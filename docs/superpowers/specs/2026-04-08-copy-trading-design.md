# Copy-Trading Strategy — Design

**Date:** 2026-04-08
**Status:** Approved (brainstorming complete, awaiting plan)
**Scope:** v1 — Hyperliquid wallet tracking, single-source-per-bot, polling-based

## Goal

Allow a user to track a public Hyperliquid wallet and automatically open
copies of that wallet's trades on the user's exchange of choice. The user
defines a fixed USDT budget and slot count; each copied trade gets `budget /
max_slots`. By default trades are mirrored 1:1; the user may override leverage,
filter symbols, and cap risk.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Source universe | Hyperliquid only |
| Sizing default | Fixed slots — `budget / max_slots` per trade |
| Overrides | budget, max_slots, target_exchange, leverage (validated against exchange max for symbol), symbol whitelist/blacklist, min_position_size_usdt, copy_tp_sl |
| Detection | Polling via existing bot worker schedule |
| Copied events | Entry + Full-Close only (no adds, no partials, no TP/SL adjustments mid-trade) |
| Cold start | Skip all positions open at bot start; only follow new fills |
| Architecture | One copy bot = one source wallet, implemented as new strategy plugin |

Explicitly excluded from v1: side filter, artificial entry delay,
non-Hyperliquid sources, multi-wallet bots, snapshot-on-start, partial
fill mirroring.

## Architecture

### New strategy: `CopyTradingStrategy`

Location: `src/strategy/copy_trading.py`
Registered in `src/strategy/__init__.py` (or wherever the strategy registry
lives) alongside `EdgeIndicatorStrategy` and `LiquidationHunterStrategy`.

Implements the same interface as the other two strategies:

- `generate_signal(symbol, ...)` — returns a `TradeSignal` if a new entry
  fill on the source wallet is detected since the last tick.
- `should_exit(trade, ...)` — returns `(True, reason)` if the source wallet
  no longer holds an open position for this symbol/side.

The strategy is **symbol-agnostic in user terms**: the user doesn't pick a
symbol when creating the bot — the bot watches the source wallet for *any*
symbol the source touches. The bot worker's per-symbol scheduling is reused
by treating the source wallet's position list as the authoritative symbol
set on each tick.

### New helper: `HyperliquidWalletTracker`

Location: `src/exchanges/hyperliquid/wallet_tracker.py`

A thin read-only wrapper around the public Hyperliquid Info API. Does **not**
need API keys — uses only public endpoints:

- `info.user_state(wallet_address)` → current open positions, equity
- `info.user_fills_by_time(wallet_address, start_time_ms)` → recent fills

Methods:

```python
class HyperliquidWalletTracker:
    async def get_open_positions(wallet: str) -> list[SourcePosition]
    async def get_fills_since(wallet: str, since_ms: int) -> list[SourceFill]
    async def close()
```

`SourcePosition` and `SourceFill` are dataclasses normalised to fields
relevant for copy logic (coin, side, size, entry_price, leverage, fill_time).

### Data flow per tick

1. Bot worker tick fires (`schedule_interval_minutes`, default `1`).
2. Strategy reads `last_processed_fill_ts` from `bot_config.strategy_state`
   (new JSON column or piggy-back on `strategy_params`).
3. `tracker.get_fills_since(source_wallet, last_processed_fill_ts)` →
   list of new fills.
