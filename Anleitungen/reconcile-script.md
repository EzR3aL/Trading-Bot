# Drift-Backfill: `reconcile_open_trades.py`

## Wofür ist das Script?

Mit der Zeit kann sich der Datenbank-Stand ("Was glaubt der Bot, ist auf der
Börse?") vom tatsächlichen Stand auf der Börse ("Was liegt wirklich für TP/SL/
Trailing-Order?") unterscheiden. Das nennen wir **Drift**.

Das Script `scripts/reconcile_open_trades.py` geht **alle offenen Trades**
einmal durch, fragt jede Börse nach dem echten TP/SL/Trailing-Stand
(`RiskStateManager.reconcile()`) und schreibt einen Markdown-Report in den
Ordner `reports/`.

Es macht **standardmäßig keine Änderungen** an der DB (Dry-Run). Erst mit
`--apply` werden Korrekturen geschrieben.

## Wann sollte ich es ausführen?

* Direkt nach einem Deploy mit Risk-State-Änderungen (Epic #188).
* Wenn du Verdacht hast, dass die DB einen veralteten TP/SL anzeigt
  (z. B. Bot zeigt im Frontend TP `--`, auf Bitget steht aber einer).
* Einmal pro Woche als Routine-Check.

## Schnellstart

```bash
# 1) Dry-Run — nur lesen, schreibt KEINEN UPDATE
docker exec bitget-trading-bot \
    python /app/scripts/reconcile_open_trades.py

# 2) Report ansehen
ls -lt reports/ | head
cat reports/reconcile-2026-04-18-1234.md
```

Im Report siehst du pro Trade:

* Welche Felder sich unterscheiden (z. B. `tp_order_id` ist NULL in DB,
  Börse hat aber `"1428..."`).
* Was die DB **nach** einem `--apply`-Lauf hätte.

## Korrigieren (`--apply`)

Wenn du nach dem Dry-Run-Report alles für richtig hältst:

```bash
docker exec -it bitget-trading-bot \
    python /app/scripts/reconcile_open_trades.py --apply
# → "WARNING: --apply will write drift corrections ..." → mit y bestätigen
```

Wenn du das Script in einem Cron / Skript ohne TTY laufen lässt:

```bash
docker exec bitget-trading-bot \
    python /app/scripts/reconcile_open_trades.py --apply --yes
```

## Filter

| Flag             | Bedeutung                                                    |
| ---------------- | ------------------------------------------------------------ |
| `--user-id 4`    | Nur Trades dieses Users.                                     |
| `--exchange bingx` | Nur Trades dieser Börse (`bitget`, `bingx`, `hyperliquid`, ...). |
| `--verbose`      | Zeigt im Report auch Trades **ohne** Drift.                  |
| `--output PATH`  | Eigener Report-Pfad statt `reports/reconcile-<ts>.md`.       |

Beispiel: nur den BingX-Stand für Admin-User reparieren:

```bash
python scripts/reconcile_open_trades.py \
    --user-id 1 --exchange bingx --apply --yes
```

## Was bedeutet "skipped"?

Manche Börsen (heute **Weex** und **Bitunix**) haben noch keine
"`get_position_tpsl`"-Implementierung. Für solche Trades steht im Report:

```
## Skipped
### Trade #42 (BTCUSDT long, user=1, weex demo)
- exchange not supported: ...
```

Das ist **kein Fehler** — nur ein Hinweis, dass diese Börse noch keinen
Probe-Endpoint anbietet. Du kannst die Trades manuell auf der Börse prüfen.

## Was bedeutet "Errors"?

Echte Fehler (`api down`, `permission denied`, ...) erscheinen unter:

```
## Errors
### Trade #42 (...)
- RuntimeError: api down
```

Diese sollten geprüft werden — meistens API-Keys abgelaufen oder
Netzwerk-Problem.

## Sicherheits-Hinweise

* Das Script fasst **nur Trades mit `status='open'`** an. Geschlossene
  oder abgebrochene Trades bleiben unangetastet.
* Idempotent: Du kannst es zweimal hintereinander laufen lassen — beim
  zweiten Mal sollte kein Drift mehr gefunden werden (außer
  `last_synced_at`).
* `--apply` braucht **immer** entweder eine `y`-Bestätigung oder das
  Flag `--yes`.

## Beispiel-Report

```markdown
# Reconcile Report — 2026-04-18 12:34 UTC

## Summary
- Trades geprüft: 5
- Mit Drift: 2
- Korrigiert (--apply): 0 (dry-run)
- Übersprungen: 1
- Fehler: 0

## Drift-Trades

### Trade #207 (BTCUSDT long, user=1, bitget demo)
| Feld | DB vorher | Exchange | DB nachher (--apply) |
|---|---|---|---|
| tp_order_id | NULL | "1428..." | (dry-run) |
| risk_source | "unknown" | "native_exchange" | (dry-run) |

### Trade #210 (ETHUSDT short, user=2, bingx live)
| Feld | DB vorher | Exchange | DB nachher (--apply) |
|---|---|---|---|
| trailing_order_id | "old123" | NULL | (dry-run) |

## Skipped
### Trade #42 (BTCUSDT long, user=1, weex demo)
- exchange not supported: weex has no probe yet
```
