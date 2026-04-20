# Exchange WebSocket Listeners (#216 Section 2.1)

Phase-2 push-mode replacement for the RSM reconcile polling loop. Lets
Bitget and Hyperliquid push trade-state changes to us instead of having
the bot poll every ~30 s.

**Status:** infrastructure + mock-tested unit coverage only. Live WS
verification against Bitget demo / HL testnet still needs a provisioned
demo account (see `tests/integration/live/test_ws_live.py`). Feature is
default-**off** until that validation is done.

## Quick facts

| Item               | Value                                                           |
|--------------------|-----------------------------------------------------------------|
| Feature flag       | `EXCHANGE_WEBSOCKETS_ENABLED` (env, default `false`)            |
| Supported exchanges| Bitget (`orders-algo`), Hyperliquid (`orderUpdates`)            |
| Reconnect strategy | Exponential backoff `1s, 2s, 4s, 8s, 30s cap`                   |
| Process model      | One process-wide `WebSocketManager`, one client per `(user, exchange)` |
| Health surface     | `GET /api/health` → `ws_connections: {bitget, hyperliquid}`     |

## Connect flow

```
┌──────────────┐      start_for_user        ┌──────────────────────┐
│  bot_worker  │ ─────────────────────────▶ │  WebSocketManager    │
└──────────────┘                            └─────────┬────────────┘
                                                      │ credentials_provider
                                                      ▼
                                            ┌──────────────────────┐
                                            │ ExchangeWebSocketCli │
                                            │ ent (subclass)       │
                                            └─────────┬────────────┘
                                                      │ run_forever
                                                      ▼
                                       ┌──────────────────────────────┐
                                       │ _connect_transport           │
                                       │   Bitget: websockets.connect │
                                       │       + HMAC login frame     │
                                       │   HL:     hyperliquid.Info   │
                                       │       (skip_ws=False)        │
                                       └─────────┬────────────────────┘
                                                 │ _subscribe
                                                 ▼
                                       ┌────────────────────────┐
                                       │ _read_once loop        │
                                       │ → _parse_message       │
                                       │ → on_event → RSM       │
                                       └────────────────────────┘
```

`WebSocketManager.start_for_user` reuses an existing connected client;
credentials come from a caller-supplied `credentials_provider` so the
encrypted-key resolver stays decoupled from this module.

## Reconnect strategy

The base class (`src/exchanges/websockets/base.py`) walks the backoff
schedule `1s, 2s, 4s, 8s, 30s-cap-forever` on every failed connect or
transport drop. Key properties:

* **Never give up.** A live trading session must not silently lose its
  push feed. The cap repeats instead of escalating to an error.
* **No replay of missed events.** On a successful reconnect the base
  class fires `on_reconnect(user_id, exchange)` exactly once. The
  `WebSocketManager` responds by running `RiskStateManager.reconcile`
  on every open trade of that `(user, exchange)` — reconcile is
  idempotent and the exchange is the source of truth, so a full
  re-probe is both correct and simpler than buffering.
* **Parse errors are isolated.** One bad frame increments a warn log
  and is dropped; the reconnect ladder is reserved for actual transport
  faults.

## Event → RSM pipeline

Each client's `_parse_message` produces a canonical shape:

```python
{
    "event_type": "plan_triggered" | "order_filled" | "position_closed",
    "payload": {"symbol": "BTCUSDT", "raw": <exchange_payload>},
}
```

`RiskStateManager.on_exchange_event(user_id, exchange, event_type, payload)`:

1. Drops events whose `event_type` isn't in the recognized set (log at
   INFO, no-op).
2. Looks up every open trade for `(user_id, exchange, symbol)` in the
   DB.
3. Calls `reconcile(trade_id)` on each one. `reconcile` does the
   Phase-C readback and heals DB drift — no exchange mutation.

If no open trade matches, we log and return. A WS event that doesn't
correspond to one of the bot's trades is an expected case (e.g. a user
placed an order manually in the Bitget app) and never an error.

## Bitget specifics

* **Channel:** `orders-algo` on `wss://ws.bitget.com/v2/ws/private`,
  `instId="default"` for USDT-M futures (captures every symbol).