4. For each fill:
   - Skip if not an entry (i.e., it's a close/reduce of an existing position).
     A fill is an entry if there was no prior open position for that
     coin/side, or if size moved away from zero.
   - Skip if symbol is not in whitelist (when set) or in blacklist.
   - Map `coin` → target-exchange symbol via `map_hl_to_target()`.
     If no mapping → log + send notification, skip.
   - Compute notional from `budget / max_slots`. If currently open trade
     count on this bot already equals `max_slots` → skip + log
     ("slot exhausted").
   - Compute size in target-exchange units from notional and current price.
     If size < `min_position_size_usdt` → skip.
   - Determine effective leverage: `min(source_leverage_or_user_override,
     max_leverage_cap)`.
   - Emit `TradeSignal` with side, size, leverage, source-fill metadata
     in `reason`.
5. After processing all fills, advance `last_processed_fill_ts` to the
   newest fill timestamp seen (atomic with bot_config update).
6. For exit checks: on each tick, call `tracker.get_open_positions(source)`
   and compute the symbol/side set. For each open trade in this bot:
   if `(symbol, side)` is not in the source's open set → return
   `should_exit=True` with reason `"COPY_SOURCE_CLOSED"`.

### State persistence

Add `last_processed_fill_ts` (bigint, UTC ms) to `BotConfig.strategy_state`
JSON column. If the column doesn't exist yet, create it via Alembic.
On bot start, initialize to `now_ms` (this implements the cold-start
"skip existing" rule automatically).

### Symbol mapping

New helper: `src/exchanges/symbol_map.py::map_hl_to_target(coin, target_exchange) -> str | None`

Examples:
- `("BTC", "bitget")` → `"BTCUSDT"`
- `("BTC", "bingx")` → `"BTC-USDT"`
- `("HYPE", "bitget")` → `None` (not listed) → triggers skip + notification
- `("BTC", "hyperliquid")` → `"BTC"` (no mapping, same wallet on same DEX
  is a degenerate but legal case)

The function uses a small lookup table for common quote-currency conventions
per exchange and falls back to a `symbol_fetcher.search()` call for the
target exchange to verify availability.

### Strategy parameter schema

```python
PARAM_SCHEMA = {
  "source_wallet":         {"type": "string", "required": True,
                            "label": "Hyperliquid Wallet (0x…)"},
  "budget_usdt":           {"type": "float",  "required": True,  "min": 50},
  "max_slots":             {"type": "int",    "default": 5,      "min": 1, "max": 20,
                            "label": "Parallele Positionen / Concurrent Positions"},
  "leverage":              {"type": "int",    "default": None,   "min": 1,
                            "label": "Hebel (leer = Hebel der Source übernehmen)",
                            "description": "Wird gegen das Maximum der Ziel-Exchange für das jeweilige Symbol validiert"},
  "symbol_whitelist":      {"type": "string", "default": "",     "description": "comma-separated"},
  "symbol_blacklist":      {"type": "string", "default": "",     "description": "comma-separated"},
  "min_position_size_usdt":{"type": "float",  "default": 10},
  "copy_tp_sl":            {"type": "bool",   "default": False},
}
```

**Leverage-Logik im Detail:**
- Wenn `leverage` **leer** ist → Bot übernimmt den Hebel den die Source für jeden
  einzelnen Trade nutzt (kann pro Trade variieren).
- Wenn `leverage` **gesetzt** ist → wird für **alle** kopierten Trades verwendet.
- Bei jedem Fill wird der effektive Hebel gegen
  `target_exchange.get_max_leverage(symbol)` validiert. Liegt er darüber:
  Trade auf das Maximum cappen + präzise Notification
  (`"Source nutzte 50x auf BTCUSDT, Bitget erlaubt nur 25x — Trade mit 25x kopiert"`).
- Frontend zeigt das Symbol-Maximum live an, sobald die Ziel-Exchange gewählt
  ist (per Endpoint `GET /api/exchanges/{exchange}/leverage-limits` — neuer
  Endpoint, einfacher Wrapper um die jeweiligen Exchange-Client-Methoden).

The user picks `target_exchange` via the existing exchange picker on the
bot creation form (no new field).

### Risk integration

The copy strategy should declare itself as **incompatible with the existing
per-symbol bot uniqueness check**: a normal Edge Indicator bot on
`BTCUSDT` and a copy bot that may also touch `BTCUSDT` should be allowed
to coexist on the same user account, *but never on the same exchange
account in the same direction* (would mess with exchange position state).
Reuse the existing `_check_symbol_conflicts` helper but with a new flag
`is_copy_bot=True` that relaxes the exclusivity rule by `(bot_config_id)`.
Trades from copy bots are tagged with `bot_config_id` like all other
trades, so PnL/Stats reporting works without changes.

### Wallet validation on bot creation

Before saving the bot config, the backend validates the source wallet via a
new endpoint `POST /api/copy-trading/validate-source` (input: `wallet`,
`target_exchange`). The endpoint runs:

1. **Address format check** — must match `^0x[a-fA-F0-9]{40}$`. Error:
   `"Ungültige Wallet-Adresse — erwartet wird 0x gefolgt von 40 Hex-Zeichen."`
2. **Existence check** — calls `info.user_state(wallet)`. If the response is
   empty / 404 → `"Wallet nicht auf Hyperliquid gefunden."`
3. **Activity check** — calls `info.user_fills_by_time(wallet, now - 30d)`.
   If empty → `"Wallet hat in den letzten 30 Tagen keine Trading-Aktivität.
   Copy-Trading benötigt eine aktive Source-Wallet."`
4. **Symbol availability preview** — extracts the unique coin set from the
   recent fills, calls `target_exchange.is_symbol_listed(coin_to_target_symbol(c))`
   for each. Returns:
   ```json
   {
     "valid": true,
     "wallet_label": "0x1234…abcd",
     "trades_30d": 47,
     "available": ["BTC", "ETH", "SOL"],
     "unavailable": ["HYPE", "PURR"],
     "warning": "2 von 5 zuletzt gehandelten Symbolen sind nicht auf Bitget verfügbar und werden übersprungen."
   }
   ```

The frontend shows this preview *before* the user clicks "Bot erstellen".
If `unavailable` is non-empty, a yellow warning banner is shown but the
user can still proceed (some Source-Wallets specialize in alts that don't
exist on every CEX, that's expected).

If the wallet is valid but the `available` list is **empty**, the form
blocks creation: `"Keines der zuletzt von dieser Wallet gehandelten Symbole
ist auf {target_exchange} verfügbar — Bot würde nichts kopieren können."`

### Asset availability at runtime

The same `is_symbol_listed` check runs again at runtime in the
fill-processing loop (because new symbols may appear after bot creation).
If a new fill targets an unlisted symbol:

1. Skip the fill — don't even attempt the order.
2. Send a precise notification through Discord/Telegram/UI-toast:
   `"Source eröffnete HYPE Long auf Hyperliquid — nicht auf Bitget verfügbar,
   Trade übersprungen."`
3. Cache the negative result for 24h per `(target_exchange, coin)` to avoid
   spamming notifications if the source repeatedly opens that coin.

### Failure modes & handling

| Failure | Behaviour |
|---|---|
| Source wallet has no fills since last poll | No-op, no log |
| HL API timeout / 5xx | Log warning, skip tick (next tick retries) |
| Symbol not on target exchange | Skip fill, send precise Discord/Telegram/UI notification, negative result cached 24h per (exchange, coin) to avoid spam |
| Source uses leverage above target-exchange max | Cap to exchange max, send notification ("Source 50x → Bitget max 25x → kopiert mit 25x") |
| Slot exhausted | Skip fill, log info |
| Target exchange order rejection | Existing `trade_executor` error path (notify user, mark trade attempt failed) |
| Source closes a position our bot never copied | Exit check sees no matching open trade → no-op |
| Bot stopped while source is open | On restart, bot does NOT close existing copies (treats them as normal open trades managed by `should_exit`) |

## Frontend

### Strategy descriptions (Anleitung)

Three strategies' descriptions (`bots.builder.strategyDesc_*`) get expanded
from 1 sentence to 5–7 sentences each. The new copy_trading strategy gets
a parallel description.

### Strategy registration

`frontend/src/constants/strategies.ts` → add `copy_trading: 'Copy Trading'`
to `STRATEGY_DISPLAY`.

### Bot builder

Existing `BotBuilderStepStrategy` already iterates over the strategies list
returned by the backend (`/api/strategies`). When the backend exposes
`copy_trading` in that list with its `param_schema`, the existing builder
will render the input fields via the generic param renderer **with two
exceptions** that need special handling:

1. **`source_wallet`** is a string param — the existing builder only
   handles select/textarea always-visible types. Add a `text` type to the
   always-visible row above `select`.
2. **`symbol_whitelist`/`symbol_blacklist`** are also strings — same fix.

These changes keep the builder generic; no copy-trading-specific code paths.

### Bot card (Bots page)

The existing card shows strategy name + risk profile. For copy bots,
the risk-profile slot is replaced by a truncated source wallet
(`0x1234…abcd`). Two-line description: `Source: 0x1234…abcd · Slots: 3/5
· Budget: $500`.

## Backend API surface

Two new endpoints, both small wrappers; no changes to existing routes.

**New:**
- `POST /api/copy-trading/validate-source` — validates a source wallet and
  returns the symbol-availability preview (see "Wallet validation" section).
- `GET /api/exchanges/{exchange}/leverage-limits?symbol=BTCUSDT` — returns
  the per-symbol max leverage allowed on the given exchange. Used by the
  frontend to show live leverage limits in the bot builder.

**Reused (no changes):**
- `POST /api/bots` — creates a copy bot when `strategy_type=copy_trading`.
- `GET /api/strategies` — needs to expose `copy_trading` in the list.
- `POST /api/bots/{id}/start` / `stop` — works via existing lifecycle.
- `GET /api/trades` — copy-bot trades show up automatically with
  `bot_config_id` set.

## Testing

- **Unit tests** for `HyperliquidWalletTracker` against the real public HL
  API (no auth needed; can hit testnet for repeatability).
- **Unit tests** for `CopyTradingStrategy.generate_signal()`:
  - new entry detected → signal emitted
  - same fill seen twice → second tick is no-op
  - whitelisted symbol → signal
  - blacklisted symbol → skipped
  - unknown symbol on target exchange → skipped + notification mock called
  - slot exhausted → skipped
- **Unit tests** for `should_exit`: source closes → exit signal; source
  still open → no exit.
- **Unit test** for cold start: tracker has 3 open positions, bot starts,
  next tick should NOT generate any entry signals.
- **Integration test** end-to-end against testnet HL wallet that the test
  itself opens/closes positions on.

## Out of scope (deferred)

- Multi-wallet copy bots (one bot, multiple sources)
- Add / partial-close mirroring
- TP/SL mirroring beyond the simple `copy_tp_sl` toggle
- WebSocket-based detection
- Snapshot-on-start
- Sources other than Hyperliquid
- Anti-front-run delays
- Public-facing wallet leaderboards / discovery UI

These can be added in v2 without breaking v1's user-facing API.

## Open questions

None — all design decisions resolved during brainstorming.
