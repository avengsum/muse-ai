# Lean Agents SDK implementation plan

Prepared for Cooper / Muse AI on 10 October 2026. This is an implementation plan, not a completed integration or production-readiness certification. Provider access and live payment behavior have not been tested.

**Revised scope:** flights and hotels are recommendations only, delivered as an illustrated trip report. Shopping is recommendations only. Neither specialist may book, reserve, create carts, purchase or take payments. Real image URLs are retrieved, not generated. Swiggy food ordering and Dineout reservations remain a separate, explicitly approved capability; they are not triggered by a trip recommendation.

## 1. Recommended direction

Use the **Python OpenAI Agents SDK inside the existing FastAPI backend**. Keep Expo as the interface, PostgreSQL as the source of truth, Inngest for durable work, Composio for existing integrations, and Browserbase for browser tasks. The SDK supplies orchestration; it does not supply booking inventory, merchant access, or payment authorization. [OpenAI SDK overview](https://developers.openai.com/api/docs/guides/agents/sdk)

Build one runtime with Cooper plus three small specialist configurations:

| Agent | Responsibilities | Integration and initial boundary |
| --- | --- | --- |
| Cooper | General assistant, existing tools, route requests | Existing Composio, schedule and phone-call flows |
| Food & Dining | Find meals, prepare carts, coupons, approved food orders and restaurant reservations | Swiggy Food/Dineout MCP; existing approval/payment design |
| Trip Planner | Research flights, hotels, places and logistics; produce an illustrated, personalized itinerary | Four read-only tools: flight search, hotel search, destination research and image lookup; no booking/payment tools |
| Shopping Research | Compare products, variants, sellers, delivered prices, reviews and returns | Read-only product/web research and sourced images; recommendation report with retailer links only |

Use handoffs so one specialist owns a branch. Preserve the last active specialist for follow-ups and permit a bounded handoff back to Cooper when the subject changes. Do not run all agents for every message. Trip Planner is one agent using tools, not four autonomous agents plus a writer. No extra planning/critic layer, payment agent, separate agent servers, or second orchestration framework. [OpenAI handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration)

**Recommended first release:** the recommendation-only Trip Planner and Shopping Research reports. They can ship without payment infrastructure or Swiggy access. Keep Swiggy food ordering and Dineout on their own release track with approvals. Flight/hotel bookings and shopping checkout are excluded from this roadmap, not deferred implementation steps.

## 2. What the current code actually needs

| Current code | Finding | Planned change |
| --- | --- | --- |
| [ai_service.py](C:/Users/sy710/Desktop/agents/personal/backend/app/ai_service.py) | OpenAI client targets Groq; manual eight-iteration tool loop; completed replies split into 14-character chunks | Replace orchestration with async SDK Runner and actual generation events |
| [composio_service.py](C:/Users/sy710/Desktop/agents/personal/backend/app/composio_service.py) | Uses OpenAIResponsesProvider and per-user sessions | Adopt OpenAIAgentsProvider; preserve accounts and enforce tool permissions |
| [main.py](C:/Users/sy710/Desktop/agents/personal/backend/app/main.py) | Browser tasks already auto-trigger from keywords; chat and browser execution are separate | Expose browser work as an agent tool; retain explicit Browser mode as a user preference |
| [main.py](C:/Users/sy710/Desktop/agents/personal/backend/app/main.py) | History is the latest 20 text messages; chat stream holds a database session | Preserve full tool history; use short database transactions |
| [inngest_service.py](C:/Users/sy710/Desktop/agents/personal/backend/app/inngest_service.py) | Durable scheduling and browser continuation already exist | Reuse for ordinary agent runs, approvals, and payment reconciliation |
| [models.py](C:/Users/sy710/Desktop/agents/personal/backend/app/models.py) | Messages, browser runs, scheduled runs and artifacts exist | Add run/action/connection state; retain existing UI records |
| [api.js](C:/Users/sy710/Desktop/agents/personal/src/services/api.js) | Uses newline-delimited JSON, not SSE | Keep NDJSON and existing events; add research progress and structured report delivery, plus separate Swiggy action events |

The statement that Browserbase must always be manually triggered is therefore inaccurate for this checkout. The missing pieces are unified orchestration, sourced research/report rendering and, separately for Swiggy, reliable transaction handling.

Keep existing calendar/email connections, schedule confirmation, call actions and browser previews working during migration. Update scheduled execution callers too; replacing only the chat endpoint would leave two different agent implementations.

## 3. Small implementation footprint

Add focused backend modules in `C:/Users/sy710/Desktop/agents/personal/backend/app/`, only as each capability ships:

| Proposed module | Owns |
| --- | --- |
| `agent_definitions.py` | Four agent configurations, instructions, allowed tools and handoffs |
| `run_service.py` | Runner lifecycle, history, pause/resume, persistence and NDJSON events |
| `research_service.py` | Small read-only flight, hotel, destination, image and product adapters; normalize and bound tool results |
| `report_schema.py` | Pydantic TripReport/ShoppingReport contracts and evidence references |
| `action_service.py` | Quotes, approval validation, execution claims and reconciliation |
| `swiggy_service.py` | Per-user OAuth, MCP connections, typed provider operations and payment status |
| `agent_routes.py` | Thin authenticated run/action/connection endpoints |

Modify the existing services rather than duplicating them. Retire the old manual loop after compatibility tests pass. Add `ReportCard.js` and `ReportView.js` under `C:/Users/sy710/Desktop/agents/personal/src/components/` for trip/product reports. Add `ActionCard.js` for the separate Swiggy workflow. Do not add a module or agent per research tool, booking/payment adapters for travel/shopping, or a generic provider/plugin framework.

Backend dependency additions, when implementation begins:

```powershell
# Run from C:\Users\sy710\Desktop\agents\personal\backend
uv add openai-agents composio-openai-agents
```

Pin the resolved compatible set in `uv.lock`; migrate and then remove `composio-openai` when unused. Use a versioned migration tool, such as Alembic, for the new schema rather than extending startup DDL. Add token encryption through the deployment's secret-management facility, or a maintained cryptography package if necessary. Do not add Redis, Celery, LangChain, a vector database, a Node backend, or a mobile Agents SDK.

Use backend-only `OPENAI_API_KEY` and an explicit `OPENAI_MODEL`. This is an intentional model-provider migration from the current Groq configuration. Evaluate tool selection, latency and cost before choosing a model; don't assume an OpenAI-compatible endpoint supports every SDK feature. Keep the legacy path behind a rollout flag, but never let it execute new commerce tools.

Composio documents `OpenAIAgentsProvider` as its SDK integration. Restrict tools to the authenticated user's connected accounts. Gate the underlying write operation, including calls through meta-tools; approving a generic executor once must not authorize every future operation. Prefer a narrow direct-tool set for these workflows. [Composio integration guidance](https://docs.composio.dev/kb/guide/toolkits-openai)

### Small SDK shape

Illustrative structure only; the injected services/tool factories and report schemas are application code to implement, not SDK exports. This intentionally gives only Food & Dining access to the guarded action tool.

```python
from agents import Agent, function_tool
from .report_schema import TripReport, ShoppingReport

def build_agents(model, actions, food_tools, trip_tools, shop_tools):
    # actions is bound server-side to the authenticated user and run.
    @function_tool(needs_approval=True)
    async def execute_action(action_id: str, version: int) -> str:
        """Execute exactly one reviewed, server-stored action."""
        return await actions.execute_approved(action_id, version)

    def specialist(name, instructions, tools, schema=None):
        return Agent(
            name=name,
            model=model,
            instructions=instructions,
            tools=tools,
            output_type=schema,
        )

    food = specialist("Food & Dining", "Prepare requested food orders/reservations.",
                      [*food_tools, execute_action])
    trip = specialist("Trip Planner", "Research and report; never book or pay.",
                      trip_tools, TripReport)
    shop = specialist("Shopping Research", "Recommend only; never cart or purchase.",
                      shop_tools, ShoppingReport)
    return Agent(
        name="Cooper",
        model=model,
        instructions="Help the user; route domain-specific work to a specialist.",
        handoffs=[food, trip, shop],
    )
```

Production definitions also need the existing Cooper tools, return handoffs, domain-specific policies and capability flags. Provider write tools must not also be exposed through an unguarded path. The SDK can interrupt approval-required calls and resume their saved state; your backend decides who may approve the exact call. [OpenAI approval lifecycle](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)

## 4. Shared approval system for Swiggy and existing write tools

Trip Planner and Shopping Research do not need purchase approvals because they cannot transact. Keep the following ordinary, deterministic backend code for Swiggy and existing write integrations. The model proposes an operation; it never sets an `approved` flag or controls credentials. Handing off from a trip report is not permission to place a food order or reserve a table: that needs a separate user request and approval.

1. **Prepare:** Re-read the live provider cart, offer or slot. Create an Action containing normalized provider data, not a model-written price summary.
2. **Review:** Show items/variants, quantities, merchant, date/time/guests where applicable, delivery address, discounts, taxes/GST, fees, tip, currency, final total and cancellation terms. Use integer minor units or exact decimals for money.
3. **Pause:** When `execute_action` is requested, persist the SDK interruption and action reference. Return an approval card; do not execute yet.
4. **Approve:** An authenticated button request identifies the action and version. The backend verifies ownership, pending status, expiry and exact pending tool-call binding. Persist the decision before dispatching continuation.
5. **Revalidate:** Fetch live state again. A changed price, item, address, payment method, booking slot or policy invalidates approval and requires a new review.
6. **Execute:** Atomically claim the action. Fixed server-side dispatch selects the adapter and validated payload. Repeated approval taps return the same action instead of making a new order.
7. **Verify:** Store provider order/booking/payment identifiers. Display success only after authoritative confirmation; payment pending and booking pending are separate states.

Use `result.interruptions` and `result.to_state()` to persist the pause. Resume only the selected, verified interruption; never copy an example that approves every interruption in a loop. Ordinary text saying "approved", a webpage instruction, and the current `APPROVED SCHEDULED TASK` prompt prefix are not authorization. A scheduled search must still pause before a new purchase.

Approval should bind a quote hash, version, expiry, owner, run and operation. Keep one serial commit per run and a per-user/provider cart lock. Other devices can still change a provider cart, so locks do not replace revalidation. If a provider cannot enforce the reviewed transaction parameters sufficiently, retain user checkout rather than claim a guaranteed spending limit.

For ambiguous timeouts, mark the action `unknown` and reconcile. Local uniqueness prevents duplicate app submissions; it cannot manufacture provider-side exactly-once execution. Swiggy explicitly identifies order placement and table booking as unsafe to blindly retry. Do not let an Inngest retry repeat these calls, and do not treat temporarily empty order history as proof no order exists. [Swiggy production guidance](https://mcp.swiggy.com/builders/docs/build/ship-to-production/)

## 5. Swiggy integration

### Access and authentication

Start with local fixtures, apply for Swiggy access, then validate against staging before production. Staging/production require the relevant onboarding and OAuth redirect allowlisting; having a public MCP URL is not production authorization. [Access requirements](https://mcp.swiggy.com/builders/docs/operate/access/)

Implement per-user OAuth 2.1 with PKCE and a single-use state tied to the app user. Use a registered HTTPS backend callback, exchange the code on the backend, store tokens encrypted, and return to the app with only an opaque completion reference. Phone/OTP entry stays on Swiggy's own page. Never use one account/token for all users. The current delegated-auth documentation does not provide usable refresh tokens in v1; use returned expiry and support reauthorization, not an invented refresh flow. Revoke and delete credentials on disconnect. [Delegated authentication](https://mcp.swiggy.com/builders/docs/start/enterprise/delegated-auth/)

Use SDK-managed Streamable HTTP connections to:

- Food: `https://mcp.swiggy.com/food`
- Restaurant reservations: `https://mcp.swiggy.com/dineout`
- Optional later grocery capability: `https://mcp.swiggy.com/im`

Python's documented integration passes the user's bearer token in `MCPServerStreamableHttp` headers. Keep connection lifecycle scoped to a run segment; reconstruct it after delayed approval instead of keeping a socket open. Never expose the token as a tool argument or prompt. [Swiggy Python connector](https://mcp.swiggy.com/builders/docs/start/developer/build-an-agent/)

### Tools and food flow

Capture `tools/list` schemas in staging and contract-test the subset we use. The service should expose narrowly typed operations, not an unrestricted `call_tool(name, arguments)` to the model. Namespace by server because payment tool names overlap.

Allow discovery/menu/cart/coupon tools within the user's request. Keep `place_food_order`, `book_table`, checkout, finalization and destructive actions inside the guarded service. Cart preparation is still a mutation: do not erase a pre-existing cart or change restaurants without consent.

Food sequence: resolve the chosen saved address; find open restaurants; inspect menu and required add-ons; prepare cart; apply eligible coupons; fetch the authoritative final cart; prepare approval; place after approval; track the returned order. Enforce the documented ₹1,000 cart cap as a configurable provider constraint and verify it in staging. Never split an order automatically to bypass a cap. [Food recipe](https://mcp.swiggy.com/builders/docs/build/recipes/order-food/)

Dietary tags are evidence, not a guarantee about allergens or cross-contamination. Ask when preferences are ambiguous; do not infer an address or dietary requirement from unrelated conversation.

### UPI and the QR-to-app experience

Swiggy's newer payment recipe supports UPI, including a returned `data.bridgeUrl`: a hosted page with a QR and a button to open a UPI app. Use available methods returned by `get_payment_options`; present the selected method in approval. After approved order creation, open that provider payment link. This avoids building a QR renderer or manufacturing a UPI URI. [Swiggy UPI recipe](https://mcp.swiggy.com/builders/docs/build/recipes/pay-with-upi/)

The Expo client is not automatically an MCP widget host. The backend must poll payment status using the returned identifiers and bounded provider timing; it must not depend on the chat screen remaining open. A browser return, screenshot or user message is not payment confirmation. [Payment status reference](https://mcp.swiggy.com/builders/docs/reference/food/check_payment_status/)

Keep finalization deterministic. Food confirmation requires provider-returned order/address/location fields; call it only for successful payment that has not already auto-confirmed. Preserve payment and order states independently, including refund or unresolved outcomes. [Confirmation contract](https://mcp.swiggy.com/builders/docs/reference/food/confirm_order/)

**Resolve documentation inconsistencies before release:** some examples use `COD`, others `Cash`; use the actual schema/method returned. The UPI recipe suggests finalization after a pending timeout, while the confirmation reference permits successful payment only. Fail closed on pending and obtain a verified staging/provider contract before enabling live finalization. Do not copy conflicting examples verbatim.

UPI authentication stays with the user in their payment app. Closing the payment window is not a confirmed failure. Do not automatically create a second order or switch to Cash while the first payment is unresolved.

### Restaurant reservations

Food & Dining can use Dineout to resolve location, search restaurants, inspect details and slots, prepare a dated party-size approval, book, and verify booking status. Persist the confirmation number. Paid offers need their own reviewed amount and payment step; a table reservation is not permission to buy a dining package. Trip Planner may recommend restaurants but cannot call the reservation operation. [Dineout recipe](https://mcp.swiggy.com/builders/docs/build/recipes/book-a-table/)

## 6. Recommendation-only Trip Planner and Shopping Research

### Trip Planner: four tools, one final synthesis

Gather origin, destination or interests, travel dates/flexibility, adults/children, rooms, total budget/currency, pace, dietary/accessibility needs and preferences. Ask concise questions for missing essentials. If dates or destination remain flexible, generate an explicitly provisional inspiration report instead of pretending to have date-specific live fares. No passport, payment card or booking identity collection is needed.

| Tool | Inputs | Normalized results |
| --- | --- | --- |
| `search_flights` | Origin/destination, dates, passenger mix, cabin, budget and stop constraints | Itinerary/offer ID, airline, local times/timezones, duration, stops, baggage, fare rules, per-person/group price basis, source link and checked time |
| `search_hotels` | Destination/area, check-in/out, room/guest mix, budget and amenities | Property ID, neighborhood, room/meal basis, review score/count/source, star classification separately, cancellation policy, full-stay price, source link and checked time |
| `research_destination` | Destination, dates, interests, pace, dietary/accessibility constraints | Sourced attractions, opening days/hours, ticket estimates, neighborhoods, food options, transport guidance, seasonal considerations and itinerary constraints |
| `find_images` | Selected destination, exact places/properties, desired image count | Verified asset IDs, real image URLs, related entity IDs, source page, credit/license metadata, dimensions and descriptive alt text |

These are ordinary function tools backed by authorized read-only data sources, not four separate LLM agents. Select a flight/hotel search provider by coverage, freshness, permitted display/linking, production access and cost; do not claim a provider is integrated until its live contract is tested. A search API offer may not include a consumer deep link: use a verified airline/hotel source page and label it accordingly, never invent a checkout URL. Prefer structured provider data for prices and availability. Use web retrieval for destination research and gaps; public-page estimates must be labelled, not promoted to live quotes.

Execution sequence:

1. Resolve the request and hard constraints. Explicitly distinguish per-person from whole-trip budgets.
2. Run independent flight, hotel and destination searches with bounded concurrency, timeouts and per-tool result limits. Preserve a partial result if one source fails.
3. Normalize and deduplicate results. Rank valid options, identify a preferred hotel area and feasible arrival/departure windows, then make a focused follow-up search only when a gap matters.
4. Fetch images for the actual shortlisted properties/places, not an unrelated generic destination gallery.
5. Give the compact evidence bundle to the same Trip Planner for a final synthesis. The model explains trade-offs and writes the day-by-day narrative; it does not invent source facts or URLs. No separate report-writer agent is needed.
6. Validate the structured report, recompute budgets, resolve source/image IDs to trusted records, persist the artifact and render it in Expo. Expose unresolved facts rather than hiding them.

The user sees progress such as "Comparing flights", "Finding places to stay", "Planning your days" and "Preparing your trip report". Do not stream raw structured-output JSON into the chat bubble.

### What makes the recommendations good

Treat "best" as best for this user's constraints among the searched sources, not an unsupported claim to have searched the entire market. Enforce hard requirements first, then explain ranking:

- Flights: all-in observed fare, usable travel times, total duration, stops/connection feasibility, baggage and flexibility. Show best overall, lowest-priced found and most convenient where the results support those distinctions. A made-up flight/airline rating is not a ranking signal; use ratings or reliability data only with an identified source and date.
- Hotels: full-stay cost, location relative to the itinerary, guest-review score and count, requested amenities, room basis and cancellation conditions. Do not confuse star classification with guest ratings or directly compare unlike rating scales.
- Itinerary: group nearby activities, allow meals/rest/transfers, respect opening days, arrival/departure buffers, party needs and budget. Describe travel times as estimates unless sourced from a route service. Distinguish seasonal weather expectations from a dated forecast.
- Evidence: every price/rating/time-sensitive claim points to a retrieved source. Use "not available" where appropriate. A failed flight tool can still yield a useful partial itinerary, but must not produce fabricated flight cards.

Store monetary values as exact amounts with currency, tax/fee inclusion and price basis. Compute hotel totals from room count and nights, and flights from the stated passenger basis without double-counting. Label currency conversions and uncertainty. One preferred combination determines the budget; alternative flights/hotels are not added to it.

### Real image URLs, not generated images

Use provider-authorized hotel/product photos for exact entities, and a licensed photo-search API for destinations/attractions. Unsplash is one possible destination-photo source: its API requires returned image URLs to be embedded directly and photographer/Unsplash attribution. Follow its full API guidelines, including applicable tracking and production access requirements. [Unsplash API documentation](https://unsplash.com/documentation)

An arbitrary URL found in web search does not establish permission to display its image. Keep the source page and credit with every asset. Match the named place/property; a scenic stock photo must be labelled illustrative and must never stand in for an exact hotel room. Missing images get a neutral placeholder, not image generation. No ImageGen integration, base64 image payloads or stock-photo substitution disguised as evidence.

The model selects only asset IDs that the image tool returned; the backend resolves URLs. Permit HTTPS and approved image hosts, bound image counts/sizes and validate redirects if the backend fetches anything. Never turn URL validation into unrestricted server-side fetching: reject private/internal destinations and credential-bearing URLs. Keep image-provider secrets server-side and do not persist expiring URLs as permanent assets; refresh permitted URLs from stable provider IDs. Respect provider-specific caching and attribution rules.

### Final trip report contract

Use `output_type=TripReport` with a small Pydantic schema. Typed output makes the report renderable; it does not establish factual correctness. Backend evidence validation is still required. [SDK structured outputs](https://developers.openai.com/api/docs/guides/agents/define-agents)

The schema should contain:

- `schema_version`, `status` (`needs_input`, `partial`, `complete`), `questions`, `generated_at` and stated trip assumptions/constraints.
- Title, concise overview, destination, dates, travelers and a hero image reference.
- A small flight shortlist and hotel shortlist with evidence IDs, recommendation reasons, trade-offs, observed prices and source links resolved by the backend.
- Day-by-day morning/afternoon/evening activities, place references, practical notes, estimated costs, transport and relevant photos.
- The recommended flight/hotel combination, transparent budget breakdown, optional alternatives and contingency suggestions.
- Useful restaurant recommendations, packing/logistics notes where supported, limitations and a cited source list.

Facts and URLs come from the evidence registry, not free-text model output. Resolve only IDs present in this run's retrieved evidence; reject unknown references, infeasible dates and arithmetic mismatches. Bound shortlist length and activities/images per day. On invalid output, allow one bounded repair or return a partial result; do not silently claim completion. Handle model refusal and incomplete responses explicitly. [Structured-output limitations](https://developers.openai.com/api/docs/guides/structured-outputs)

Buttons say "View flight source", "View hotel" or "View place". They open a user-selected external page; there is no booking action, availability guarantee or payment state. Follow-ups such as "make day two relaxed" revise the report while reusing still-valid evidence; date, passenger or room changes trigger fresh relevant searches.

### Shopping Research: same pattern, no cart

Use small read-only tools for `search_products`, `research_product_reviews` and the shared image lookup when merchant-provided product images are insufficient. Ask for category, budget, region, exact variant/size and priorities. Search several available sellers and compare like-for-like models, total delivered price, observed availability, warranty, returns and review evidence. Keep unavailable shipping/tax fields explicit. Potential coupons are unverified until the user checks them; the agent does not apply them.

Return a `ShoppingReport` with best overall/value/alternative picks where justified, real product photos, a compact comparison, pros/cons, reasons tailored to the user, evidence references, last-checked times and retailer links. Distinguish retailer listings and manufacturer claims from independent reviews; don't invent hands-on experience. The user independently decides what to do on the retailer site.

Remove cart creation, coupon application, checkout, purchase execution, wallet connections, virtual cards and Stripe/Shop Pay/PayPal integration from this agent and its roadmap. No payment keys or purchase Action records are needed for these reports.

### Enforce read-only scope in code

Trip/shopping tool factories expose only their named research adapters. They receive no `execute_action`, raw Swiggy MCP, write-capable Composio executor, arbitrary shell or general checkout/browser-control tool. Prefer retrieval/structured APIs; reuse Browserbase only behind constrained, vetted public-research adapters without authenticated customer sessions. If a source cannot be accessed safely, return a limitation or external link instead of automating it. A prompt saying "don't pay" is not the access-control boundary.

Keep Swiggy account cookies, tokens and all transaction capabilities out of these research contexts. Recommendations do not authorize another agent to order or reserve anything.

## 7. Persistence and APIs

Add these compact tables through reviewed migrations. Recommendation reports need AgentRun/AgentRunEvent first; Action and ProviderConnection belong to the separate Swiggy/write-tool release and need not block Trip Planner:

| Record | Essential state |
| --- | --- |
| AgentRun | Owner/conversation, status, active agent, saved SDK state, definition/SDK version, lease/version, client request ID, pending dispatch marker, cancellation flag, optional scheduled TaskRun link |
| Action | Run/owner, operation, immutable quote/payload/hash/version/expiry, decision, execution claim, provider IDs, outcome, receipt and sanitized audit details |
| ProviderConnection | User/provider, encrypted credentials, expiry, connection status, short-lived pending OAuth metadata |
| AgentRunEvent | Run ID, monotonic sequence, event type and sanitized payload; index for reconnect replay |

Use the existing Conversation record for completed SDK history and active-agent identity. Choose app-owned replay using `to_input_list()`; do not simultaneously add SQLite SDK sessions and response-ID chaining. Preserve complete tool call/result pairs, then bound history at completed-turn boundaries. Save resumable state for approvals and reconstruct trusted tool bindings on restore. Never deserialize executable pickle from clients. [SDK results and history](https://developers.openai.com/api/docs/guides/agents/results)

Use existing Messages/MessageArtifacts for display. Store each validated `trip_report` or `shopping_report` plus its bounded evidence/source/image registry in the artifact's JSON; no new reports table or file-generation service is needed. Add schema/report revision and generated/checked timestamps. Retain summaries in ordinary chat history instead of reinserting every image/result on every turn; reload the owned report when needed.

An artifact is currently keyed by `message_id`, so it holds only one artifact per message: give a report or action card its own message rather than overwriting another artifact. Every report fetch/update must verify conversation ownership. Persist a revised report as a new artifact/message with a reference to the prior report so reconnects cannot overwrite newer revisions.

Minimal endpoint contracts:

- `POST /api/agent-runs`: conversation, message, client request ID; returns a run ID.
- `GET /api/agent-runs/{id}`: authorized current snapshot.
- `GET /api/agent-runs/{id}/events?after={sequence}`: replay/live NDJSON.
- `POST /api/actions/{id}/decision`: approve/reject plus expected version, not a client-supplied executable payload.
- `POST /api/agent-runs/{id}/cancel`: stop future agent activity.
- `GET /api/messages/{message_id}/artifact`: owner-checked, versioned report payload; reused by the report screen.
- Swiggy connection start/status/disconnect plus the HTTPS OAuth callback.

Keep `/api/chat/stream` as a compatibility wrapper around the same service. Add `research_progress` and `report_ready` (artifact/message ID, kind and revision); emit report readiness only after validation and persistence. Preserve native events and separately add Swiggy's `action_required`, `payment_required`, and `receipt`; include run/action IDs and event sequence. Batch ordinary text deltas to avoid a database write per token. The SDK supports real streaming through `Runner.run_streamed`; the NDJSON adapter remains app-owned. [Running and streaming agents](https://developers.openai.com/api/docs/guides/agents/running-agents)

Use Inngest to drive execution independently of HTTP connections. Commit run/action state and a pending-dispatch marker before emitting events; use stable event IDs and reconcile unsent dispatches. Persist at approval/tool boundaries and make mutating tool execution consult the Action ledger before every attempt. After a crash, repeated model/read work must not duplicate external writes. Lease runs and serialize conversation updates. Do not hold SQL transactions across provider calls or while awaiting approval.

Stopping a run does not cancel an already-placed order. Expose those as distinct operations with separate confirmations. Delayed approvals expire; stale continuation events cannot reactivate cancelled runs.

## 8. Expo changes

Keep the current chat experience, but add real report rendering: the existing MessageBubble renders plain Text, so image Markdown alone will not produce the requested experience. Show a compact ReportCard in chat and a full ReportView with hero photo, flight/hotel or product cards, itinerary sections, budget and sources. Use a thin Expo Router screen at `C:/Users/sy710/Desktop/agents/personal/src/app/reports/[messageId].js`; keep rendering logic in components outside the routes directory.

Use the already-installed `expo-image` for remote URLs, stable layout dimensions, loading/error placeholders and accessible descriptions. Render only bounded, relevant photos; lazy-load long itinerary sections. Credits and external source links remain visible. Use a deterministic native layout rather than model-generated HTML or a new WebView report engine. [Expo 57 Image](https://docs.expo.dev/versions/v57.0.0/sdk/image/)

Trip/shopping reports have no Approve Purchase or Pay controls. Add a separate native ActionCard for Swiggy with review, approve/reject, payment-pending, confirmed, failed and unresolved states. Reconnect using persisted run/report/action IDs on foreground or network recovery; disable duplicate taps locally while enforcing uniqueness server-side.

Reuse the installed Expo WebBrowser capability for OAuth and provider-hosted checkout. Validate provider URLs against a maintained allowlist; never open a model-invented payment URL. Test the hosted UPI flow on physical Android and iOS devices, including missing payment apps and cancellation. Do not rely on a WebView to support every app-launch path. Follow SDK 57 documentation; no native folder edits or new navigation library are needed for this plan. [Expo 57 WebBrowser](https://docs.expo.dev/versions/v57.0.0/sdk/webbrowser/)

Persist completion in the existing in-app notification/history surfaces. Remote push notifications are a separate optional delivery feature, not something proven by merely having `expo-notifications` installed.

## 9. Build order and release gates

1. **Foundation:** Pin SDK/provider dependencies; add read-only routing and true streaming behind a feature flag. Preserve chat, Composio, schedule and phone-call regression tests. Migrate history and scheduled callers.
2. **Trip-report vertical slice:** Add the four read-only research tools, normalized evidence, structured synthesis, report artifacts, native rendering and reconnect. Start with fixtures, then validate production data-provider access, freshness and image-display terms. No transaction infrastructure is required for this release.
3. **Shopping reports:** Reuse web/image/evidence/report plumbing for product research, comparison and external retailer links. Test exact-variant matching and uncertain delivered prices. No carts or payments.
4. **Swiggy transaction boundary:** Add actions, OAuth connections, approvals, exact-quote checks, duplicate prevention and payment-specific UI. Pass restart/timeout tests with a fake provider before enabling real orders.
5. **Swiggy vertical slice:** Menu/cart/coupons, approved order, hosted UPI/Cash, status/receipt; then Dineout. Complete staging contracts and onboarding independently of research-report releases. Flight/hotel booking and shopping payment remain out of scope.

Start with one model configuration, bounded turn/tool/time budgets and small comparison/image shortlists. Parallelize independent research; serialize Swiggy cart changes and purchases. Cache public reference data according to provider terms, apply explicit freshness rules to recommendations and never substitute cached research for approval-time Swiggy validation. Keep kill switches by research provider and Swiggy action type.

### Tests required before recommendation reports ship

- Tool allowlists prevent travel/shopping bookings, cart writes and payments, including via handoffs or injected web content.
- Origin, dates, occupancy, passenger counts, budgets and hard constraints are reflected in the final recommendations.
- Flights/hotels/products, ratings, image IDs and source links resolve to retrieved evidence; arbitrary model URLs are rejected.
- Budget arithmetic handles per-person/group fares, room-nights, taxes and currency without double-counting alternatives.
- Arrival/departure windows, opening days and plausible travel/rest buffers are respected; unknowns remain visible.
- Wrong-place photos, broken/expired URLs, absent image permissions and missing attribution degrade safely to placeholders.
- Provider failures/empty results, model refusals, invalid schema and expired prices produce partial/needs-input states rather than fabricated complete reports.
- Report revision, ownership, app restart/reconnect and cancelling research behave correctly on Android, iOS and web.
- UI stays responsive with bounded images/sections; costs, latencies and evidence freshness are measured.

### Additional tests before Swiggy transactions ship

- Correct specialist and tool selection; no invented product IDs, totals or confirmations.
- Cross-user run/action/token access denied; OAuth state replay rejected.
- Prompt injection in menus/pages/tool results cannot approve, exfiltrate secrets or invoke an unrestricted executor.
- Double tap, duplicate event, worker crash and reconnect do not create a second purchase.
- Stale quotes, altered cart, expired slot, changed address and payment changes require renewed approval.
- Timeout after a provider accepted an order stays unresolved until reconciled; no blind retry.
- UPI pending/success/failure/refund, missing app, delayed success and background/resume work on real devices.
- Cancelled/expired actions remain blocked; cancelling a run is not reported as cancelling an order.
- Provider tool-schema changes fail closed; staging/live credentials and endpoints cannot be mixed.
- Model/browser/token/call budgets and sensitive-data redaction are exercised.

Use structural SDK tracing with sensitive content excluded, plus provider request IDs, report validation and action outcomes. Set retention/deletion rules for trip preferences, source data, Swiggy addresses, receipts and traces. Measure recommendation constraint adherence, citation coverage, broken-image rate, report latency/cost and, separately, confirmed-action success and duplicate/unknown outcomes. Built-in tracing is useful, but not a replacement for the transaction ledger. [SDK observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)

Run frontend lint and the project's configured type checks, backend unit/integration tests, and provider staging tests before enabling feature flags. The current frontend is JavaScript and lacks a `tsconfig.json`; `tsc --noEmit` alone is not currently a working project typecheck. Do not bundle a full TypeScript migration into this feature.

## 10. Definition of a successful first release

A user can request a trip and receive a saved visual report with sourced flight/hotel recommendations, a feasible day-by-day itinerary, real credited photos, a coherent budget and useful external links. Shopping produces the equivalent evidence-backed product comparison. Both support revisions and app reconnect without booking, carts or payment.

Separately, once Swiggy is enabled, a user can approve a food order or restaurant reservation and return to authoritative status without duplicate execution. Trip/shopping recommendations never initiate those actions automatically.

The lean scope is **one SDK runtime, three specialist configurations, reusable research/report tools, real image URLs, and Swiggy-only transaction infrastructure when that release is ready.**
