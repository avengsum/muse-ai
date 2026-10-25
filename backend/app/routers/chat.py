import json
import logging
from datetime import UTC, datetime
from uuid import uuid4
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from ..agent_run_service import (
    agent_run_payload,
    create_agent_run_record,
    durable_chat_stream,
    owned_agent_run,
)
from ..auth import CurrentUser, get_current_user
from ..browser_runtime import browser_response
from ..callback_urls import validate_callback_url
from ..conversation_service import ensure_conversation_access, update_conversation
from ..database import SessionLocal
from ..inngest_service import (
    inngest_is_configured,
    queue_agent_run_event,
    queue_food_order_placed_event,
)
from ..message_artifacts import artifact_data, schedule_artifact
from ..models import (
    AgentRun,
    AgentRunEvent,
    BrowserRun,
    Conversation,
    FoodOrder,
    Message,
    MessageArtifact,
)
from ..schemas import (
    AgentRunEventResponse,
    AgentRunResponse,
    ChatRequest,
    ConversationResponse,
    MessageResponse,
    ScheduleMessageUpdate,
)
from ..swiggy_runtime import swiggy_connection_token
from ..quota_service import check_and_consume_question_quota
from ..swiggy_service import SwiggyAuthError, SwiggyError, SwiggyFoodClient, append_query, order_id

logger = logging.getLogger("muse_ai")
router = APIRouter()


@router.post("/api/chat/stream")
def chat_stream(payload: ChatRequest, current_user: CurrentUser = Depends(get_current_user)):
    message_text = payload.message.strip()
    callback_url = validate_callback_url(payload.callback_url)

    if not message_text:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    conversation_id = payload.conversation_id or str(uuid4())
    if callback_url:
        callback_url = append_query(callback_url, conversation_id=conversation_id)
    run_id = str(uuid4())
    dispatch_mode = "inngest" if inngest_is_configured() else "direct"

    with SessionLocal() as database:
        conversation = ensure_conversation_access(
            database,
            conversation_id,
            current_user.id,
        )
        conversation = update_conversation(
            database,
            conversation_id,
            current_user.id,
            message_text,
        )
        
        check_and_consume_question_quota(database, current_user.id, message_text)
        
        database.add(
            Message(
                conversation_id=conversation_id,
                sender="user",
                text=message_text,
            )
        )
        database.commit()
        create_agent_run_record(
            database,
            run_id=run_id,
            user_id=current_user.id,
            conversation_id=conversation_id,
            prompt=message_text,
            timezone=payload.timezone,
            callback_url=callback_url,
            dispatch_mode=dispatch_mode,
        )

    if dispatch_mode == "inngest":
        try:
            queue_agent_run_event(run_id)
        except Exception:
            logger.exception("Could not dispatch agent run; falling back to local worker")
            dispatch_mode = "direct"
            with SessionLocal() as database:
                run = database.get(AgentRun, run_id)
                if run:
                    run.dispatch_mode = "direct"
                    database.commit()

    return durable_chat_stream(
        run_id=run_id,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )


