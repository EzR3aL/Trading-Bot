-- Korrigiert den AVAXUSDT Short Demo-Trade vom 2026-04-08 09:51 (Bitget),
-- der durch den ticker.last_price-Bug einen falschen Exit-Preis und PnL bekam.
--
-- Echte Bitget-Werte (aus dem Share-Card Screenshot des Users):
--   Entry price : 8.578
--   Close price : 8.587
--   PnL         : -9.8973 USDT (-0.10%)
--
-- Vorher zeigte das Frontend faelschlich:
--   Exit 9.465, PnL -975.44 USD (-10.34%)
--
-- Vor Ausfuehrung verifizieren:
--   SELECT id, symbol, side, entry_price, exit_price, pnl, pnl_percent, status, exit_time
--   FROM trade_records
--   WHERE symbol = 'AVAXUSDT'
--     AND side = 'short'
--     AND status = 'closed'
--     AND entry_price BETWEEN 8.577 AND 8.579
--     AND exit_time >= '2026-04-08 07:00:00'
--     AND exit_time <  '2026-04-08 09:00:00';

BEGIN;

UPDATE trade_records
SET
    exit_price  = 8.587,
    pnl         = -9.8973,
    pnl_percent = -0.10
WHERE symbol = 'AVAXUSDT'
  AND side = 'short'
  AND status = 'closed'
  AND entry_price BETWEEN 8.577 AND 8.579
  AND exit_time >= '2026-04-08 07:00:00'
  AND exit_time <  '2026-04-08 09:00:00';

-- Sicherheitscheck: nur eine Zeile darf betroffen sein.
-- Wenn mehr als 1 Row geaendert wurde -> ROLLBACK statt COMMIT.
-- Pruefe das Ergebnis (Postgres meldet UPDATE 1) und committe dann manuell:
--   COMMIT;
-- bzw. bei Mehrtreffer:
--   ROLLBACK;
