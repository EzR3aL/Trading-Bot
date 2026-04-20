# Risk-State Anti-Patterns

Developer reference for the seven recurring failure modes that produced
the Phase-1 retroactive fixes in #218/#219/#220/#221/#222/#223/#224/#225.
Before merging changes to `src/bot/risk_state_manager.py`,
`src/bot/position_monitor.py`, `src/bot/bot_worker.py`, or any
`src/exchanges/*/client.py`, grep for these patterns and reject any
match.

The authoritative source is `~/.claude/projects/C--Users-edgar/memory/
feedback_risk_state_patterns.md`. This file is the human-readable
mirror kept in-tree so contributors without the memory see it during
review.

---

## Pattern A — Probe-but-don't-write

**What it looks like.** A `has_native_trailing_stop()`,
`get_position_tpsl()`, `get_trailing_stop()` or similar probe is called,
the result is assigned to a local variable, and the variable is never
written back to the DB.

**Why it fails.** The DB keeps the old (wrong) flag. Downstream code
relies on the DB, not on the probe, so the probe is effectively dead
code.

**Rule.** Every probe result must either drive a DB write or live
inside an assertion/test. No third option.

---

## Pattern B — Heuristic exit-reason classifier

**What it looks like.** Code looks at `trade.native_trailing_stop` +
0.2 % price-distance to TP/SL to guess what triggered the close,
instead of querying the exchange's order or plan history.

**Why it fails.** Slippage > 0.2 % misses the match, and the close gets
classified as `EXTERNAL_CLOSE_UNKNOWN`. Happened to trade #286 in
April 2026.

**Rule.** The exchange is authoritative. Heuristic fallback is allowed
**only** when the exchange probe genuinely fails
(`NotImplementedError` or `ExchangeError`), never as a shortcut.

---

## Pattern C — Cancel errors at DEBUG

**What it looks like.**
```python
try:
    await client.cancel_native_trailing_stop(...)
except Exception as e:
    logger.debug(f"Cancel failed: {e}")
```

**Why it fails.** A failed cancel means the OLD plan is still alive on
the exchange. The NEW plan you're about to place will conflict
(`Insufficient position`, `trigger price < market`), and the
operator has no signal because the error was buried.

**Rule.** Cancel-failure = WARN minimum. Classify benign
("no matching plan") vs. real (HTTP 5xx, auth, network) and only DEBUG
the benign ones. Pattern-C site fixes in `bitget/client.py` and
`weex/client.py` (see `_log_bitget_cancel_outcome`).

---

## Pattern D — Identical i18n labels for distinct codes

**What it looks like.** `de.json` has two different `ExitReason` codes
that both render as "Manuell geschlossen".

**Why it fails.** Destroys the entire point of distinct exit reasons.
User sees the same label for a native-SL-trigger and a manual close,
can't tell them apart.

**Rule.** Every `ExitReason` enum value must have a unique,
non-overlapping translation in every language file. Unit test asserts
uniqueness. Legacy aliases (`TRAILING_STOP`, `MANUAL_CLOSE`) are
allowed but must carry a distinct suffix such as "(Legacy)".

---

## Pattern E — Module written but never wired

**What it looks like.** A service singleton (e.g. `RiskStateManager`)
exists, has a factory (`get_*_manager()`), is used in one caller (e.g.
API dependency), but no other consumer retains a reference. The hot
code path (`BotWorker`, `PositionMonitor`) sets the attribute to
`None` and nothing overwrites it.

**Why it fails.** All work behind the singleton is dead code in the
silent path. Happened to Epic #188: every bot-detected close fell
through to the legacy heuristic for two weeks.

**Rule.** When introducing a new long-lived service singleton, grep
for every code path that will use it and confirm each one holds a
reference before merging. Wiring tests must assert the attribute is
set to the **singleton**, not merely non-null.

---

## Pattern F — Exchange query requirements encoded as constants, never verified

**What it looks like.** An exchange adapter has a `_fetch_X` helper
with query parameters that were written from memory or docs. The code
was never run against a live demo account to verify the exact field
names and required params.

**Examples.**
- Bitget `orders-plan-history` requires `planType`; the call omitted
  it → every response was "Parameter verification failed". Unseen for
  two weeks.
- Bitget `planStatus` field returns `executed` on fired plans; the
  filter checked `triggered` → zero matches even on successful
  responses.
- Bitget `endTime` is advisory on `orders-plan-history`; the response
  includes rows with later `uTime` values → client-side filter
  required for backfill correctness.

**Rule.** For every exchange readback method, run a live demo probe
and inspect the actual response before relying on the implementation.
Compare observed fields (`planStatus`, `orderSource`, spellings of
`moving_plan` vs `track_plan`) against what the code filters on. Add
an integration test that hits a demo account at least once per
adapter.

---

## Pattern G — Prefix/key mapping without matching ExitReason

**What it looks like.** An exchange adapter has a table that maps
string prefixes to plan-type keys. A corresponding `_PLAN_TYPE_TO_REASON`
dict maps keys to ExitReason values. The two are updated
independently, so a prefix emits a key that has no ExitReason.

**Example.** Bitget's `_BITGET_ORDER_SOURCE_PREFIXES` originally
included `("normal_plan", "normal_plan")`, but `normal_plan` is not a
key in `_PLAN_TYPE_TO_REASON` → any close tagged `normal_plan_*`
silently fell through to `EXTERNAL_CLOSE_UNKNOWN`.

**Rule.** Every entry in an exchange's prefix/key table must have a
paired entry in `_PLAN_TYPE_TO_REASON`. Adding only one side is
Pattern G. Cross-check during PR review. A table of expected mappings
lives in `src/bot/risk_state_manager.py` alongside
`_PLAN_TYPE_TO_REASON`.

---

## Review checklist

When reviewing a PR that touches risk-state code, confirm each point:

- [ ] Pattern A: every probe result drives a DB write or an assertion
- [ ] Pattern B: no heuristic classifier that skips the exchange probe
- [ ] Pattern C: cancel failures logged at WARN (DEBUG only for
      classified benign errors)
- [ ] Pattern D: every `ExitReason` has a unique translation in all
      language files
- [ ] Pattern E: every service singleton has every intended consumer
      wired + tested
- [ ] Pattern F: exchange query params verified against a live demo
      response, integration test exists
- [ ] Pattern G: prefix-table keys are a subset of
      `_PLAN_TYPE_TO_REASON` keys

---

## References

- Phase-1 retroactive fix PRs: #219, #222, #223
- Follow-up sweep PRs: #227 (BingX/HL), #228 (Pattern C/F)
- Roadmap: #216
- Original Epic: #188