@router.get("/api/agent/runs/{run_id}", response_model=AgentRunResponse)
def get_agent_run(run_id: str, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        return agent_run_payload(owned_agent_run(database, run_id, current_user.id))


@router.get("/api/agent/runs/{run_id}/events", response_model=list[AgentRunEventResponse])
def get_agent_run_events(run_id: str, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        owned_agent_run(database, run_id, current_user.id)
        events = database.scalars(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run_id)
            .order_by(AgentRunEvent.sequence)
        ).all()
        return [
            AgentRunEventResponse(
                sequence=event.sequence,
                kind=event.kind,
                payload=json.loads(event.payload_json or "{}"),
                created_at=event.created_at,
            )
            for event in events
        ]


@router.post("/api/conversations", response_model=ConversationResponse)
def create_conversation(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        conversation = Conversation(
            id=str(uuid4()),
            user_id=current_user.id,
            title="New chat",
        )
        database.add(conversation)
        database.commit()
        database.refresh(conversation)
        return conversation


@router.get("/api/conversations", response_model=list[ConversationResponse])
def get_conversations(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        return database.scalars(
            select(Conversation)
            .where(Conversation.user_id == current_user.id)
            .order_by(Conversation.updated_at.desc())
        ).all()

class ConversationRenameRequest(BaseModel):
    title: str


@router.patch("/api/conversations/{conversation_id}", response_model=ConversationResponse)
def rename_conversation(
    conversation_id: str,
    payload: ConversationRenameRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    clean_title = payload.title.strip()[:120]
    if not clean_title:
        raise HTTPException(status_code=422, detail="Title cannot be empty")

    with SessionLocal() as database:
        conversation = ensure_conversation_access(
            database,
            conversation_id,
            current_user.id,
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.title = clean_title
        conversation.updated_at = datetime.now(UTC)
        database.commit()
        database.refresh(conversation)
        return conversation


@router.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def get_messages(conversation_id: str, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        conversation = ensure_conversation_access(database, conversation_id, current_user.id)

        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = database.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        ).all()

        browser_runs = database.scalars(
            select(BrowserRun).where(BrowserRun.conversation_id == conversation_id)
        ).all()
        browser_by_message = {
            item.message_id: browser_response(item)
            for item in browser_runs
            if item.message_id
        }

        artifacts = (
            database.scalars(
                select(MessageArtifact).where(
                    MessageArtifact.message_id.in_([message.id for message in messages])
                )
            ).all()
            if messages
            else []
        )
        artifact_by_message = {
            artifact.message_id: artifact
            for artifact in artifacts
        }

        food_orders = (
            database.scalars(
                select(FoodOrder).where(
                    FoodOrder.message_id.in_([message.id for message in messages])
                )
            ).all()
            if messages
            else []
        )
        food_order_by_message = {
            order.message_id: order
            for order in food_orders
        }

        # Reconstruct activity logs, scratchpad state, and active specialist per message
        runs = database.scalars(
            select(AgentRun).where(
                AgentRun.conversation_id == conversation_id,
                AgentRun.result_message_id.is_not(None),
            )
        ).all()
        run_by_message = {
            r.result_message_id: r.id
            for r in runs
            if r.result_message_id
        }
        run_events = (
            database.scalars(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id.in_(list(run_by_message.values())))
                .order_by(AgentRunEvent.sequence)
            ).all()
            if run_by_message
            else []
        )

        activity_by_run: dict[str, list[str]] = {}
        scratchpad_by_run: dict[str, dict] = {}
        specialist_by_run: dict[str, str] = {}
        sandbox_by_run: dict[str, dict] = {}

        for ev in run_events:
            try:
                payload = json.loads(ev.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}

            if ev.kind in {"status", "tool_started", "tool_finished", "scratchpad_updated"}:
                msg_str = payload.get("message")
                if msg_str:
                    steps = activity_by_run.setdefault(ev.run_id, [])
                    if not steps or steps[-1] != msg_str:
                        steps.append(str(msg_str))

            if ev.kind == "scratchpad_updated" and payload.get("plan"):
                scratchpad_by_run[ev.run_id] = {
                    "plan": payload.get("plan", []),
                    "currentStep": payload.get("current_step", 0),
                    "notes": payload.get("notes", ""),
                }

            if ev.kind == "agent_switched":
                spec_name = payload.get("name") or payload.get("agent")
                if spec_name:
                    specialist_by_run[ev.run_id] = str(spec_name)
            
            if ev.kind == "sandbox" and isinstance(payload.get("sandbox"), dict):
                sandbox_by_run[ev.run_id] = payload["sandbox"]

        return [
            MessageResponse(
                id=message.id,
                conversation_id=message.conversation_id,
                sender=message.sender,
                text=message.text,
                created_at=message.created_at,
                browser=browser_by_message.get(message.id),
                sandbox=sandbox_by_run.get(run_by_message.get(message.id, "")),
                schedule_confirmation=(
                    schedule_artifact(database, message.id)
                    if message.id in artifact_by_message
                    else None
                ),
                schedule_status=(
                    artifact_by_message[message.id].status
                    if message.id in artifact_by_message
                    else None
                ),
                connect_cta=(
                    artifact_data(database, message.id)
                    if message.id in artifact_by_message
                    and artifact_by_message[message.id].kind == "connect_cta"
                    else None
                ),
                swiggy_cta=(
                    artifact_data(database, message.id)
                    if message.id in artifact_by_message
                    and artifact_by_message[message.id].kind == "swiggy_connect_cta"
                    else None
                ),
                food_confirmation=(
                    artifact_data(database, message.id)
                    if message.id in artifact_by_message
                    and artifact_by_message[message.id].kind == "food_order_confirmation"
                    else None
                ),
                food_status=(
                    artifact_by_message[message.id].status
                    if message.id in artifact_by_message
                    and artifact_by_message[message.id].kind == "food_order_confirmation"
                    else None
                ),
                food_order_id=(
                    food_order_by_message[message.id].swiggy_order_id
                    if message.id in food_order_by_message
                    else None
                ),
                tool_approval=(
                    artifact_data(database, message.id)
                    if message.id in artifact_by_message
                    and artifact_by_message[message.id].kind == "tool_approval_request"
                    else None
                ),
                tool_approval_status=(
                    artifact_by_message[message.id].status
                    if message.id in artifact_by_message
                    and artifact_by_message[message.id].kind == "tool_approval_request"
                    else None
                ),
                activity=activity_by_run.get(run_by_message.get(message.id, ""), [])[-8:],
                scratchpad=scratchpad_by_run.get(run_by_message.get(message.id, "")),
                active_specialist=specialist_by_run.get(run_by_message.get(message.id, "")),
            )
            for message in messages
        ]

@router.post("/api/food/orders/{message_id}/cancel")
def cancel_food_order_confirmation(
    message_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    with SessionLocal() as database:
        message = database.get(Message, message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Food order confirmation not found")
        ensure_conversation_access(database, message.conversation_id, current_user.id)
        artifact = database.get(MessageArtifact, message_id)
        if artifact is None or artifact.kind != "food_order_confirmation":
            raise HTTPException(status_code=404, detail="Food order confirmation not found")
        if artifact.status != "pending":
            raise HTTPException(status_code=409, detail="This food order can no longer be cancelled")

        artifact.status = "cancelled"
        database.commit()
    return {"success": True, "status": "cancelled"}


@router.patch("/api/messages/{message_id}/schedule")
def update_schedule_message(
    message_id: int,
    payload: ScheduleMessageUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    status = payload.status.strip().lower()

    if status not in {"pending", "cancelled"}:
        raise HTTPException(status_code=422, detail="Schedule status is invalid")

    with SessionLocal() as database:
        message = database.get(Message, message_id)

        if message is None:
            raise HTTPException(status_code=404, detail="Message not found")

        conversation = ensure_conversation_access(
            database,
            message.conversation_id,
            current_user.id,
        )
        artifact = database.get(MessageArtifact, message_id)

        if conversation is None or artifact is None:
            raise HTTPException(status_code=404, detail="Schedule confirmation not found")

        artifact.status = status
        artifact.updated_at = datetime.now(UTC)
        database.commit()
        return {"success": True, "status": status}


@router.delete("/api/conversations/{conversation_id}/messages")
def clear_messages(conversation_id: str, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        conversation = ensure_conversation_access(database, conversation_id, current_user.id)

        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        message_ids = database.scalars(
            select(Message.id).where(Message.conversation_id == conversation_id)
        ).all()

        if message_ids:
            database.execute(delete(MessageArtifact).where(MessageArtifact.message_id.in_(message_ids)))

        run_ids = database.scalars(
            select(AgentRun.id).where(AgentRun.conversation_id == conversation_id)
        ).all()
        if run_ids:
            database.execute(delete(AgentRunEvent).where(AgentRunEvent.run_id.in_(run_ids)))
            database.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))

        database.execute(delete(Message).where(Message.conversation_id == conversation_id))
        database.execute(delete(BrowserRun).where(BrowserRun.conversation_id == conversation_id))
        conversation.title = "New chat"
        conversation.active_agent = "cooper"
        conversation.summary = None
        conversation.summarized_until_message_id = None
        conversation.updated_at = datetime.now(UTC)
        database.commit()
        return {"success": True}


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        conversation = ensure_conversation_access(database, conversation_id, current_user.id)

        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        message_ids = database.scalars(
            select(Message.id).where(Message.conversation_id == conversation_id)
        ).all()

        if message_ids:
            database.execute(delete(MessageArtifact).where(MessageArtifact.message_id.in_(message_ids)))

        run_ids = database.scalars(
            select(AgentRun.id).where(AgentRun.conversation_id == conversation_id)
        ).all()
        if run_ids:
            database.execute(delete(AgentRunEvent).where(AgentRunEvent.run_id.in_(run_ids)))
            database.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))

        database.execute(delete(Message).where(Message.conversation_id == conversation_id))
        database.execute(delete(BrowserRun).where(BrowserRun.conversation_id == conversation_id))
        database.delete(conversation)
        database.commit()
        return {"success": True}


class FoodOrderConfirmRequest(BaseModel):
    payment_method: str = "COD"  # "COD" or "UPI"
    generate_upi_qr: bool = False
    intent_app: str | None = None


def _find_in_dict(data, *keys):
    if isinstance(data, dict):
        for k in keys:
            if data.get(k) is not None:
                return data[k]
        for v in data.values():
            found = _find_in_dict(v, *keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_in_dict(item, *keys)
            if found is not None:
                return found
    return None


@router.post("/api/food/orders/{message_id}/confirm")
def confirm_food_order(
    message_id: int,
    payload: FoodOrderConfirmRequest | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    req = payload or FoodOrderConfirmRequest()
    payment_method = (req.payment_method or "COD").strip().upper()

    with SessionLocal() as database:
        message = database.get(Message, message_id)
        if message is None:
            raise HTTPException(
                status_code=404, detail="Food order confirmation not found"
            )

        conversation = ensure_conversation_access(
            database,
            message.conversation_id,
            current_user.id,
        )
        artifact = database.get(MessageArtifact, message_id)
        if (
            conversation is None
            or artifact is None
            or artifact.kind != "food_order_confirmation"
        ):
            raise HTTPException(
                status_code=404, detail="Food order confirmation not found"
            )

        existing_order = database.scalar(
            select(FoodOrder).where(FoodOrder.message_id == message_id)
        )
        if existing_order and existing_order.status == "PLACED":
            return {
                "success": True,
                "status": existing_order.status,
                "order_id": existing_order.swiggy_order_id,
            }

        if artifact.status not in {"pending", "pending_payment", "unknown"}:
            raise HTTPException(
                status_code=409,
                detail=f"This food order is already {artifact.status}",
            )

        token = swiggy_connection_token(database, current_user.id)
        if not token:
            raise HTTPException(
                status_code=401,
                detail="Your Swiggy session expired. Reconnect Swiggy and review the cart again.",
            )

        confirmation = artifact_data(database, message_id) or {}
        address_id = confirmation.get("address_id")
        client = SwiggyFoodClient(token)

        # Resolve addressId from get_addresses if not stored on the confirmation artifact
        if not address_id:
            try:
                addr_res = client.call_tool("get_addresses", {})
                address_id = _find_in_dict(addr_res, "addressId", "id")
            except Exception:
                pass

        order_args: dict = {"paymentMethod": payment_method}
        if address_id:
            order_args["addressId"] = str(address_id)

        if payment_method == "UPI":
            if req.generate_upi_qr or not req.intent_app:
                order_args["generateUPIQR"] = True
            else:
                order_args["intentApp"] = req.intent_app

        artifact.status = "processing"
        database.commit()

        try:
            provider_order = client.call_tool("place_food_order", order_args)
            provider_order_id = order_id(provider_order) or _find_in_dict(
                provider_order, "orderId", "order_id"
            )
            if not provider_order_id:
                raise SwiggyError("Swiggy did not return an order ID", 502)
        except SwiggyAuthError as error:
            artifact.status = "pending"
            database.commit()
            raise HTTPException(status_code=401, detail=str(error)) from error
        except SwiggyError as error:
            if error.status_code and error.status_code >= 500:
                try:
                    client.call_tool("get_food_orders", {})
                except Exception:
                    logger.exception("Swiggy order reconciliation failed")
                artifact.status = "unknown"
            else:
                artifact.status = "pending"
            database.commit()
            raise HTTPException(status_code=502, detail=str(error)) from error
        except Exception as error:
            artifact.status = "pending"
            database.commit()
            raise HTTPException(status_code=502, detail=str(error)) from error

        paas_id = _find_in_dict(
            provider_order, "paasId", "paas_id", "transactionId"
        )
        upi_intent_url = _find_in_dict(
            provider_order,
            "intentUrl",
            "upiIntentUrl",
            "upi_intent_url",
            "deepLink",
            "qrString",
            "qrPayload",
        )
        qr_code_data = _find_in_dict(
            provider_order,
            "qrCode",
            "qr_code",
            "qrImage",
            "qrData",
            "upiQr",
            "qrString",
        )
        lat_val = _find_in_dict(provider_order, "lat", "latitude")
        lng_val = _find_in_dict(provider_order, "lng", "longitude")

        is_pending_payment = payment_method == "UPI"
        final_status = "PENDING_PAYMENT" if is_pending_payment else "PLACED"
        artifact_status = "pending_payment" if is_pending_payment else "placed"

        confirmation["order_id"] = str(provider_order_id)
        confirmation["order_status"] = final_status
        confirmation["paas_id"] = paas_id
        confirmation["address_id"] = address_id
        confirmation["lat"] = lat_val
        confirmation["lng"] = lng_val
        confirmation["upi_intent_url"] = upi_intent_url
        confirmation["qr_code"] = qr_code_data
        artifact.data_json = json.dumps(
            confirmation, ensure_ascii=False, default=str
        )
        artifact.status = artifact_status

        if not is_pending_payment:
            status_note = f"\n\n✅ Order placed on Swiggy (Order ID: {provider_order_id})."
            if status_note.strip() not in (message.text or ""):
                message.text = f"{(message.text or '').strip()}{status_note}".strip()

        if existing_order is None:
            food_order = FoodOrder(
                id=str(uuid4()),
                user_id=current_user.id,
                conversation_id=message.conversation_id,
                message_id=message.id,
                swiggy_order_id=str(provider_order_id),
                status=final_status,
                payload_json=json.dumps(
                    provider_order, ensure_ascii=False, default=str
                ),
            )
            database.add(food_order)
        else:
            existing_order.swiggy_order_id = str(provider_order_id)
            existing_order.status = final_status
            existing_order.payload_json = json.dumps(
                provider_order, ensure_ascii=False, default=str
            )

        database.commit()

    if not is_pending_payment:
        try:
            queue_food_order_placed_event(str(provider_order_id))
        except Exception:
            logger.exception(
                "Could not queue Swiggy order tracking",
                extra={"order_id": provider_order_id},
            )

    return {
        "success": True,
        "status": artifact_status,
        "order_id": str(provider_order_id),
        "paas_id": paas_id,
        "upi_intent_url": upi_intent_url,
        "qr_code": qr_code_data,
        "raw": provider_order,
    }


@router.post("/api/food/orders/{message_id}/check-payment")
def check_swiggy_upi_payment(
    message_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    with SessionLocal() as database:
        message = database.get(Message, message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Order not found")
        ensure_conversation_access(
            database, message.conversation_id, current_user.id
        )
        artifact = database.get(MessageArtifact, message_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Order artifact not found")

        token = swiggy_connection_token(database, current_user.id)
        if not token:
            raise HTTPException(status_code=401, detail="Swiggy session expired")

        confirmation = artifact_data(database, message_id) or {}
        order_id_val = confirmation.get("order_id")
        paas_id_val = confirmation.get("paas_id")
        address_id_val = confirmation.get("address_id")
        lat_val = confirmation.get("lat")
        lng_val = confirmation.get("lng")

        client = SwiggyFoodClient(token)
        status_args: dict = {"paasId": str(paas_id_val or order_id_val)}
        if order_id_val:
            status_args["orderId"] = str(order_id_val)
        if address_id_val:
            status_args["addressId"] = str(address_id_val)
        if lat_val is not None:
            status_args["lat"] = lat_val
        if lng_val is not None:
            status_args["lng"] = lng_val

        pay_status = client.call_tool("check_payment_status", status_args)
        is_success = bool(
            _find_in_dict(pay_status, "isTerminalSuccess")
            or str(
                _find_in_dict(pay_status, "status", "paymentStatus") or ""
            ).upper()
            == "SUCCESS"
        )
        already_confirmed = bool(_find_in_dict(pay_status, "confirmed"))

        if is_success:
            if not already_confirmed and order_id_val and address_id_val:
                confirm_args: dict = {
                    "orderId": str(order_id_val),
                    "addressId": str(address_id_val),
                }
                if lat_val is not None:
                    confirm_args["lat"] = lat_val
                if lng_val is not None:
                    confirm_args["lng"] = lng_val
                try:
                    client.call_tool("confirm_order", confirm_args)
                except Exception:
                    pass

            artifact.status = "placed"
            confirmation["order_status"] = "PLACED"
            artifact.data_json = json.dumps(
                confirmation, ensure_ascii=False, default=str
            )
            status_note = f"\n\n✅ UPI Payment received! Order placed on Swiggy (Order ID: {order_id_val})."
            if status_note.strip() not in (message.text or ""):
                message.text = f"{(message.text or '').strip()}{status_note}".strip()
            database.commit()
            try:
                queue_food_order_placed_event(str(order_id_val))
            except Exception:
                pass
            return {
                "status": "placed",
                "order_id": order_id_val,
                "payment": pay_status,
            }

        return {
            "status": "pending_payment",
            "order_id": order_id_val,
            "payment": pay_status,
        }

class ToolActionConfirmRequest(BaseModel):
    arguments: dict | None = None


@router.post("/api/actions/{message_id}/confirm")
async def confirm_tool_action(
    message_id: int,
    payload: ToolActionConfirmRequest | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    from ..composio_service import execute_composio_tool_action
    from ..conversation_service import get_agent_session

    with SessionLocal() as database:
        message = database.get(Message, message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Action request not found")

        conversation = ensure_conversation_access(
            database, message.conversation_id, current_user.id
        )
        artifact = database.get(MessageArtifact, message_id)
        if (
            conversation is None
            or artifact is None
            or artifact.kind != "tool_approval_request"
        ):
            raise HTTPException(status_code=404, detail="Action approval card not found")

        if artifact.status == "completed":
            return {"success": True, "status": "completed", "data": artifact_data(database, message_id)}

        if artifact.status not in {"pending", "failed"}:
            raise HTTPException(status_code=409, detail=f"Action is already {artifact.status}")

        saved_data = artifact_data(database, message_id) or {}
        tool_name = saved_data.get("tool_name")
        final_args = (
            payload.arguments
            if (payload and isinstance(payload.arguments, dict))
            else saved_data.get("arguments") or {}
        )

        session = get_agent_session(database, current_user.id)
        if session is None:
            raise HTTPException(status_code=503, detail="Workspace integration session unavailable")
        composio_session_id = session.session_id

        artifact.status = "executing"
        saved_data["arguments"] = final_args
        artifact.data_json = json.dumps(saved_data, ensure_ascii=False, default=str)
        database.commit()

    try:
        result = await execute_composio_tool_action(
            composio_session_id,
            tool_name,
            final_args,
            multi_wrapper=saved_data.get("_multi_wrapper"),
        )
    except Exception as error:
        with SessionLocal() as database:
            artifact = database.get(MessageArtifact, message_id)
            if artifact:
                artifact.status = "pending"
                database.commit()
        raise HTTPException(status_code=502, detail=str(error)) from error

    with SessionLocal() as database:
        message = database.get(Message, message_id)
        artifact = database.get(MessageArtifact, message_id)
        if artifact:
            saved_data["result"] = str(result)[:2000]
            artifact.data_json = json.dumps(saved_data, ensure_ascii=False, default=str)
            artifact.status = "completed"
            artifact.updated_at = datetime.now(UTC)

        app_label = saved_data.get("app_name") or "Workspace"
        action_label = saved_data.get("action_label") or tool_name
        status_note = f"\n\n✅ Executed **{app_label}: {action_label}**."
        if message and status_note.strip() not in (message.text or ""):
            message.text = f"{(message.text or '').strip()}{status_note}".strip()
        database.commit()

    return {
        "success": True,
        "status": "completed",
        "tool_name": tool_name,
        "arguments": final_args,
        "result": str(result)[:1000],
    }


@router.post("/api/actions/{message_id}/cancel")
def cancel_tool_action(
    message_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    with SessionLocal() as database:
        message = database.get(Message, message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Action request not found")

        ensure_conversation_access(database, message.conversation_id, current_user.id)
        artifact = database.get(MessageArtifact, message_id)
        if artifact is None or artifact.kind != "tool_approval_request":
            raise HTTPException(status_code=404, detail="Action approval card not found")

        artifact.status = "cancelled"
        artifact.updated_at = datetime.now(UTC)
        database.commit()

    return {"success": True, "status": "cancelled"}