* **Auth:** HMAC-SHA256 over `{ts}GET/user/verify`, base64 encoded —
  same primitive as the REST client's `_generate_signature`.
* **Event classification** (`_classify_bitget_event`):
  * `status ∈ {executing, live}` → `plan_triggered`
  * `status == filled`           → `order_filled`
  * `state == closed`            → `position_closed`

Demo mode uses the same WS URL (REST uses a header, not a URL switch).

## Hyperliquid specifics

* Uses the `hyperliquid-python-sdk` `Info.subscribe` call with
  `{"type": "orderUpdates", "user": <wallet_address>}`.
* The SDK's callback is **synchronous** and fires from its own socket
  thread — the client marshals messages onto an `asyncio.Queue` via
  `loop.call_soon_threadsafe` so the base-class loop stays async.
* Only `isTrigger=true` items are emitted — TP/SL/trailing on HL are
  all trigger orders; plain limit fills are tracked elsewhere.
* Status mapping: `triggered` → `plan_triggered`, `filled` →
  `order_filled`. Cancels/rejects are dropped.

## Known limitations (pre-prod)

1. **Not yet live-verified.** The unit tests cover parse + reconnect +
   dispatch logic against mocked transports. We have NOT yet confirmed
   that Bitget's real `orders-algo` payloads match the
   `_classify_bitget_event` assumptions. Plan: enable demo creds, run
   `tests/integration/live/test_ws_live.py`, then adjust the classifier
   if needed.
2. **No subscription-level metrics.** Drop counts, latency histograms
   and per-event-type counters are TODO. The `/api/health` gauge shows
   connected-count only.
3. **One subscription per user per exchange.** `orders-algo` uses
   `instId="default"` which covers every contract, so fan-out by
   symbol is not needed. HL subscribes to the whole wallet. If we ever
   add per-subaccount scoping, the key `(user_id, exchange)` has to
   grow a third component.
4. **No message buffering during reconnect.** Deliberate — see
   "Reconnect strategy" above. If the exchange ever drops a TP-fill
   during a 30-second outage, the post-reconnect sweep catches it via
   `reconcile`. Timestamped history would only help if an exchange
   implements message-id resumption, which neither of these does.
5. **Process-wide singleton.** A single `WebSocketManager` lives on
   `app.state.exchange_ws_manager`. In a multi-replica deployment each
   replica opens its own WS; duplicate events are harmless because
   `reconcile` is idempotent, but the `ws_connections` health counter
   is per-replica rather than cluster-wide.

## Wiring the manager into the app

Not done in this PR — the manager is a library today. Follow-up task:

```python
# in src/api/main_app.py lifespan()
from src.bot.ws_manager import WebSocketManager, is_enabled

if is_enabled():
    exchange_ws_manager = WebSocketManager(
        risk_state_manager=get_risk_state_manager(),
        credentials_provider=credentials_provider,
        session_factory=get_session,
    )
    app.state.exchange_ws_manager = exchange_ws_manager
    # Start per active user on bot start, stop in shutdown via stop_all.
```

`/api/health` already reads `app.state.exchange_ws_manager` defensively
— if the wiring lands later, the endpoint starts reporting real counts
with no further change.

## Files

| Path                                              | Purpose                               |
|---------------------------------------------------|---------------------------------------|
| `src/exchanges/websockets/base.py`                | Abstract client + reconnect + dispatch|
| `src/exchanges/websockets/bitget_ws.py`           | Bitget `orders-algo` subclass         |
| `src/exchanges/websockets/hyperliquid_ws.py`      | HL `orderUpdates` subclass            |
| `src/bot/ws_manager.py`                           | Process-wide manager + health counts  |
| `src/bot/risk_state_manager.py`                   | `on_exchange_event` dispatch          |
| `src/api/routers/status.py`                       | `/api/health` `ws_connections` field  |
| `tests/unit/exchanges/test_ws_base.py`            | Base-class backoff + health tests     |
| `tests/unit/bot/test_ws_manager.py`               | Manager reconnect + stop_all tests    |
| `tests/unit/bot/test_risk_state_manager.py`       | `on_exchange_event` tests (2 added)   |
| `tests/integration/live/test_ws_live.py`          | Live WS stubs (skipped)               |
