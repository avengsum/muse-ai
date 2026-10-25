import json
from datetime import UTC, datetime

from sqlalchemy import select

from .database import SessionLocal
from .models import FoodOrder
from .notification_service import add_notification, send_user_push
from .swiggy_service import order_eta_minutes, order_status


def food_order_notification(database, order: FoodOrder, status: str, payload: dict):
    previous_status = order.last_notified_status
    eta = order_eta_minutes(payload)
    notification_key = status
    if status == "DELIVERED":
        title = "Order delivered"
        body = "Your Swiggy order has been delivered."
    elif eta is not None and eta <= 2 and previous_status != "ARRIVING_SOON":
        notification_key = "ARRIVING_SOON"
        title = "Arriving soon 📍"
        body = "Your Swiggy delivery partner is about 2 minutes away."
    elif status == "OUT_FOR_DELIVERY":
        title = "Order picked up 🛵"
        body = "Your Swiggy order is on its way."
    else:
        return
    if previous_status == notification_key:
        return
    order.last_notified_status = notification_key
    add_notification(database, order.user_id, title, body, "food_order")
    database.commit()
    send_user_push(
        database,
        order.user_id,
        title,
        body,
        {"url": f"/(tabs)/chat?conversation_id={order.conversation_id}", "orderId": order.swiggy_order_id},
    )


def record_food_order_status(order_id_value: str, payload: dict):
    with SessionLocal() as database:
        order = database.scalar(
            select(FoodOrder).where(FoodOrder.swiggy_order_id == order_id_value)
        )
        if order is None:
            return None
        status = order_status(payload)
        if status != "UNKNOWN":
            order.status = status
        order.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        order.updated_at = datetime.now(UTC)
        database.commit()
        food_order_notification(database, order, status, payload)
        database.refresh(order)
        return order.status
