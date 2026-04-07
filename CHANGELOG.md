# Changelog

Alle wichtigen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

> **Hinweis:** Dieser Changelog wird automatisch bei jeder Änderung aktualisiert.

---

## [4.15.5] - 2026-04-07

### Behoben
- **Hyperliquid Builder-Fee-Bestätigung schlug immer fehl — User festgefahren in Signatur-Loop (#138)** — User eLPresidente (und jeder andere Demo-User) klickte "Transaktion bestätigen", signierte erfolgreich in seinem Wallet, und bekam dann immer wieder `Builder-Fee-Genehmigung nicht auf Hyperliquid gefunden. Bitte erneut signieren.` Zwei kombinierte Bugs:
  1. **`HyperliquidClient.check_builder_fee_approval` short-circuitete bei `self._builder is None`**: Der HL-Client liest die Builder-Config nur aus `os.environ`, aber auf der Prod-Instanz liegt sie in der `system_settings` DB-Tabelle (via `get_hl_config()`). Clients die über `create_hl_client()` / `create_hl_mainnet_read_client()` erstellt werden haben daher `self._builder = None`, und die Methode returnt `None` ohne die HL-API überhaupt zu fragen. Der Bot-Trading-Pfad ist nicht betroffen, weil `bot_worker.py:181-184` `builder_address` explizit als kwargs durchreicht.
  2. **`confirm_builder_approval` nutzte Testnet-Client für Demo-User**: Das Frontend signiert mit `hyperliquidChain: 'Mainnet'` und postet an die Mainnet-API `https://api.hyperliquid.xyz/exchange`. Der Backend-Check lief aber für Demo-only-User gegen Testnet — die Approval gab es dort natürlich nicht.
  
  Live-verifiziert: direkte HTTP-Abfrage gegen HL Mainnet für eLPresidente's Wallet `0x5A57D576...` mit dem Builder `0x67B10Bf6...` gibt `maxBuilderFee: 10` zurück. Die Signatur war die ganze Zeit korrekt gespeichert, unser Backend hat sie nur nicht korrekt abgefragt.
  
  Fix: `check_builder_fee_approval(user_address, builder_address)` akzeptiert jetzt den Builder explizit. `confirm_builder_approval` und `revenue_summary` nutzen `create_hl_mainnet_read_client` und übergeben den Builder-Address aus `get_hl_config()` explizit. Der `mode`-Query-Parameter auf `revenue_summary` wird für Rückwärtskompatibilität akzeptiert aber ignoriert (Builder-Fees und Referrals existieren nur auf Mainnet).

### Hinzugefügt
- 5 neue Tests (3 Unit + 2 Router) für die Builder-Fee-Confirmation-Pfade:
  - `test_check_approval_accepts_explicit_builder_address` — Regression für den self._builder=None Pfad
  - `test_check_approval_explicit_builder_overrides_self` — Explizites kwarg hat Vorrang
  - `test_approval_uses_mainnet_for_demo_user` — Mainnet-Zwang auch bei Demo-User
  - `test_approval_passes_explicit_builder_address` — Router-Seite übergibt Builder korrekt
  - `test_approval_requires_configured_builder_address` — Klarer Fehler wenn Builder nicht konfiguriert

---

## [4.15.4] - 2026-04-07

### Behoben
- **Hyperliquid Referral-Verifikation zeigte unbrauchbare Fehlermeldung (#135)** — User (z.B. eLPresidente) sahen beim Klick auf "Bereits registriert? Jetzt prüfen" nur `Referral nicht gefunden. Bitte registriere dich zuerst über https://app.hyperliquid.xyz/join/TRADINGDEPARTMENT`, ohne Hinweis WAS sie tatsächlich tun müssen. Ursache: Der Endpoint meldete einen generischen Fehler, ohne zu unterscheiden zwischen (a) Wallet hat noch kein Guthaben auf HL, (b) Wallet hat Guthaben aber keinen Referrer, (c) Wallet wurde über anderen Referrer registriert. Zusätzlich lief die Abfrage für Demo-User gegen Hyperliquid-Testnet, obwohl Referrals ein reines Mainnet-Konzept sind.

  Fix: `POST /api/config/hyperliquid/verify-referral` gibt jetzt bei Fehler eine strukturierte JSON-Detail-Response zurück mit:
  - `required_action`: `DEPOSIT_NEEDED` | `ENTER_CODE_MANUALLY` | `WRONG_REFERRER` | `VERIFIED`
  - `wallet_address` + `wallet_short`: welches Wallet geprüft wurde
  - `account_value_usd` + `cum_volume_usd`: aktueller HL-Kontostand und Handelsvolumen
  - `referred_by`: rohe Referrer-Info von HL
  - `min_deposit_usdc`: 5.0 (Hyperliquids Hard-Minimum)
  - `deposit_url`, `enter_code_url`: konkrete nächste-Schritte-Links
  
  Frontend `HyperliquidSetup.tsx` rendert jetzt pro Action-Typ einen passenden Anleitungs-Block mit nummerierten Schritten:
  - **DEPOSIT_NEEDED**: "Zahle mindestens 5 USDC via Arbitrum Bridge ein (weniger geht verloren!)"
  - **ENTER_CODE_MANUALLY**: "Öffne https://app.hyperliquid.xyz/referrals → Enter Code → TRADINGDEPARTMENT"
  - **WRONG_REFERRER**: Erklärt dass HL keine nachträgliche Referrer-Änderung zulässt
  
  Außerdem: `verify-referral` und `referral-status` forcieren jetzt Mainnet (neuer Helper `create_hl_mainnet_read_client` in `src/services/config_service.py`), weil HL-Referrals nur dort existieren. Der `mode`-Query-Parameter auf `referral-status` wird für Rückwärtskompatibilität akzeptiert aber ignoriert.

### Hinzugefügt
- `src/services/config_service.py::create_hl_mainnet_read_client()` — Mainnet-only HL-Client für read-only Queries (Referral, User-State).
- `src/exchanges/hyperliquid/client.py::HyperliquidClient.get_user_state()` — direkter `user_state`-Query für Balance-Diagnose.
- `src/errors.py`: drei neue Fehler-Konstanten mit Platzhaltern für wallet/account/code.
- `src/api/routers/config_hyperliquid.py`: Konstante `HL_MIN_DEPOSIT_USDC = 5.0` und Action-Enum-Konstanten.
- i18n-Keys in `frontend/src/i18n/{de,en}.json` für alle Diagnose-Texte (Step-by-Step-Anleitungen).
- 5 neue Tests in `tests/unit/api/test_config_router_extra.py` für alle Diagnose-Pfade: `test_referral_deposit_needed`, `test_referral_enter_code_needed`, `test_referral_wrong_referrer`, `test_referral_uses_mainnet_regardless_of_demo`, plus aktualisierter `test_referral_found`.

---

## [4.15.3] - 2026-04-07

### Behoben
- **Dashboard Trailing Stop zeigte falschen Status (#133)** — Die Dashboard-API (`/api/portfolio/positions`, `/api/trades`) berechnete den Trailing-Stop mit anderen Parametern als die Strategie selbst. Zwei unabhängige Bugs:
  1. `_compute_trailing_stop` in `src/api/routers/trades.py` merged nur `DEFAULTS + strategy_params` und **ignorierte `RISK_PROFILES`**. Für ein `conservative`-Bot (edge_indicator) wurden `trailing_breakeven_atr=2.0` und `trailing_trail_atr=3.0` nicht angewendet — stattdessen griffen die DEFAULTS (1.5, 2.5).
  2. Der Klines-Prefetch in `src/api/routers/portfolio.py` und `src/api/routers/trades.py` hardcodete `"1h"` statt das konfigurierte `kline_interval` der Strategie zu verwenden. Ein conservative-Bot mit `kline_interval="4h"` bekam für die ATR-Berechnung 1h-Klines.
  
  Konsequenz: Das Dashboard zeigte "Trailing aktiv ✓" samt ShieldCheck-Badge (z.B. $69,179.54 bei Trade #71), obwohl die Strategie den Trailing nie aktivierte. User verließen sich auf einen Schutz, den es gar nicht gab. **Der Bot selbst hat immer korrekt auf dem gewählten Intervall gehandelt** — Signalgenerierung, Exit-Checks und native Trailing-Stop-Platzierung nutzen `self._strategy._p` mit korrektem Profil-Merge. Nur die Dashboard-Anzeige war falsch.
  
  Fix: Neuer Helper `resolve_strategy_params()` in `src/strategy/base.py` spiegelt die Merge-Logik (`DEFAULTS → RISK_PROFILE → user_params`) der Strategie-`__init__`-Methoden. Dashboard und Strategie sehen jetzt garantiert dieselben Parameter. Unterstützt auch `liquidation_hunter` (vorher nur edge_indicator). Klines-Cache ist jetzt pro `(symbol, interval)` statt nur `symbol`.

- **BingX native Trailing Stop schlug immer fehl (Error 109400)** — `place_trailing_stop` sendete `price` zusammen mit `priceRate` im TRAILING_STOP_MARKET-Request. BingX interpretiert `price` als "USDT-Trail-Distance" (Alternative zu `priceRate`) und lehnt die Kombination mit Error 109400 "cannot provide both the Price and PriceRate fields" ab. Korrektes Feld ist `activationPrice` (laut [BingX-API Issue #28](https://github.com/BingX-API/BingX-swap-api-doc/issues/28)). User Ludwig (Bot 14) und alle BingX-Bots waren betroffen seit Feature-Release. Software-Backup hatte gegriffen, aber der native Trailing war komplett kaputt.

- **Trailing Stop: falsche Erfolgsmeldungen bei Weex/Bitunix/Hyperliquid** — `trade_executor` prüfte den Rückgabewert von `client.place_trailing_stop` nicht. Da die Basis-Klasse für nicht unterstützte Börsen `None` zurückgibt, wurde fälschlicherweise `trailing_placed=True` gesetzt und "Native trailing stop placed" geloggt — obwohl nichts platziert wurde. `trade.native_trailing_stop` in der DB zeigte diesen falschen Status an. Zusätzlich versuchte `position_monitor._try_place_native_trailing_stop` alle 10 Minuten vergeblich Klines zu holen und einen Trailing zu setzen. Fix: neues Class-Level Flag `ExchangeClient.SUPPORTS_NATIVE_TRAILING_STOP` (Bitget/BingX = True, Rest = False). Beide Pfade überspringen unnötige API-Calls, die nicht unterstützten Börsen verlassen sich vollständig auf Software-Trailing in `strategy.should_exit`.

### Hinzugefügt
- `src/strategy/base.py::resolve_strategy_params()` — zentrale Helfer-Funktion zum Auflösen von Strategie-Parametern außerhalb einer Strategie-Instanz (Dashboard, Background Jobs).
- `src/exchanges/base.py::SUPPORTS_NATIVE_TRAILING_STOP` — explizite Capability-Deklaration pro Exchange-Client.
- `tests/unit/test_resolve_strategy_params.py` — 23 Tests inkl. Parametrized Parity-Tests, die garantieren dass `resolve_strategy_params` dasselbe Ergebnis liefert wie `EdgeIndicatorStrategy._p` / `LiquidationHunterStrategy._p` für alle Risk Profiles.
- `tests/unit/exchanges/test_bingx_trailing_stop.py` — Regression-Tests, die verhindern dass `price` statt `activationPrice` wieder gesendet wird.
- `tests/unit/exchanges/test_native_trailing_capability.py` — 8 Tests, die die Support-Matrix pro Client absichern (Bitget ✓, BingX ✓, Weex/Bitunix/Hyperliquid ✗) passend zur Frontend-Feature-Matrix.

---

## [4.15.2] - 2026-04-05

### Behoben
- **Discord: Trade Entry Notifications wurden nicht gesendet** — `send_trade_entry()` crashte still wenn `take_profit` oder `stop_loss` `None` war (Strategie-Exit ohne TP/SL). Der Format-String `${None:,.2f}` warf einen TypeError, der im Notification-Dispatcher verschluckt wurde. TP/SL sind jetzt Optional und zeigen "—" wenn nicht gesetzt.
- **Telegram: Parameter-Mismatch bei Trade Entry & Exit** — `position_size` statt `size` verursachte TypeError bei jedem Trade-Notification-Versuch. Parameter-Name auf `size` vereinheitlicht.
- **WhatsApp: Parameter-Mismatch bei Trade Entry & Exit** — `direction` statt `side` verursachte TypeError. Parameter-Name auf `side` vereinheitlicht (konsistent mit allen anderen Notifiern).
- **Telegram/WhatsApp: Error-Notifications crashten** — `send_error()` akzeptierte kein `error_type`-Argument, das vom Bot-Worker gesendet wurde. Parameter `error_type` und `details` hinzugefügt.
- **WhatsApp: Daily Summary zeigte nur Nullwerte** — Parameter-Namen wichen ab (`gross_pnl`/`fees`/`funding` statt `total_pnl`/`total_fees`/`total_funding`). Signatur an Caller-Konvention angepasst.
- **Discord: Bot-Status zeigte keinen Bot-Namen** — `bot_name` wurde in `**kwargs` verschluckt. Wird jetzt im Titel angezeigt.

---

## [4.15.1] - 2026-04-03

### Behoben
- **Auth: Session-Verlust auf Mobile/PWA (#130)** — User wurden auf Android-PWA alle ~10 Min ausgeloggt. Drei Ursachen behoben:
  1. `/auth/me` war fälschlicherweise von der Token-Refresh-Logik ausgeschlossen — bei abgelaufenem Access-Token wurde kein Refresh versucht
  2. Token-Expiry war nur im Arbeitsspeicher — ging bei PWA-Kill/Background verloren. Jetzt in localStorage persistiert
  3. Race Condition: Wenn Visibility-Handler und Interceptor gleichzeitig refreshen wollten, konnte der Interceptor fälschlicherweise einen Fehlschlag melden. Jetzt teilen sich alle Caller dieselbe Refresh-Promise
- **Multi-Tab Logout-Sync** — Logout in einem Tab synchronisiert jetzt die Token-Expiry über alle offenen Tabs via `storage`-Event
- **localStorage-Fehlerbehandlung** — Private-Browsing-Modus oder voller Speicher crasht die App nicht mehr

---

## [4.15.0] - 2026-04-03

### Behoben
- **Bot Builder: 400-Fehler ohne Details** — Fehlermeldung zeigte nur "Request failed with status code 400" statt dem eigentlichen Grund. Ursache: Affiliate-Gate gab ein JSON-Object statt eines Strings als `detail` zurück, das Frontend konnte es nicht parsen. Jetzt werden alle Error-Details korrekt als String zurückgegeben und im Frontend angezeigt.
- **Frontend `getApiErrorMessage()`** — Unterstützt jetzt auch Object-Details mit `message`-Feld (zusätzlich zu String und Array).

### Verbessert
- **Sprechende Fehlermeldungen beim Bot-Start** — Jede Fehlermeldung erklärt jetzt den Grund und nennt die nötige Aktion:
  - CEX (Bitget, Weex, Bitunix, BingX): Affiliate-Link + UID-Hinweis mit Exchange-Name
  - Hyperliquid: Wallet-Verbindung, Referral-Link, Builder Fee — jeweils mit Navigation zu Einstellungen
- **Bot Builder: Validierung bei fehlender Exchange-Verbindung** — Step "Exchange & Assets" blockiert jetzt den Wizard wenn keine Exchange-Connection vorhanden ist. Auffällige Warnung (statt grauer Text) mit Handlungsanweisung.
- **Hyperliquid Setup immer sichtbar** — Referral-Link und Builder Fee Setup werden jetzt im Settings-Accordion sofort angezeigt, nicht erst nach dem Speichern der Wallet-Daten. Neue User sehen den Referral-Link direkt beim Öffnen der Hyperliquid-Sektion.

---

## [4.14.0] - 2026-04-02

### Hinzugefügt
- **Bot Builder: Mode-aware Symbol-Listen** — Symbol-Listen werden jetzt passend zum gewählten Modus (Demo/Live) geladen. Bitget Demo zeigt nur die ~22 handelbaren Symbole statt aller 544 Live-Symbole. BingX und Hyperliquid nutzen ebenfalls ihre Demo/Testnet-Endpunkte. Beim Mode-Wechsel werden ungültige Trading-Pairs automatisch entfernt. (#128)

---

## [4.13.1] - 2026-04-02

### Verbessert
- **Bot Builder: Demo-Button per Exchange** — Demo-Button wird ausgegraut mit Info-Tooltip wenn die Exchange kein Paper/Demo-Trading anbietet (Weex, Bitunix). Beim Exchange-Wechsel wird automatisch auf Live umgeschaltet falls Demo nicht verfügbar ist. (#126)
- **Bot Builder: Symbol-Konflikt in Übersicht verbessert** — Die Konflikt-Warnung auf der Review-Seite zeigt jetzt den betroffenen Bot-Namen, Modus und einen Hinweistext an (statt nur das Symbol). (#126)

---

## [4.13.0] - 2026-04-01

### Behoben
- **Login-Endlosschleife** — Login-Seite leitete in Dauerschleife auf sich selbst weiter (`fetchUser` 401 → Refresh-Versuch → Session Expiry → Redirect → Loop)
- **"Sitzung abgelaufen" statt "Ungültige Anmeldedaten"** — Login-401 wurde fälschlich als abgelaufene Session behandelt
- **User löschen + neu anlegen** — Gelöschter Username konnte nicht wiederverwendet werden (Soft Delete blockierte Unique Constraint). Jetzt: Hard Delete bei Neuanlage
- **DuckDNS-Domain** zu CORS hinzugefügt

### Hinzugefügt
- **Smart Deploy-Skript** (`scripts/deploy.sh`) — Erkennt ob Dependencies geändert wurden, nutzt Docker-Cache wenn möglich (~2 Min statt ~10 Min)

---

## [4.12.8] - 2026-04-01

### Geaendert
- **Dokumentation bereinigt** — Alle Referenzen auf entfernte Strategien (Contrarian Pulse, LLM Signal, Degen, Sentiment Surfer) aus Dokumentation und Frontend-Code entfernt. Nur Edge Indicator und Liquidation Hunter bleiben.
- **2FA/TOTP-Referenzen entfernt** — Integrations-Dokumentation aktualisiert (2FA wurde aus dem Bot entfernt).
- **App-Name aktualisiert** — SETUP.md verwendet jetzt "Edge Bots by Trading Department" statt "Bitget Trading Bot".
- **Exchange-Liste aktualisiert** — FAQ listet jetzt alle 5 Exchanges (Bitget, BingX, Weex, Bitunix, Hyperliquid).
- **Frontend: `contrarian_pulse` entfernt** — Aus `strategies.ts`, `BotBuilderTypes.ts` und i18n-Dateien (de/en) bereinigt.

---

## [4.12.7] - 2026-04-01

### Hinzugefuegt
- **Demo-Mode-aware Symbol-Validierung** — `get_exchange_symbols()` akzeptiert jetzt einen `demo_mode`-Parameter mit separatem Cache fuer Demo vs. Live:
  - **BingX Demo**: Holt Symbole von `open-api-vst.bingx.com` statt `open-api.bingx.com`
  - **Hyperliquid Testnet**: Holt Symbole von `api.hyperliquid-testnet.xyz` statt `api.hyperliquid.xyz`
  - **Bitget/Weex/Bitunix**: Gleiche URL fuer Demo und Live (unveraendert)
- **`validate_symbol()` Methode in `ExchangeClient` Basisklasse** — Praktische Validierung per `get_ticker()`, ob ein Symbol tatsaechlich handelbar ist. Faengt Faelle ab, in denen die Symbolliste ein Paar listet, das im Demo-Modus nicht tradebar ist.
- **Praktische Symbol-Validierung im Bot-Worker** — Nach dem Symbollistencheck wird jedes Trading-Pair per `validate_symbol()` gegen die Exchange geprueft. Klare Fehlermeldung wenn ein Symbol zwar existiert aber im aktuellen Modus nicht handelbar ist.
- **`?demo=true` Query-Parameter fuer `/api/exchanges/{name}/symbols`** — Ermoeglicht Abfrage der Demo-Symbolliste ueber die API.

### Geaendert
- **Bot-Erstellung und -Update validieren Symbole jetzt modus-abhaengig** — `POST /api/bots` und `PUT /api/bots/{id}` uebergeben den Bot-Modus (demo/live/both) an die Symbol-Validierung.

---

## [4.12.6] - 2026-04-01

### Behoben
- **24 fehlgeschlagene Tests nach RiskManager-Refactoring behoben** — Testdateien an die entfernte JSON-Dateispeicherung angepasst:
  - `test_risk_manager.py`: `TestGetStatsFile`, `TestLoadDailyStats`, `TestSaveDailyStats` und `TestStatsFileHelpers` entfernt (testen entfernte Methoden). `TestGetHistoricalStats` und `TestGetPerformanceSummary` an neues Verhalten (leere Liste) angepasst. Tests fuer `data_dir`, `initialize_day`, `_halt_trading` und `net_pnl` an DB-basierte Architektur angepasst.
  - `test_production_hardening.py`: `response=MagicMock()` Parameter zu allen `login()`, `change_password()` und `refresh_token()` Aufrufen hinzugefuegt (2FA-Entfernung hat `Response`-Parameter eingefuehrt).
  - `test_auth.py`: Keine Aenderungen noetig — bereits korrekt.

---

## [4.12.5] - 2026-04-01

### Entfernt
- **Inline SQLite-Migrationen entfernt** — Die gesamte `_run_sqlite_migrations()`-Funktion (~150 Zeilen raw ALTER TABLE/CREATE TABLE) aus `src/models/session.py` entfernt. Alembic ist jetzt das einzige Migrationssystem. Die App wird auf PostgreSQL deployed; SQLite braucht keinen eigenen Migrationspfad.
- **`requests`-Bibliothek aus requirements.txt entfernt** — War neben `httpx` und `aiohttp` gelistet, wurde aber nirgendwo in `src/` importiert.

### Geaendert
- **MAX_BOTS_PER_USER zentralisiert** — Duplizierte Konstante aus `orchestrator.py` und `bots.py` in `src/constants.py` zusammengefuehrt. Beide Dateien importieren jetzt von dort.
- **Rate Limiting fuer bots_statistics-Endpunkte** — `GET /{bot_id}/statistics` und `GET /compare/performance` haben jetzt 30/minute Rate Limiting (gleicher Pattern wie auth.py und statistics.py).
- **Orchestrator-Logging auf lazy %s-Format umgestellt** — Alle f-String-Logging-Aufrufe durch `logger.info("...", arg)` ersetzt, um unnoetige String-Formatierung zu vermeiden.
- **Hardcodierten `data_dir`-Pfad durch Umgebungsvariable ersetzt** — `risk_manager.py` nutzt jetzt `os.getenv("RISK_DATA_DIR", "data/risk")` statt des hartkodierten Standardwerts.

---

## [4.12.4] - 2026-04-01

### Geaendert
- **RiskManager: JSON-Dateispeicherung entfernt, DB ist einzige Quelle** — `_read_stats_file()`, `_write_stats_file()`, `_get_stats_file()`, `_load_daily_stats()` und `get_historical_stats()` (dateibasiert) wurden entfernt. Die Datenbank (risk_stats-Tabelle) ist jetzt die einzige Persistenzschicht. `data_dir`-Parameter bleibt fuer Rueckwaertskompatibilitaet erhalten, wird aber ignoriert.
- **TradeLogger: Blocking I/O in async Event Loop behoben** — `log_trade_entry()` und `log_trade_exit()` schreiben Trade-Logs jetzt ueber `asyncio.to_thread()` statt synchronem `open()`, um den Event Loop nicht zu blockieren. Neuer Helper `_schedule_log_write()` fuer non-blocking Writes mit synchronem Fallback.

---

## [4.12.3] - 2026-04-01

### Sicherheit
- **Refresh Token Revocation: Session-Validierung auch für Body-Tokens** — Die Session-Prüfung im `/api/auth/refresh`-Endpoint wurde bisher nur für Cookie-basierte Tokens durchgeführt. Tokens im Request-Body konnten die Session-Validierung umgehen und blieben nach Logout weiterhin gültig. Jetzt werden alle Refresh-Tokens gegen die `user_sessions`-Tabelle geprüft.
- **Passwortänderung invalidiert jetzt alle bestehenden Sessions** — Beim Passwortwechsel wurde zwar `token_version` erhöht, aber bestehende Sessions in der DB blieben aktiv. Jetzt werden alle Sessions deaktiviert und eine neue Session für das aktuelle Gerät erstellt.

### Behoben
- **Risk Manager: Stille `RuntimeError`-Unterdrückung durch Debug-Log ersetzt** — In `_save_daily_stats()` wurde `except RuntimeError: pass` durch ein Debug-Log ersetzt, das erklärt warum der DB-Write übersprungen wird.
- **Audit Log: Fehler-Zähler für fehlgeschlagene Audit-Schreibvorgänge** — `_store_audit_record_safe` zählt jetzt Fehler in einem globalen Counter. Der Zähler wird im `/api/health`-Endpoint angezeigt, sodass stumme Audit-Lücken sichtbar werden.

---

## [4.12.2] - 2026-04-01

### Verbessert
- **Web3-Abhängigkeiten lazy-loaded** — `@rainbow-me/rainbowkit`, `wagmi` und `viem` (~500KB+) werden jetzt per `React.lazy()` nur geladen, wenn der Hyperliquid-Setup tatsächlich angezeigt wird. Vorher wurden sie für alle Nutzer in das Haupt-Bundle eingebunden, unabhängig von der gewählten Exchange.

---

## [4.12.1] - 2026-04-01

### Behoben
- **KRITISCH: Hyperliquid TP/SL-Fehler wurden stillschweigend verschluckt** — `_place_trigger_order` hat Exceptions gefangen ohne den Fehlerstatus weiterzugeben. Das zurückgegebene `Order`-Objekt hatte immer `tpsl_failed=False`, sodass der `trade_executor` niemals Fallback-TP/SL oder Risiko-Alerts auslösen konnte. Die Methode gibt jetzt `bool` zurück und `place_market_order` setzt `tpsl_failed=True` bei fehlgeschlagenen Trigger-Orders.

---

## [4.12.0] - 2026-04-01

### Behoben
- **net_pnl Berechnung: abs(total_funding) entfernt** — In `statistics.py`, `risk_manager.py` und `tax_report.py` wurde `abs(total_funding)` durch `total_funding` ersetzt. `funding_paid` wird bereits als positiver Kostenwert gespeichert; `abs()` konnte das Vorzeichen bei empfangenem Funding-Einkommen falsch maskieren (#4)

### Entfernt
- **Contrarian Pulse Strategie komplett entfernt** — `src/strategy/contrarian_pulse.py` geloescht und alle Imports/Referenzen aus `src/strategy/__init__.py` entfernt. Die Strategie hatte ~70% Ueberlappung mit Liquidation Hunter und wurde bereits im Frontend nicht mehr verwendet

---

## [4.11.3] - 2026-04-01

### Behoben
- **KRITISCH: Falsche Position-Schließung bei API-Exceptions** — `_confirm_position_closed` hat `True` zurückgegeben wenn alle Retries Exceptions warfen, was zu falschen Schließungen führte. Jetzt wird `False` zurückgegeben wenn Exceptions aufgetreten sind.
- **Race Condition im Trailing-Stop-Lock** — Backoff-Timestamp wurde außerhalb des Locks aktualisiert, was gleichzeitigen Re-Entry ermöglichte. Timestamp wird jetzt innerhalb des Locks gesetzt.
- **Off-by-one im Retry-Count** — `range(1, _POSITION_GONE_THRESHOLD)` ergab nur 2 statt 3 Iterationen. Korrigiert zu `range(1, _POSITION_GONE_THRESHOLD + 1)`.

---

## [4.11.2] - 2026-04-01

### Bereinigt
- **Backend Refactoring: Trailing Stop Deduplizierung** — Identische `_check_trailing_stop`-Methoden aus `EdgeIndicatorStrategy` und `LiquidationHunterStrategy` in eine gemeinsame `check_atr_trailing_stop()`-Funktion in `strategy/base.py` extrahiert. Beide Strategien delegieren jetzt an die gemeinsame Funktion.
- **Backend Refactoring: PnL-Berechnung zentralisiert** — Inline-PnL-Berechnungen in `trades.py::sync_trades` und `bots_lifecycle.py::close_position` durch Aufrufe der bestehenden `calculate_pnl()`-Funktion aus `bot/pnl.py` ersetzt.
- **Backend Refactoring: Doppelter Exchange-Client-Code entfernt** — `portfolio.py::_get_all_user_clients` delegiert jetzt an `factory.py::get_all_user_clients` statt die gleiche Logik zu duplizieren.
- **Backend: Import-Pfad korrigiert** — `risk_manager.py` importiert `calculate_pnl` jetzt direkt aus `bot/pnl.py` statt über den Umweg `bot/bot_worker.py`. Der unnötige Re-Export in `bot_worker.py` wurde entfernt.
- **Backend: Irreführenden noqa-Kommentar entfernt** — `auth.py` Import von `_get_real_client_ip` war als "re-export for backward compat" markiert, wird aber tatsächlich im selben Modul verwendet.

---

## [4.11.1] - 2026-04-01

### Bereinigt
- **Frontend Code Cleanup** — Stale Kommentare entfernt (`Bots.tsx`: BuilderFeeApproval-Hinweis, utcHourToLocal-Import-Notiz), doppelten Kommentar in `Portfolio.tsx` entfernt, überflüssige Leerzeilen in `Bots.tsx` und `BotPerformance.tsx` bereinigt
- **Ungenutzte CSS-Klassen entfernt** — `.overlay-fade` (inkl. `@keyframes fadeOverlay`) und `.transition-smooth` aus `index.css` entfernt, da sie nirgendwo im Code referenziert wurden

---

## [4.11.0] - 2026-04-01

### Hinzugefügt
- **Builder Wallet Balance-Hinweis** — Im Hyperliquid-Setup (Settings-Seite und Builder Fee Approval Modal) wird jetzt ein Hinweis angezeigt, dass die Builder Wallet mindestens 100 USDC Guthaben benötigt, damit Trades ausgeführt werden können. Der Hinweis erscheint sowohl vor der Signierung als auch nach erfolgreicher Genehmigung.
- **Fehlende Übersetzung `builderFee.signRejected`** — Neuer i18n-Schlüssel für die Fehlermeldung bei abgelehnter Wallet-Signierung, in DE ("Signierung wurde abgelehnt.") und EN ("Signing was rejected."). Vorher nur als Inline-Fallback vorhanden.
- **`hlSetup.builderWalletHint`** — Neuer Übersetzungsschlüssel für den Builder-Wallet-Balance-Hinweis (DE + EN)

### Geprüft
- **Deutsche Übersetzungen vollständig geprüft** — Alle `hlSetup.*` und `builderFee.*` Schlüssel in `de.json` sind korrekt auf Deutsch übersetzt. Alle Hardcoded-Fallbacks in `BotBuilderStepExchange.tsx`, `HyperliquidSetup.tsx`, `BuilderFeeApproval.tsx` und `Bots.tsx` stimmen mit den i18n-Einträgen überein.

---

## [4.10.0] - 2026-04-01

### Hinzugefügt
- **Exchange-Fehlermeldungen auf Deutsch übersetzt** — Neue Übersetzungsfunktion `translate_exchange_error()` in `src/errors.py` mit 40+ englisch→deutsch Zuordnungen für häufige Exchange-API-Fehler:
  - Bitget TP/SL-Preisfehler (Long/Short)
  - Guthaben-/Margin-Fehler (Insufficient balance, margin)
  - Order-Fehler (nicht gefunden, zu klein, Preislimit)
  - Positions-Fehler (nicht vorhanden, Schließbetrag)
  - Hebel-Fehler (zu hoch, nicht im erlaubten Bereich)
  - API-Key/Auth-Fehler (ungültig, abgelaufen, IP-Whitelist)
  - Netzwerk-/Timeout-Fehler
  - Exchange-spezifische Fehler (Hyperliquid, BingX)
- **TP/SL-Validierungsmeldungen auf Deutsch** — Alle hartcodierten englischen Fehlermeldungen im TP/SL-Endpunkt (`PUT /trades/{id}/tp-sl`) durch deutsche Fehlerkonstanten aus `src/errors.py` ersetzt
- **Unit-Tests** — 17 Tests für die Übersetzungsfunktion (`tests/unit/test_exchange_error_translation.py`)

### Geändert
- **Error Handler Middleware** — Übersetzt jetzt Exchange-Fehler automatisch ins Deutsche bevor sie an das Frontend gesendet werden
- **Bot Lifecycle Router** — Exchange-Fehler bei Start/Restart werden jetzt übersetzt
- **Trades Router** — Exchange-Validierungsfehler (TP/SL) werden übersetzt; alle lokalen Validierungsmeldungen nutzen jetzt zentrale Fehlerkonstanten

---

## [4.9.0] - 2026-04-01

### Entfernt
- **2FA/TOTP komplett entfernt** — Zwei-Faktor-Authentifizierung (TOTP, Backup-Codes, QR-Code-Setup) wurde aus dem gesamten Projekt entfernt:
  - **Backend**: TOTP-Endpunkte (`/2fa/setup`, `/2fa/verify-setup`, `/2fa/verify-login`, `/2fa/disable`, `/2fa/backup-codes`) entfernt, Login-Flow vereinfacht (kein Temp-Token-Schritt mehr), `totp_secret`/`totp_enabled`/`totp_backup_codes` aus User-Model entfernt, 2FA-Fehler-Konstanten entfernt
  - **Frontend**: 2FA-Schritt aus Login-Seite entfernt, `verify2fa`/`tempToken`/`requires2fa` aus Auth-Store entfernt, 2FA-Bereich aus Settings-Seite entfernt, `totp_enabled` aus User-Type entfernt
  - **i18n**: Alle `login.2fa.*` und `settings.twoFactor*` Uebersetzungsschluessel aus DE + EN entfernt
  - **Tests**: TOTP-bezogene Mock-Felder aus test_auth.py und test_production_hardening.py entfernt
  - **Dependencies**: `pyotp` und `qrcode[pil]` aus requirements.txt entfernt
  - **Migration**: Neue Migration 017 entfernt `totp_secret`, `totp_enabled`, `totp_backup_codes` Spalten aus der `users`-Tabelle

---

## [4.8.2] - 2026-04-01

### Hinzugefügt
- **BotBuilder Hyperliquid Gate-Check**: Warnung im Exchange-Schritt wenn Referral oder Builder Fee noch nicht abgeschlossen sind (amber Banner, kein Hard-Block)
- **Bots-Seite HL-Warnung**: Amber Banner auf Bot-Karten für Hyperliquid-Bots mit unvollständiger Einrichtung (Admins ausgenommen)
- **i18n**: Neue Übersetzungsschlüssel für HL Gate-Warnungen (DE + EN)

### Behoben
- **Orchestrator `user_id=0` Fix**: `_update_instance_state` fragt jetzt `BotConfig` aus der DB ab wenn der Worker keine Config hat, statt `user_id=0` / `exchange_type="unknown"` als Fallback zu verwenden

### Geändert (UI)
- **Affiliate-Link-Karten (Settings)**: Karten sind jetzt einklappbar/ausklappbar — standardmäßig eingeklappt, nur Exchange-Name, Icon, Status-Badge und Chevron sichtbar. Klick öffnet die Formulare. Spart Platz bei vielen Exchanges.

---

## [4.8.1] - 2026-04-01

### Geändert (UI)
- **Bot-Aktionsleiste**: Stoppen/Starten, Trade-Historie und 3-Punkte-Menü jetzt alle in einer Zeile (kompaktere Buttons, kleinere Icons)
- Trade-Historie-Label wird jetzt immer angezeigt (nicht mehr nur auf Desktop)
- **Share-Button (Desktop)**: In der Detail-Zeile neben Modus eingereiht statt in eigener Zeile unten

### Behoben
- **Share-to-Clipboard (Desktop)**: Bild wird jetzt korrekt in die Zwischenablage kopiert (ClipboardItem erhält Promise statt fertigen Blob, damit Chrome's User-Gesture-Fenster nicht abläuft)
- **Mobile Trade-Karten**: Datum wird jetzt oben rechts im Header angezeigt (wie auf Desktop)
- **Share-Button Position**: Eigene Grid-Zelle in Detail-Zeile (sauber ausgerichtet wie andere Felder) — in Performance-Tab und Bot Trade-Historie
- **Clipboard-Fix (Bots Trade-Historie)**: Promise-basierter ClipboardItem auch hier angewendet
- **Desktop Share öffnete Teilen-Dialog statt Zwischenablage**: Mobile-Erkennung per Touch-Events erkannte Touchscreen-Laptops fälschlich als Mobil → jetzt User-Agent-basiert
- MobileTradeCard: Doppeltes Datum im Header wieder entfernt (Summary-Zeile hat es bereits)
- **Trade-ID entfernt**: Interne DB-ID aus Detail-Ansicht entfernt (nicht relevant für Enduser)
- Share-Button inline neben DEMO/LIVE in der Modus-Zelle
- **Session-Verbesserung**: Access-Token von 4h auf 24h verlängert, sofortiger Refresh wenn Tab nach Sleep/Idle reaktiviert wird

---

## [4.8.0] - 2026-03-31

### Behoben (Mobile UI)
- **Step-Indikator im Bot Builder**: Zeigt auf Mobile nur Schrittnummern + aktuellen Namen, horizontal scrollbar
- **Exchange-Buttons Overflow**: `flex-wrap` damit alle Exchanges sichtbar sind
- **Modus/Margin-Modus Überlappung**: Auf Mobile vertikal gestapelt statt nebeneinander
- **Suchleiste Text/Lupe Überlappung**: Input padding-left erhöht für Icon-Platz
- **Balance-Übersicht Mobile**: Karten-Layout statt Tabelle (Logo + Modus + Kapital pro Exchange)
- **Weiter-Button Position**: Cancel links, Weiter rechts — immer in einer Reihe (inline style)
- **Telegram Text-Overflow**: `break-words` + `overflow-wrap: anywhere` für URLs
- **Bot-Löschen Buttons nicht übersetzt**: `common.delete` i18n-Keys in de.json/en.json ergänzt
- **Trailing Stop Slider State**: `useEffect` synct Toggle + ATR-Wert bei Position-Wechsel, `MobilePositionCard` übergibt `trailing_atr_override` + `native_trailing_stop`
- **Desktop Share kopiert nicht**: Desktop nutzt jetzt Clipboard statt `navigator.share`

### Verbessert
- **Übersicht-Schritt (Bot Builder Review)**: Visuelles Upgrade mit gruppierten Karten, Icons, Farbcodes und besserer Hierarchie
- **30 Umlaut-Fixes**: ue→ü, ae→ä, oe→ö, ss→ß in de.json, errors.py, tax_report.py, Strategien, Bot-Komponenten, Hyperliquid-Gates
- **Share-Karten komplett überarbeitet**: Kompaktes Format (Symbol + Perp|Side|Hebel|Datum, zentrierter PnL, Einstieg/Ausstieg nebeneinander)
- **Alle Share-Icons auf Share2 (Android 3-Punkte)**: Einheitlich in MobileTradeCard, Trade-Listen, Modals
- **"Bild kopieren" entfernt**: Nur noch ein "Teilen" Button (Mobile → App-Auswahl, Desktop → Clipboard)
- **Native Web Share API**: Affiliate-Link als Text bei `navigator.share()` — erscheint in WhatsApp/Telegram
- **Direct Mobile Share**: Share-Button in Trade-Liste öffnet direkt die App-Auswahl ohne Umweg über Modal
- **Letzter Trade Karte (Mobile)**: PnL zentriert groß, Einstieg/Ausstieg zentriert nebeneinander
- **Datum in Share-Karten**: Verschoben in die Perp|Side|Leverage Zeile (oben rechts)
- **X-Buttons auf Mobile ausgeblendet**: In Trade-Detail und Bot-Detail Modals (Swipe-to-Close reicht)
- **Redundanter "Teilen" Button bei "LETZTER TRADE" entfernt**: Klick auf Trade öffnet Detail-Modal
- **Nginx Cache-Headers**: `no-cache` für index.html + sw.js, `immutable` für Vite-Assets
- **Service Worker Cache v2**: Invalidiert alten Cache bei Deployment

---

## [4.7.0] - 2026-03-31

### Sicherheit (Security Audit)
- **JWT httpOnly Cookie Migration**: Access-Token wird jetzt als httpOnly Cookie gesetzt statt in localStorage — verhindert Token-Diebstahl durch XSS
  - Backend: Cookie-Fallback in `get_current_user()`, alle Auth-Endpoints setzen Cookie
  - Frontend: localStorage komplett entfernt, `withCredentials: true` sendet Cookies automatisch
  - WebSocket: Authentifizierung per Cookie statt Token-Nachricht
  - Backward-kompatibel: Bearer Header funktioniert weiterhin

### Verbessert
- **config.py aufgeteilt (SRP)**: 1.186 LOC Monolith-Router in 4 fokussierte Module gesplittet: `config_exchange.py`, `config_trading.py`, `config_affiliate.py`, `config_hyperliquid.py` + shared `config_service.py` — alle API-Pfade unverändert
- **BotBuilder.tsx aufgeteilt**: 1.928 LOC Monolith-Komponente in 8 fokussierte Dateien gesplittet (BotBuilderStepName, StepStrategy, StepDataSources, StepExchange, StepNotifications, StepSchedule, StepReview + Types)
- **Accessibility (a11y)**: `aria-busy` auf Ladecontainern, `aria-label` auf Icon-Buttons, NumInput Keyboard-Navigation, Toast `aria-live="polite"`
- **Empty States**: Dashboard, Trades, Bots, Portfolio haben jetzt Icons + Beschreibungstexte statt leerer Tabellen
- **Light-Mode Chart Themes**: PnlChart, ChartTooltip, RevenueChart, Portfolio-Charts nutzen jetzt theme-aware Farben
- **Trailing Stop Slider (Mobile Fix)**: `touch-action: none` + `stopPropagation` verhindert Swipe-Konflikt mit Bottom-Sheet

---

## [4.6.12] - 2026-03-31

### Sicherheit (Security Audit)
- **Raw SQL durch ORM-Inserts ersetzt (config_audit.py)**: `text("INSERT INTO config_change_logs ...")` durch `ConfigChangeLog`-Model + `session.add()` ersetzt — verhindert potenzielle SQL-Injection
- **Raw SQL durch ORM-Inserts ersetzt (event_logger.py)**: `text("INSERT INTO event_logs ...")` durch `EventLog`-Model + `session.add()` ersetzt — verhindert potenzielle SQL-Injection
- **CORS Origin-Validierung (main_app.py)**: Werte aus `CORS_ORIGINS` werden jetzt per `urlparse` auf gueltiges Schema und Host geprueft. Ungueltige Eintraege werden geloggt und uebersprungen
- **SPA Path-Traversal gibt 404 zurueck (main_app.py)**: Bei erkannter Path-Traversal wird jetzt `HTTPException(404)` statt `index.html` zurueckgegeben — verhindert Information Disclosure
- **Static-File Extension-Whitelist (main_app.py)**: Der SPA Catch-All-Endpoint liefert nur noch Dateien mit erlaubten Endungen aus (.html, .css, .js, .json, .png, etc.). Alle anderen Dateitypen ergeben 404
- **npm Dependency-Schwachstellen behoben (frontend)**: 4 Schwachstellen (1 high, 3 moderate) gefixt
  - `picomatch` Method Injection + ReDoS (high)
  - `brace-expansion` ReDoS (moderate)
  - `esbuild` Dev-Server Request-Schwachstelle (moderate)
  - `vite` von v5.4.21 auf v7.3.1 aktualisiert

---

## [4.6.11] - 2026-03-31

### Behoben
- **Trailing Stop Toggle-State nicht korrekt**: `trailingAtr` wurde immer auf 2.5 initialisiert statt den gespeicherten Wert aus `position.trailing_stop_distance_pct` zu verwenden
- **TP/SL-Validierung nur gegen Entry-Price**: Exchanges wie Bitget lehnen SL/TP ab wenn sie auf der falschen Seite des aktuellen Preises liegen. Validierung prueft jetzt zusaetzlich gegen `current_price`
- **Generische Fehlermeldungen bei API-Fehler**: Der Catch-Block zeigt jetzt die echte Exchange-Fehlermeldung aus `response.data.detail` an statt nur "Fehler beim Speichern"

### Hinzugefuegt
- **ATR-Erklaerungstext im Trailing Stop**: Neuer Hilfetext erklaert was der ATR-Multiplikator bedeutet (1.0x = eng, 3.0x = Standard, 5.0x = weit)
- **i18n-Keys fuer neue Validierungsmeldungen**: `slAboveCurrentPrice`, `slBelowCurrentPrice`, `tpBelowCurrentPrice`, `tpAboveCurrentPrice`, `atrExplanation` in de.json und en.json

---

## [4.6.10] - 2026-03-31

### Behoben
- **Hyperliquid positionTpsl KeyError**: `set_position_tpsl()` verwendete `"name"` als Key im Order-Dict fuer `bulk_orders()`, aber das Hyperliquid SDK erwartet `"coin"` bei `grouping="positionTpsl"`. Gefixt fuer TP- und SL-Order. Fallback `_place_trigger_order()` bleibt bei `"name"` (korrekt fuer Einzel-Orders via `order()`)
- **Zahnrad-Icon fehlt bei Hyperliquid-Positionen**: Position-Trade-Matching in Portfolio nutzte exakten Symbol-Vergleich (`ETHUSDT` vs `ETH`), was bei Hyperliquid fehlschlug. Jetzt wird `normalize_symbol()` auf beiden Seiten (DB + Exchange-API) angewendet — funktioniert fuer alle 5 Exchanges (Bitget, Weex, Hyperliquid, Bitunix, BingX). Zusaetzlich: `normalize_symbol()` Fallback fuer Hyperliquid gefixt (strippte bisher kein USDT-Suffix), und bei Duplikat-Keys wird der neueste Trade bevorzugt
- **Trailing-Stop-Slider zeigt gespeicherten Wert**: ATR-Slider im TP/SL-Panel startete immer bei 2.5x, ignorierte den gespeicherten `trailing_atr_override`. Jetzt wird der Override-Wert aus der API geladen und als Slider-Startwert gesetzt (Schema, Backend-Response, Frontend in Dashboard/Portfolio/MobilePositionCard)
- **BingX/Weex: Orphan-TP/SL-Orders bei Update**: Beim Aendern von TP/SL wurden neue Orders auf der Exchange platziert ohne die alten zu loeschen — fuehrte zu doppelten Triggern. Jetzt werden bestehende TP/SL-Orders VOR dem Platzieren neuer gecancelt (BingX via open_orders-Query + cancel, Weex via pendingTpSlOrders + cancelTpSlOrder). BingX-Cancel erkennt auch `TRAILING_STOP_MARKET` Orders und `orderType`-Feldnamen-Fallback. Cancel wird ebenfalls bei `place_trailing_stop` aufgerufen
- **TypeScript-Typen fuer `trailing_atr_override`**: Fehlende Felddefinition in `PortfolioPosition` (types/index.ts) und `Position` (MobilePositionCard.tsx) ergaenzt — verhindert TypeScript-Kompilierfehler
- **`normalize_symbol()` Replace-Reihenfolge**: `.replace("USDT","").replace("-USDT","")` erzeugte fuer Hyperliquid-Eingaben wie `ETH-USDT` das Ergebnis `ETH-` (mit Bindestrich). Reihenfolge umgekehrt: zuerst `-USDT`, dann `USDT` strippen
- **TP/SL Cancel auf allen Exchanges**: Neue `cancel_position_tpsl()` Methode auf allen 5 Exchanges — fragt offene TP/SL-Orders ab und cancelt sie gezielt. Behebt das Problem dass alte TP/SL-Orders auf der Exchange verbleiben wenn neue gesetzt oder bestehende entfernt werden
- **Race Condition bei TP/SL-Update**: Strategie "Place First, Cancel Old" — neue Orders werden zuerst platziert, dann alte gecancelt. Position ist nie ungeschützt, auch bei API-Fehlern
- **Beide TP+SL entfernen entfernt jetzt auch Exchange-Orders**: Wenn beide Werte gleichzeitig gelöscht werden, wird `cancel_position_tpsl()` direkt aufgerufen statt den Exchange-Call zu überspringen

### Dokumentation
- **Anleitungen aktualisiert**: Strategien-Uebersicht von 3 auf 2 Strategien (Sentiment Surfer entfernt), LLM-Provider-Konfiguration als Archiv markiert, 15m/Aggressiv-Profil aus Risikoprofil-Anleitung entfernt, README mit Edge Bots Branding aktualisiert

### Hinzugefuegt
- **E2E-Tests fuer TP/SL-Bearbeitung (alle 5 Exchanges)**: 20 parametrisierte Tests (5 Exchanges x 4 Szenarien) — verifiziert die "Place First, Cancel Old"-Strategie fuer Bitget, BingX, Weex, Hyperliquid und Bitunix. Testet: neuen TP setzen, SL aendern, TP entfernen (SL behalten), beide entfernen
- **BingX `cancel_position_tpsl()`**: Fragt `/openApi/swap/v2/trade/openOrders` ab, filtert auf `TAKE_PROFIT_MARKET`/`STOP_MARKET` nach Symbol und Position-Side, cancelt jede Order einzeln
- **Weex `cancel_position_tpsl()`**: Fragt `/capi/v3/pendingTpSlOrders` ab, filtert nach Symbol und Position-Side, cancelt via `/capi/v3/cancelTpSlOrder`
- **Bitget `cancel_position_tpsl()`**: Fragt `/api/v2/mix/order/orders-pending` ab, filtert nach TP/SL Plan-Order-Typen und Hold-Side, cancelt jede Order einzeln
- **Hyperliquid `cancel_position_tpsl()`**: Zwei-Stufen-Strategie — (1) leere `positionTpsl` via `bulk_orders` zum Clearen aller Trigger, (2) Fallback: `open_orders` abfragen und Trigger-Orders einzeln canceln
- **Bitunix `cancel_position_tpsl()`**: Fragt `/api/v1/futures/tpsl/get_pending_orders` ab, filtert nach Symbol und Position-Side, cancelt via `/api/v1/futures/tpsl/cancel_order`

## [4.6.9] - 2026-03-31

### Behoben
- **TP/SL Entfernen sendet finalen Zustand an Exchange**: Beim Entfernen von TP wird jetzt der verbleibende SL mitgeschickt (und umgekehrt), statt beide auf null zu setzen — verhindert Bitget "must set one or both" Fehler
- **Share-Icon einheitlich**: Desktop und Mobile nutzen jetzt das Android 3-Punkte Share-Icon statt "Bild kopieren" Text-Button. Mobil immer sichtbar in der Header-Zeile

### Performance-Optimierungen
- **Vite Chunk-Splitting**: Wallet-Libs (wagmi/viem/rainbowkit) und Recharts in separate Bundles — kleineres Hauptbundle
- **3 neue DB-Indexes**: `ix_trade_user_demo`, `ix_funding_user_timestamp`, `ix_funding_user_symbol` (Migration 016)
- **N+1 Kline-Fix**: Portfolio-Positions nutzt Batch-Kline-Cache statt N einzelner Binance-API-Calls
- **Toter Code entfernt**: BotDetail.tsx (438 Zeilen), 3 npm-Pakete, tote i18n-Keys, unbenutzte CSS

## [4.6.8] - 2026-03-30

### Verbessert
- **Error Toasts statt stiller Fehler**: `console.error`-Aufrufe in Bots.tsx, BotPerformance.tsx und Dashboard.tsx zeigen jetzt zusätzlich einen Toast — Benutzer sehen sofort, wenn Bildkopie, Trade-Historie oder Positionen-Laden fehlschlägt
- **Dashboard Memoization**: `sortedPositions` in `DashboardOpenPositions` mit `useMemo` gewrappt, `onEditPosition` mit `useCallback` im Parent — verhindert unnötige Re-Renders
- **Aria-Labels ergänzt**: Theme-Toggle und Sprach-Toggle in MobileBottomNav, PnL-Sort-Button im Dashboard — verbesserte Screenreader-Unterstützung

## [4.6.7] - 2026-03-30

### Behoben
- **i18n: Ungenutzte Keys entfernt**: "bot"-Namespace (ohne 's') aus de.json und en.json entfernt — war veraltet und nicht mehr in Verwendung. "bots"-Namespace (mit 's') bleibt erhalten
- **i18n: Weitere ungenutzte Keys entfernt**: `dashboard.balance`, `dashboard.openPositions`, `dashboard.recentTrades`, `dashboard.noPositions`, `settings.free`, `settings.models`, `settings.availableModels`, `settings.defaultModel` aus beiden Sprachdateien entfernt
- **i18n: "ws"-Namespace hinzugefügt**: WebSocket-Benachrichtigungs-Übersetzungen (botStarted, botStopped, tradeOpened, tradeClosed, connectionLost, reconnecting) in de.json und en.json ergänzt
- **CSS: `.glass-card-hover` entfernt**: Ungenutzte CSS-Klasse und zugehörige Light-Mode-Variante aus index.css entfernt

## [4.6.6] - 2026-03-30

### Behoben
- **PNL-Charts zeigen jetzt nach Schließdatum**: Alle Endpoints (Dashboard, Portfolio Summary, Portfolio Daily, Revenue-Analytics, Bot-Statistiken, Config-Revenue) gruppierten Trades bisher nach Eröffnungsdatum (`entry_time`). Umgestellt auf `exit_time` mit COALESCE-Fallback auf `entry_time` bei NULL-Werten — zeigt realisierten PNL am Tag der tatsächlichen Schließung, wie bei Exchanges üblich
- **Steuerbericht nach Veräußerungsdatum**: Steuerbericht ordnete Trades bisher nach Eröffnungsdatum dem Steuerjahr zu. Umgestellt auf `exit_time` (Veräußerungsdatum) — steuerlich relevant nach §23 EStG. Trade am 31.12. eröffnet, am 02.01. geschlossen, landet jetzt korrekt im neuen Steuerjahr
- **"Bots.confidence" Übersetzung fehlte**: Der Schlüssel `bots.confidence` war in den Sprachdateien nicht vorhanden und wurde als roher Key angezeigt. Übersetzung ergänzt: "Konfidenz" (DE) / "Confidence" (EN)
- **CSV-Test für leeres Jahr**: Test prüfte auf englischen Text ("Trade Count"), aber CSV wird standardmäßig auf Deutsch generiert ("Anzahl Trades")
- **"Trades.confidence" in Mobile-Karte**: MobileTradeCard nutzte `trades.confidence` statt `bots.confidence` — zeigt jetzt korrekt "Konfidenz" / "Confidence"
- **Demo-Trade unter LIVE angezeigt**: Dashboard filterte offene Positionen nicht nach Demo/Live-Modus. Demo-Trades erschienen unter "LIVE". Frontend-Filter hinzugefügt (Portfolio hatte den Filter bereits)
- **TP/SL sendet nur geänderte Werte an Exchange**: Beim Setzen von nur TP wurde der alte SL-Wert aus der DB mitgeschickt, was auf Bitget einen ungewollten SL erzeugte. Jetzt werden nur explizit vom User geänderte Werte an die Exchange gesendet
- **Circuit Breaker durch leeren TP/SL-Call**: Wenn beide Werte null waren, wurde trotzdem die Exchange-API aufgerufen → Bitget-Fehler → Circuit Breaker offen → alle Bitget-Daten weg. Jetzt wird die Exchange nur aufgerufen wenn mindestens ein Wert gesetzt ist
- **Security-Hardening TP/SL-Endpoint**: Row-Level-Lock (with_for_update), positive Wert-Validierung, sanitized Error-Response, extra="forbid" auf Request-Model, contradictory Flags abgelehnt
- **Trailing Stop Override löschen**: Wenn Trailing deaktiviert wird, wird trailing_atr_override in DB auf NULL gesetzt
- **Bot-Lösch-Dialog übersetzt**: "Delete Bot" / "Are you sure" jetzt auf Deutsch und Englisch korrekt
- **Sentiment Surfer Strategie entfernt**: Komplett gelöscht aus Backend, Frontend, Tests, Docs (1.987 Zeilen)

### Geaendert
- **Bot Trade-Historie: Einheitliche Card-Ansicht**: Desktop-Tabelle durch aufklappbare Trade-Cards ersetzt (gleiche Komponente wie mobil). Zeigt Einstieg, Ausstieg, PNL%, Hebel, Gebühren, Konfidenz und Exit-Grund. Kein horizontales Scrollen mehr
- **Hebel im Bot-Trade-Response**: Backend gibt jetzt `leverage` pro Trade zurück — sichtbar in der aufklappbaren Trade-Card zur Analyse vergangener Konfigurationen

### Entfernt
- **Trailing-Stop-Spalte aus Bot Trade-Historie**: Zeigt nach Trade-Schließung sowieso nur "--" — unnötige Spalte entfernt
- **Modus-Spalte aus Bot Trade-Historie**: Redundant, da der Bot selbst bereits das DEMO/LIVE-Label trägt
- **"Beide"-Modus im Bot Builder**: Option entfernt, Bots können nur noch "Demo" oder "Live" sein. Bestehende "both"-Bots funktionieren weiterhin im Backend

### Hinzugefuegt
- **Manueller Trailing-ATR-Override**: Neues DB-Feld `trailing_atr_override` auf TradeRecord (Alembic Migration 015). User kann per Slider den ATR-Multiplikator anpassen. Backend berechnet trigger_price und callback_% aus echtem ATR automatisch. Position Monitor und Strategy should_exit nutzen den Override. UI zeigt Trailing-Stop mit Shield-Symbol wenn aktiv
- **DB-Index auf `exit_time`**: Neuer Index `ix_trade_exit_time` für performante Abfragen nach Schließdatum (Alembic Migration 014)
- **Integration-Test für NULL-exit_time-Fallback**: Prüft, dass geschlossene Trades ohne `exit_time` via COALESCE auf `entry_time` zurückfallen und in Charts/Statistiken erscheinen
- **TP/SL + Trailing Stop nachträglich bearbeiten (Issue #120)**: Offene Positionen können jetzt per Zahnrad-Icon in Dashboard und Portfolio bearbeitet werden. Neuer Backend-Endpoint `PUT /api/trades/{id}/tp-sl` setzt TP/SL auf der Exchange und aktualisiert die DB. Frontend-Panel mit Preis/Prozent-Eingabe (bidirektional synchronisiert), ATR-Slider für Trailing Stop, Exchange-Hinweis (nativ vs. Bot-überwacht), Validierung (TP/SL-Richtung), und i18n DE/EN. Funktioniert auf allen Exchanges die `set_position_tpsl` unterstützen (Bitget, Hyperliquid, BingX, Weex, Bitunix)
- **Edge Indicator Anleitung (PDF)**: Vollständige zweisprachige Dokumentation der Strategie — Signallogik, Konfidenz-Bewertung, Trailing Stop, Risikomanagement, Exchange-Besonderheiten, alle Parameter. Unter `Anleitungen/Edge_Indicator_Strategie.pdf`

## [4.6.5] - 2026-03-28

### Hinzugefuegt
- **Admin-Rolle von Supabase synchronisieren**: Beim SSO-Login wird `app_metadata.role` aus dem Supabase JWT gelesen. Ist der Wert `admin`, wird der Bot-User automatisch zum Admin. Bestehende lokale Admins bleiben unangetastet (nur Upgrade, nie Downgrade)
- **Erweitertes User Management**: Admin-Panel zeigt jetzt pro User: verbundene Exchanges (Icons), aktive Bots, Gesamtzahl Trades, Auth-Provider (local/supabase), letzter Login. Hilft beim Support
- **Last-Login Tracking**: `last_login_at` wird bei jedem Login aktualisiert (lokal und SSO). Neue Alembic Migration 013

### Behoben
- **Einheitliche Zahlen-Schriftart**: `font-mono` von allen Trading-Tabellen entfernt (Portfolio, Dashboard, Bots, Trades). Alle Zahlen nutzen jetzt die gleiche Inter-Schrift mit `tabular-nums` fuer saubere Ausrichtung — konsistentes Erscheinungsbild ueber alle Seiten hinweg
- **3-Punkte-Menu hinter Sidebar**: Dropdown-Menu bei Bot-Karten in der linken Spalte wurde von der Sidebar verdeckt. Dropdown oeffnet jetzt nach rechts statt nach links
- **Live/Demo-Filter bei Positionen**: Portfolio-Seite filtert offene Positionen jetzt nach dem globalen Demo/Live-Modus. Im Live-Modus werden nur Live-Positionen angezeigt, nicht mehr alle
- **Light-Mode umfassend ueberarbeitet**:
  - Donut-Chart Text (Gesamt/Betrag) sichtbar gemacht
  - Period-Buttons mit gruenem Hintergrund + Glow
  - Settings-Seite farbliche Felder (LIVE/DEMO/Success-Banner) Light-Mode-kompatibel
  - Asset-Name (ETHUSDT etc.) in Trade-Karten sichtbar — Tailwind `darkMode: 'class'` aktiviert
  - Glass-Cards und alle Karten mit sichtbaren Raendern (`border-gray-200`, `shadow-sm`)
  - Globale Border-Overrides fuer `border-white/5`, `border-white/10`, `border-white/[0.06]` verstaerkt
  - Amber/Gelb-Texte (Warnungen, Testnet-Hinweise) auf dunkle Brauntoene umgestellt fuer Lesbarkeit
  - Blaue Hint-Texte (`text-blue-300`) auf `#2563eb` umgestellt
  - Admin User-Karten: Badges (Active/Inactive, Admin/User) mit `dark:` Prefix fuer beide Modi
  - MobileCollapsibleCard mit solidem Rand im Light-Mode
- **Tax Report CSV-Button**: Auf Mobile kompakter, immer horizontal neben dem Jahresdropdown
- **Uebersetzung**: `bots.confidence` korrigiert zu `trades.confidence` (zeigte rohen Schluessel statt "Konfidenz")
- **Admin API**: `BotConfig.is_active` zu `is_enabled` korrigiert, async SQLAlchemy Result-Handling gefixt

---

## [4.6.4] - 2026-03-28

### Sicherheit
- **JWT-Validierung auf JWKS/ES256 umgestellt**: Supabase nutzt ES256 (nicht HS256). Neuer `PyJWKClient` holt und cached den Public Key automatisch von Supabase JWKS-Endpoint. HS256 als erlaubter Algorithmus entfernt (Algorithm-Confusion-Schutz)
- **Issuer-Validierung**: JWT decode prueft jetzt `iss` Claim gegen konfigurierte `SUPABASE_PROJECT_URL` — Tokens von fremden Supabase-Projekten werden abgelehnt
- **Email-Bestaetigungspruefung**: `email_confirmed_at` Claim wird validiert — unbestaetigte Email-Adressen koennen keine Bot-Accounts verknuepfen (Account-Takeover-Schutz)
- **Rate-Limiting auf Auth Bridge**: `@limiter.limit("10/minute")` auf `/api/auth/bridge/generate` und `/exchange` — verhindert Brute-Force und DoS
- **BEHIND_PROXY aktiviert**: Rate-Limiter erkennt jetzt echte Client-IPs hinter Nginx statt nur 127.0.0.1
- **Nginx gehaertet**: TLS 1.0/1.1 deaktiviert (nur TLS 1.2+), `server_tokens off` aktiviert (Server-Version versteckt)

---

## [4.6.3] - 2026-03-28

### Hinzugefuegt
- **Hilfe-Tooltip auf Portfolio-Seite**: GuidedTour mit 3 Schritten (Übersicht, Charts & Allocation, Offene Positionen) analog zu Dashboard, Bots, Settings und Getting Started. Übersetzungen DE + EN.
- **Integrations-Anleitung**: Vollständige Schritt-für-Schritt-Anleitung (DE/EN) für die Integration in trading-department.com unter `Anleitungen/integration-plan-step-by-step.md`.
- **Auth Bridge Backend (Phase 1)**: Supabase-Auth-Integration mit One-Time-Code System. Neue Dateien: `src/auth/supabase_jwt.py`, `src/auth/auth_code.py`, `src/api/routers/auth_bridge.py`. Neue Endpoints: `POST /api/auth/bridge/generate` und `POST /api/auth/bridge/exchange`. Alembic Migration 012 fügt `supabase_user_id` und `auth_provider` zum User-Model hinzu. Auto-Provisioning erstellt Bot-Accounts für neue Supabase-User automatisch.
- **Auth Bridge Bugfixes**: Edge Function `getSession()` durch direkten JWT ersetzt (funktioniert nicht serverseitig). JWKS/ES256 statt HS256 fuer Supabase JWT-Validierung.
- **Nginx Subdomain Config**: `bots.trading-department.com` mit SSL (Let's Encrypt), Rate Limiting für Auth-Endpoints, alte duckdns-URL bleibt als Fallback.
- **Auth Callback Frontend (Phase 2)**: Neue `/auth/callback` Seite im Bot-Frontend empfängt One-Time-Codes und tauscht sie gegen Bot-JWT. Neuer `exchangeAuthCode()` im authStore. i18n Keys DE/EN.

---

## [4.6.2] - 2026-03-27

### Behoben
- **Dropdown-Buttons nicht klickbar (Bots-Seite)**: Desktop-Overlay (z-40) blockierte Klicks auf das 3-Punkt-Menue (Bearbeiten/Kopieren/Loeschen) weil der Bot-Card Stacking Context (z-30) das Dropdown einschloss. Overlay z-index auf z-20 gesenkt

### Geaendert
- **Dashboard Positions-Tabelle**: Vereinfachte Tabelle durch vollstaendige Portfolio-Version ersetzt — zeigt jetzt Trailing Stop (Preis, Distanz%, Shield-Icon), Size (Token/USDT toggle), PnL-Sortierung, expandierbare Zeilen mit Margin und Bot-Name

### Entfernt
- **Aggressives Risikoprofil (Edge Indicator)**: 15m-Modus entfernt — Simulation ueber 30 Tage zeigte 27% Winrate und -7.27% PnL. Nur noch Standard (1h) und Konservativ (4h) verfuegbar

### Verbessert
- **BotBuilder Empfehlung**: Zeigt jetzt empfohlenen Timeframe (4h) UND Zeitplan-Intervall (240min) an

---

## [4.6.1] - 2026-03-26

### Behoben
- **BingX Fee-Tracking (kritisch)**: Fees wurden als $0 gemeldet weil (1) `close_order_id` nie auf dem TradeRecord gespeichert wurde und (2) der Fallback ueber Fill-History nur Dual-Side-Mode (`positionSide=LONG/SHORT`) erkannte — BingX VST (Demo) nutzt One-Way-Mode. Fix: Close-Order-ID wird jetzt beim Strategy-Exit und bei externen Closes persistiert, und die Close-Fill-Erkennung unterstuetzt auch `reduceOnly` und `profit`-Felder
- **Close-Order-ID bei Strategy-Exit**: `close_position()` gab bereits eine `order_id` zurueck, aber der Position Monitor speicherte sie nicht auf dem Trade. Betrifft alle Exchanges

---

## [4.6.0] - 2026-03-26 — LLM-Integration entfernt

### Entfernt
- **LLM-Provider komplett entfernt**: 7 Provider (Groq, Gemini, OpenAI, Anthropic, DeepSeek, Mistral, xAI, Perplexity) aus `src/ai/` geloescht. Code archiviert unter Git-Tag `llm-archive-v4.5`
- **LLM-Strategien entfernt**: `llm_signal` (KI-Companion) und `degen` (Arena-Strategie) aus Strategy-Registry entfernt. Kein Bot nutzte diese Strategien
- **LLM-API-Endpunkte entfernt**: `/config/llm-connections` CRUD und Test-Endpunkte entfernt
- **LLM-Datenbank-Modell entfernt**: `LLMConnection` Tabelle wird nicht mehr von der App referenziert
- **Settings LLM-Keys Tab entfernt**: Der gesamte "LLM-Schluessel"-Tab in den Einstellungen entfernt
- **Bot Builder LLM-Optionen entfernt**: Provider/Modell-Auswahl, Custom Prompt und Temperature-Slider entfernt
- **LLM-Metriken entfernt**: Provider, Modell, Konfidenz, Tokens, Reasoning-Anzeige aus Bot-Karten und Statistiken entfernt
- **LLM-Tests entfernt**: ~600 Zeilen Provider- und Strategy-Tests, `tests/unit/ai/` komplett geloescht

### Hinweis
- Bestehende `llm_connections`-Tabelle in der Datenbank bleibt erhalten (war leer, 0 Eintraege)
- Historische Trade-Records mit LLM-Metriken in `metrics_snapshot` bleiben unberuehrt
- Verbleibende Strategien: Edge Indicator, Contrarian Pulse, Liquidation Hunter, Sentiment Surfer

---

## [4.5.0] - 2026-03-25 — UI Overhaul

### Entfernt
- **BotDetail-Seite komplett entfernt**: Die Unterseite die beim Klick auf einen Bot-Namen erschien wurde entfernt — alle Infos (Trades, Positionen, Config) sind bereits auf Dashboard, Portfolio und Bots-Seite verfuegbar. Bot-Name ist nicht mehr klickbar
- **BotDetail Config-Panel**: Konfigurationsanzeige (Strategie, Hebel, TP/SL etc.) entfernt — Infos sind ueber Bot-Edit erreichbar, Panel zeigte bei fehlenden Werten "null" an

### Geaendert
- **Stop-Button 2-Stufen-Sicherung**: Stop-Button erfordert jetzt 2 Klicks — erster Klick zeigt "Wirklich stoppen?" (3s Timeout), zweiter Klick stoppt den Bot. Gilt fuer Bots-Seite und BotDetail-Seite
- **Dashboard: Open Positions statt Letzte Trades**: Dashboard-Hauptseite zeigt jetzt offene Positionen (aus Portfolio-API) statt geschlossene Trades — relevantere Live-Uebersicht
- **Historie-Button sichtbarer**: Button in Bot-Cards jetzt mit Farbe (Primary), Border und Label-Text statt nur grauem Icon

### Geaendert (UX)
- **3-Punkte-Menue Desktop vs Mobil**: Desktop zeigt jetzt ein kompaktes Dropdown-Menue direkt am Button. Mobil bleibt das Bottom-Sheet wie gehabt
- **Trade-Historie Modal groesser auf Desktop**: `lg:max-h-[90vh]` und mehr Margin — kein vertikales Scrollen mehr bei normaler Trade-Anzahl

### Hinzugefuegt
- **i18n Keys**: `bots.confirmStop` fuer DE ("Wirklich stoppen?") und EN ("Confirm Stop?")

---

## [4.4.1] - 2026-03-25

### Behoben
- **Hyperliquid aktueller Preis in Portfolio**: `get_open_positions()` setzte `current_price=0.0` statt den tatsaechlichen Marktpreis abzufragen. Fix: Mid-Prices werden jetzt per Batch-API-Call (`all_mids`) geholt — ein einziger Request fuer alle offenen Positionen

---

## [4.4.0] - 2026-03-25 — Full Audit Fixes

### Sicherheit
- **npm Sicherheitsluecken behoben**: 8 HIGH-Severity Schwachstellen in Frontend-Abhaengigkeiten behoben (axios, rollup, undici, h3, flatted, socket.io-parser, hono) via `npm audit fix`
- **Alertmanager externe Receiver**: Discord/Telegram Webhook-Templates fuer kritische Alerts hinzugefuegt — Benachrichtigung auch bei App-Ausfall moeglich
- **Nginx Reverse Proxy Config**: `deploy/nginx.conf` ins Repo aufgenommen — reproduzierbare Disaster Recovery
- **Off-Host Backup Script**: `deploy/backup-offhost.sh` fuer S3/DO-Spaces Backup mit Verschluesselung und Retention
- **.env.example erweitert**: `BEHIND_PROXY` und `ENVIRONMENT` Produktions-Settings dokumentiert
- **Error Messages bilingual**: `src/errors.py` enthaelt jetzt alle Fehlermeldungen auf Deutsch UND Englisch (_EN Varianten)

### Behoben (Kritisch)
- **Position Monitor Shared State** (C1): Module-Level `_trailing_stop_backoff`, `_trailing_stop_lock` und `_glitch_counter` waren globale Variablen die von ALLEN Bots geteilt wurden — Glitch-Counter kollidierten, Lock blockierte alle Bots. Jetzt per BotWorker-Instanz isoliert via `_init_monitor_state()`
- **Trade Close Session-Sicherheit** (C2): `_close_and_record_trade()` laedt den TradeRecord jetzt in einer eigenen DB-Session statt das evtl. detachte Objekt des Callers zu modifizieren — verhindert stille Datenverluste bei PnL-Persistierung
- **Trade Execution Atomizitaet** (C3): TradeRecord-Erstellung und PendingTrade-Aufloesung laufen jetzt in der GLEICHEN DB-Session — bei Crash zwischen Order und DB-Eintrag bleibt kein Ghost-State zurueck
- **DB Session Retry bei Pool-Exhaustion** (M4): `get_session()` versucht jetzt bis zu 3x mit exponentiellem Backoff eine DB-Session zu acquirieren — verhindert Cascading Failures unter Last
- **WebSocket Broadcast Tasks**: Fire-and-forget `asyncio.create_task()` Aufrufe haben jetzt `done_callback` — Tasks werden nicht mehr vom GC entfernt und Fehler werden nicht mehr verschluckt

### Behoben (UX/Accessibility)
- **Confirmation Modals statt window.confirm()**: Bot-Loeschen und Position-Schliessen nutzen jetzt styled ConfirmModal mit Varianten (danger/warning), ESC-Handler, Focus-Trap und Loading-State
- **Loading-State fuer Start/Stop Buttons**: BotDetail Start/Stop Buttons zeigen Spinner und sind waehrend der Aktion deaktiviert — verhindert Doppelklicks
- **Dashboard Trades Sync Debounce**: `/trades/sync` wird nur noch einmal pro Browser-Session aufgerufen statt bei jedem Dashboard-Load
- **WCAG Kontrast**: `text-gray-500` Labels auf dunklen Hintergruenden durch `text-gray-400` ersetzt — erfuellt 4.5:1 Kontrastverhältnis
- **Keyboard Navigation FilterDropdown**: Pfeiltasten, Home/End, Enter/Space und Escape unterstuetzt — visuelles Highlighting
- **Focus-Visible Indikatoren**: Globale sichtbare Fokusrahmen (emerald) fuer alle interaktiven Elemente — WCAG 2.4.7
- **Focus Trap Hook**: `useFocusTrap.ts` fuer modale Dialoge — Tastaturfokus bleibt im Container

### Geaendert
- **Strategy Display Konstante zentralisiert**: `STRATEGY_DISPLAY` aus 4 Dateien in `src/constants/strategies.ts` extrahiert
- **Docker Compose Memory-Limits**: Prometheus (256M), Alertmanager (64M), Grafana (256M) begrenzt — verhindert OOM auf dem 2GB VPS

---

## [4.3.0] - 2026-03-25

### Hinzugefuegt
- **API Glitch Tracking & Alerting**: Position Monitor erkennt und meldet jetzt API-Stoerungen (z.B. wiederholte Timeouts, fehlerhafte Responses) mit automatischem Alerting
- **Weex V3 API Migration**: Trading-Endpunkte auf Weex V3 API migriert — bessere Stabilitaet und Zukunftssicherheit
- **Admin Bypass**: Admin-User umgehen alle Affiliate- und Referral-Gates (inkl. Bot-Worker-Level HL Gates) — vereinfacht Testing und Support
- **Exchange Feature Matrix**: Aktualisiert mit korrekten Margin-Modi und Feature-Flags fuer alle 5 Exchanges
- **Symbol-Validierung beim Bot-Start**: Trading Pairs werden auch in `bot_worker.initialize()` gegen die Exchange geprueft — verhindert Fehler wenn Symbole nach Bot-Erstellung delistet werden

### Behoben
- **Bot Builder Intervall-Feld**: Intervall-Eingabe zeigte automatisch "5" an und liess sich nicht leeren. Fix: Feld startet leer, Minimum wird erst bei Absenden validiert
- **Mobile Bot-Menue**: 3-Punkte-Menue auf Bot-Karten war auf Mobilgeraeten nicht klickbar — Dropdown wurde von anderen Elementen verdeckt. Fix: Z-Index erhoeht (z-50), Touch-Target vergroessert (44px+), overflow-hidden entfernt, Karte wird bei offenem Menue angehoben
- **HL Unrealized PnL**: Wird jetzt korrekt aus Positions-Daten gelesen statt separat abgefragt. Circuit Breaker hinzugefuegt + Weex Symbol-Referenz korrigiert
- **HL Funding Rate**: Korrekte Berechnung nach Weex V3 Migration
- **HL Balance Response**: Defensiver Type-Check verhindert Crashes bei unerwartetem Response-Format
- **BingX Balance Response**: Wird jetzt korrekt als Liste geparst
- **PNL Arrow Wrapping**: PNL-Pfeil und Wert bleiben jetzt in einer Zeile (kein Umbruch mehr)
- **NEUTRAL Signals**: Werden jetzt abgelehnt statt weitergeleitet. Side-Mismatch im Position Monitor behoben
- **Position Close Retry**: Bestaetigung vor dem Markieren von Positionen als geschlossen hinzugefuegt — verhindert vorzeitiges Schliessen
- **Symbol-Normalisierung**: Alle Market-Data-API-Aufrufe normalisieren Symbole jetzt auf Binance-Format — konsistente Daten ueber alle Exchanges
- **Hyperliquid float_to_wire Rounding (kritisch)**: Trade-Size wurde nicht auf `szDecimals` gerundet bevor sie an die HL SDK uebergeben wurde. Jedes Signal generierte den Fehler `float_to_wire causes rounding` — kein einziger Trade konnte ausgefuehrt werden. Fix: Size wird jetzt via `_get_sz_decimals()` auf die korrekte Dezimalstellenzahl gerundet (z.B. BTC=5, ETH=4, AAVE=2). Betrifft alle drei Pfade: Open, Close und TP/SL Fallback
- **Hyperliquid close_position Rounding**: Auch `close_position()` und der TP/SL-Fallback-Pfad in `set_position_tpsl()` rundeten die Size nicht — haetten beim Schliessen den gleichen `float_to_wire`-Fehler ausgeloest
- **Symbol-Validierung AttributeError**: `bot_worker.py` referenzierte `self._trading_pairs` (existiert nicht) — Symbol-Validierung wurde bei jedem Bot-Start uebersprungen. Fix: Nutzt jetzt `_safe_json_loads(self._config.trading_pairs)`
- **Hyperliquid Event Loop Blocking**: Alle HL SDK-Aufrufe (sync `requests`) blockierten den gesamten Event Loop (100-500ms pro Call). Alle anderen Bots, WebSocket-Verbindungen und API-Handler waren waehrenddessen eingefroren. Fix: `_cb_call()` nutzt jetzt `run_in_executor()`, `get_ticker()` laeuft jetzt durch den Circuit Breaker
- **Hyperliquid Price Tick Size**: `_get_tick_size()` las faelschlicherweise `szDecimals` (Size-Precision) statt der tatsaechlichen Preis-Precision. TP/SL Trigger-Preise konnten falsch gerundet sein. Fix: Nutzt jetzt `meta_and_asset_ctxs` mit 5 signifikanten Stellen (HL Standard)
- **Builder Fee Revenue 10x zu niedrig**: `calculate_builder_fee()` dividierte durch 1.000.000 statt korrekt 100.000. Revenue-Dashboard zeigte 10x weniger Builder-Fee-Einnahmen als tatsaechlich verdient
- **Funding Fee Richtung**: `get_funding_fees()` nutzte `abs()` — empfangene Funding-Zahlungen wurden als Kosten gezaehlt statt abgezogen. Fee-Tracking war immer zu hoch. Betrifft HL und BingX
- **BingX margin_mode Parameter (kritisch)**: `place_market_order()` und `close_position()` fehlte der `margin_mode` Parameter — jeder Aufruf haette einen TypeError ausgeloest. Fix: Parameter hinzugefuegt, doppelten `set_leverage`-Aufruf in `place_market_order` entfernt (wurde bereits vom Trade Executor gesetzt)
- **BingX VST Demo-Modus (kritisch — Ludwig)**: BingX VST API unterstuetzt `set_leverage` und `set_margin_type` nicht (Error 109400). Der Trade Executor behandelte dies als Hard-Block — kein einziger Demo-Trade konnte ausgefuehrt werden. Fix: VST-spezifische Fehler werden erkannt und uebersprungen, Bot tradet mit Standard-Einstellungen
- **BingX Quantity Precision**: Rohe Float-Werte (z.B. `0.03400000001`) wurden als Quantity an die BingX API gesendet — konnte zu Error 100400 fuehren. Fix: `_round_quantity()` rundet auf 4 Dezimalstellen
- **HL Builder Fee fuer Admins**: Admin-Accounts uebersprungen jetzt die Builder Fee komplett — kein Approval noetig, kein Builder-Parameter in der Order. Verhindert "Builder fee has not been approved" Fehler fuer Admin-Wallets
- **BingX Content-Type Header (kritisch)**: Authentifizierte Requests sendeten `Content-Type: application/json` mit leerem Body — BingX VST API lehnte alle Orders mit Error 109400 ab. Live-API ignorierte den Header. Root Cause fuer Ludwigs Bot-Probleme
- **BingX Trailing Stop Parameter**: `activationPrice`/`callbackRate` durch korrekte `price`/`priceRate` ersetzt. `priceRate` wird jetzt als Dezimalwert gesendet (1.5% → 0.015)
- **BingX Funding Rate predicted_rate**: `estimatedSettlePrice` (ein Preis) wurde faelschlicherweise als Funding-Rate gemappt. Fix: Feld auf `null` gesetzt
- **Mobile Bot-Menue Bottom Sheet**: Dropdown-Menue wurde durch ein Bottom Sheet ersetzt — gleiche Slide-Up-Animation wie das "Mehr"-Menue, keine Positionierungsprobleme mehr
- **i18n Portfolio Keys**: `portfolio.total` und `portfolio.margin` fehlten — englische Version zeigte "Gesamt" statt "Total" im Donut-Chart
- **Bitunix margin_mode Parameter (kritisch)**: `set_leverage`, `place_market_order` und `close_position` fehlte der `margin_mode` Parameter — jeder Trade und jedes Schliessen crashte mit TypeError. Kein Bitunix-Bot konnte jemals traden
- **Bitunix Quantity Precision**: Rohe Float-Werte als qty gesendet — jetzt auf 4 Dezimalstellen gerundet
- **Weex doppeltes set_leverage**: `place_market_order` rief intern nochmal `set_leverage` auf — ueberfluessig und konnte margin_mode zuruecksetzen. Entfernt
- **Weex Quantity Precision**: Rohe Float-Werte als quantity gesendet — jetzt auf 4 Dezimalstellen gerundet
- **Weex Funding Fees abs()**: `get_funding_fees()` nutzte `abs()` — empfangene Funding-Zahlungen als Kosten gezaehlt

### Geaendert
- **Hyperliquid Onboarding vereinfacht**: Affiliate-Verifizierung und Builder-Fee-Genehmigung sind jetzt direkt in den Exchange-Einstellungen integriert statt in einem separaten Wizard beim Bot-Start. Einmaliger Einrichtungsprozess — kein Wizard-Popup mehr beim Starten von HL-Bots
- **Zeitzonen-Support im Bot Builder**: Uhrzeiten werden jetzt in der lokalen Zeitzone des Users angezeigt und eingegeben. Automatische Erkennung via Browser. Keine "(UTC)"-Anzeigen mehr — Konvertierung erfolgt automatisch im Hintergrund

### Entfernt
- **Trade Rotation entfernt**: Schedule-Typ "Nur Trade-Rotation" aus Bot Builder und Backend entfernt. Eigenes Intervall deckt den gleichen Use Case ab
- **Market Sessions entfernt**: Schedule-Typ "Markt-Sessions (1h, 8h, 14h, 21h UTC)" aus Bot Builder und Backend entfernt. Feste Uhrzeit (Eigene Uhrzeiten) deckt den gleichen Use Case ab
- **Backtest-Modul komplett entfernt**: Frontend-Seite, Backend-Engine (8 Dateien), API-Endpunkte, Tests, Skripte und Anleitungen. Code bleibt in der Git-History erhalten. Entfernt ~13.750 Zeilen Code

---

## [4.2.1] - 2026-03-19

### Behoben
- **Access Token Lifetime**: Von 24h auf 4h reduziert — besserer Kompromiss zwischen Security (kurze Token bei XSS-Leak) und UX (proaktiver Refresh erneuert automatisch)
- **Refresh-Endpoint Tests**: 8 bestehende Tests auf neues `response`-Parameter-Pattern migriert, 2 neue Regressionstests fuer Cookie-only-Refresh und fehlenden-Token-Fall hinzugefuegt
- **formatSize Edge-Case**: Gibt jetzt "—" zurueck bei size <= 0 statt "$0" oder "0.0000 BTC"
- **Symbol-Validierung beim Bot-Start**: Trading Pairs werden jetzt auch in `bot_worker.initialize()` gegen die Exchange geprueft — verhindert Fehler wenn Symbole nach Bot-Erstellung delistet werden

---

## [4.2.0] - 2026-03-19

### Hinzugefuegt
- **Size Toggle**: Klick auf Size-Wert in Trade/Position-Karten wechselt global zwischen Token-Size (z.B. "13.0600 ETH") und USDT-Wert (z.B. "$28.5k"). Persistiert in localStorage. Betrifft MobilePositionCard, MobileTradeCard, Portfolio-Tabelle und Trades-Tabelle
- **Symbol-Validierung**: Bei Bot-Erstellung und -Update werden Trading Pairs gegen die Exchange-API validiert. Ungueltige Symbole (z.B. SPXUSDT auf Bitget) werden mit klarer Fehlermeldung abgelehnt
- **Proaktiver Token-Refresh**: Access Token wird 5 Minuten vor Ablauf automatisch im Hintergrund erneuert. Bei Tab-Wechsel (visibilitychange) wird ebenfalls geprueft und refreshed

### Behoben
- **Session-Expiry (kritisch)**: Refresh-Token-Mechanismus war seit Einfuehrung defekt — Frontend sendete leeren Body `{}` an `/api/auth/refresh`, was Pydantic mit 422 ablehnte. Der httpOnly Cookie wurde nie gelesen. User mussten sich nach 60 Minuten neu einloggen. Fix: RefreshRequest.refresh_token optional gemacht, Frontend sendet keinen Body mehr
- **Pie Chart Focus-Rahmen**: Kein weisser Rahmen mehr beim Klicken auf Donut-Charts (Portfolio + Dashboard). CSS-Regel entfernt Focus-Outline auf allen Recharts SVG-Elementen
- **Pie Chart Tooltip**: Tooltip-Text im Dark Mode war schwarz/unlesbar. Fix: itemStyle und labelStyle mit korrekter Farbe fuer Dark Mode
- **Mobile Card Layout**: PnL und Aufklapp-Button waren nicht mehr in einer Zeile. Fix: Ueberfluessige Labels (DATE, SIZE, PnL) aus Summary-Zeile entfernt, Gap reduziert — alle Elemente passen jetzt in eine Zeile

### Geaendert
- **Access Token Laufzeit**: Von 1 Stunde auf 24 Stunden erhoeht. Proaktiver Refresh erneuert automatisch, Refresh-Token (30 Tage) dient als Sicherheitsnetz
- **Sentiment Surfer Schedule**: Von market_sessions (4x taeglich) auf interval (alle 60 Minuten) umgestellt — Bot analysiert jetzt regelmaessig

### Analyse
- **TradFi/HIP-3 Recherche** (Issue #113): Hyperliquid TradFi-Perps und HIP-3 evaluiert. Ergebnis: Nicht priorisieren — Edge Indicator ist nicht fuer TradFi optimiert (Gaps, geringe Liquiditaet, Isolated Margin only). Builder-Fee und Referral funktionieren aber auf HIP-3

---

## [4.1.1] - 2026-03-17

### Behoben
- **Builder Fee Berechnung**: Fee-Rate war 10x zu hoch (0.10% statt 0.01% bei Konfiguration HL_BUILDER_FEE=10). Korrigiert auf korrekte tenths-of-basis-point Berechnung
- **Referral-Code Matching**: Referral-Verifizierung prueft jetzt ob der User den konfigurierten Affiliate-Link genutzt hat (nicht irgendeinen beliebigen Referral)
- **Wallet-Wechsel Reset**: Bei Aenderung der Hyperliquid Wallet-Adresse werden builder_fee_approved und referral_verified automatisch zurueckgesetzt
- **Trust-Frontend Fallback entfernt**: Builder Fee Approval vertraut nicht mehr blind dem Frontend, sondern verifiziert immer on-chain mit Retry

### Geaendert
- **Builder Fee Approval Flow**: Neuer 4-Schritt-Wizard (Affiliate Link → Wallet verbinden → Builder Fee signieren → Fertig). Referral-Verifizierung ist jetzt direkt in den Bot-Start-Flow integriert statt nur auf der Settings-Seite
- Referral-Gate prueft im BotWorker ebenfalls gegen den konfigurierten Referral-Code
- **Portfolio Pie-Chart**: Hover/Klick zeigt Exchange-Name + Funds in der Mitte statt haesslicher Randmarkierung. Ohne Auswahl wird Gesamtbetrag angezeigt
- **Performance-Seite**: Trailing-Stop-Sektion entfernt — offene Positionen gehoeren ins Portfolio, Performance zeigt nur realisierte Ergebnisse
- **Steuerbericht**: Header "Monatliche Aufschluesselung" optisch ueberarbeitet (Desktop + Mobil) — konsistent mit dem Rest der App

### Rebranding
- **"Trading Bot" → "Edge Bots by Trading Department"**: Neuer Name und Logo in Sidebar, Mobile Header, Login-Seite, PWA Manifest, Browser-Tab, WalletConnect und Service Worker

### Aktualisierte Dokumentation
- Anleitung "Hyperliquid Builder Fee genehmigen" komplett ueberarbeitet: 5-Schritt-Prozess mit Affiliate Link, Wallet-Wechsel-Hinweis, Rabby Wallet Empfehlung (DE + EN)
- Neue i18n-Keys fuer Referral-Flow (DE + EN)

---

## [4.1.0] - 2026-03-16

### Entfernt
- **Presets-Feature komplett entfernt**: Preset-Seite, API-Endpunkte, DB-Model, Preset-Anwendung auf Bots. Bot-Duplizierung deckt den gleichen Use Case ab
- DB-Migration `011_remove_presets.py` entfernt `config_presets` Tabelle und FK-Spalten
- Preset-bezogene Tests, Anleitungen (DE+EN) und i18n-Keys entfernt

### Hinzugefuegt
- **Bitget Futures Warnung**: Hinweis im Bot Builder und in den Anleitungen, dass Bitget Futures fuer neue deutsche Kunden voraussichtlich bis 2027 nicht verfuegbar sind (bestehende Konten nicht betroffen)

### Geaendert
- **Strategien-Dokumentation aktualisiert**: Nur noch 3 verfuegbare Strategien (Edge Indicator, Liquidation Hunter, Sentiment Surfer) hervorgehoben. Versteckte Strategien (Contrarian Pulse, LLM Signal, Degen) als "derzeit nicht verfuegbar" gekennzeichnet
- LLM-Provider-Doku mit Admin-only Hinweis versehen
- Backtest-Ergebnisse und Strategie-Dokumentation mit Verfuegbarkeitshinweisen ergaenzt

---

## [4.0.5] - 2026-03-13

### Sicherheit (Security Hardening)
- **Session-Invalidierung bei Logout**: Logout deaktiviert die Session in der Datenbank (`is_active=false`), nicht nur den Cookie. Refresh mit invalidierter Session wird abgelehnt
- **Session-Tracking bei Login**: Login und 2FA-Verify erstellen nun einen `UserSession`-Eintrag in der DB fuer explizite Revocation
- **Refresh Token Rotation mit DB-Update**: Bei Token-Refresh wird der Session-Hash in der DB rotiert und `last_activity` aktualisiert
- **Security Headers gehaertet**:
  - CSP: `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`
  - Neu: `Permissions-Policy` (kamera, mikrofon, geolocation etc. deaktiviert)
  - Neu: `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`
  - HSTS: `max-age` auf 2 Jahre erhoet + `preload` Flag
- **Refresh Rate Limit verschaerft**: Von 10/min auf 5/min reduziert

---

## [4.0.4] - 2026-03-13

### Sicherheit (Security Fixes)
- **httpOnly Cookie fuer Refresh Tokens**: Refresh-Tokens werden nicht mehr im localStorage gespeichert (XSS-anfaellig), sondern als httpOnly, secure, samesite=lax Cookie gesetzt. Nur der Access-Token bleibt im localStorage (kurzlebig, 30min). Cookie ist auf `/api/auth` Pfad beschraenkt
  - Login, 2FA-Verify, Refresh und Change-Password setzen den Cookie serverseitig
  - Neuer `/api/auth/logout` Endpoint loescht den Cookie
  - Frontend sendet `withCredentials: true` — Refresh-Request schickt Cookie automatisch
  - Backward-kompatibel: Refresh-Endpoint akzeptiert noch Body-Parameter (fuer bestehende Clients)
- **SSRF-Schutz fuer Webhook-URLs**: Discord-Webhook-URLs werden nun gegen eine Allowlist validiert (nur `discord.com`, `discordapp.com`, `hooks.slack.com`, `api.telegram.org`). Verhindert Server-Side Request Forgery durch manipulierte URLs
- **Rate Limit auf `/api/health`**: Health-Check-Endpoint hat nun ein Rate Limit von 30/min, um DDoS-Vektoren zu schliessen
- **Hyperliquid Circuit Breaker**: Alle API-Aufrufe zum Hyperliquid-SDK laufen nun durch einen Circuit Breaker (5 Fehler → 60s Pause), konsistent mit den anderen Exchanges

### Behoben (Bug Fixes)
- **N+1 Query in Portfolio Positions**: BotConfig-Abfragen fuer offene Positionen werden nun per Batch geladen statt einzeln pro Trade (Performance-Fix)
- **Symbol Lock Race Condition**: `_get_symbol_lock()` nutzt nun `setdefault()` statt manuelles if/set — verhindert theoretische Doppel-Lock-Erstellung bei gleichzeitigem Zugriff
- **Toast Overflow**: Toast-Container hat nun `max-height` und `overflow-y-auto` — bei vielen gleichzeitigen Toasts scrollbar statt ueber den Bildschirmrand hinaus
- **GettingStarted Tests**: Tests an die neue Tab-basierte Seitenstruktur angepasst (vorher wurde erwartet, dass alle Sektionen gleichzeitig sichtbar sind)

### Hinzugefuegt (UX)
- **Portfolio Expand-Row**: Positions-Tabelle hat nun das gleiche klickbare Expand-Detail-Pattern wie Trades und Dashboard (Size, Entry/Current Price, Leverage, Trailing Stop, Bot-Name, Margin)
- **Farbenblinden-freundliche PnL-Indikatoren**: Alle PnL-Werte zeigen nun ▲/▼ Symbole zusaetzlich zur Farbe (nicht nur Farbe fuer Profit/Loss)
- **HTML `lang`-Attribut**: Das `<html lang>` Attribut wird automatisch mit der aktuellen Sprache synchronisiert (Accessibility)

---

## [4.0.3] - 2026-03-13

### Hinzugefuegt
- **Responsive Tabellen-Design (Industrie-Standard)** — Alle 7 Tabellen im Frontend reagieren jetzt dynamisch auf die Bildschirmgroesse:
  - **Column Priority Hiding**: Spalten mit niedriger Prioritaet werden auf kleineren Bildschirmen automatisch ausgeblendet (Tailwind responsive classes: `hidden lg:table-cell`, `hidden xl:table-cell`, `hidden 2xl:table-cell`)
  - **Row-Expand (Trades & Dashboard)**: Klick auf eine Zeile oeffnet ein Detail-Panel mit allen versteckten Informationen — kein Informationsverlust
  - **Betroffene Seiten**: Trades (12→6 Spalten auf Tablet), Dashboard Recent Trades, Portfolio Positions, BotDetail, BotPerformance, Backtest Trade Log, Backtest History
  - **Breakpoint-Strategie**: Smartphone (<1024px) 4-6 Spalten, 13" Laptop (1024-1535px) 6-8 Spalten, Desktop (≥1536px) alle Spalten
  - **Light-Mode Support**: Expand-Rows haben angepasste Farben fuer den Light-Mode
  - Ansatz basiert auf Recherche der groessten Trading-Plattformen (Binance, Bybit, Coinbase, Stripe) — alle nutzen Column Hiding + Detail-Expand als Standard

### Geaendert
- **i18n**: Neue Uebersetzungsschluessel `trades.exitTime` und `trades.exitReason` (DE/EN) fuer die Expand-Detail-Ansicht

---

## [4.0.2] - 2026-03-13

### Hinzugefuegt
- **Liquidation Hunter: 3-Schicht-Exit-System** — Automatische Exit-Strategie (`should_exit`) fuer den Liquidation Hunter:
  - **Schicht 1 — ATR Trailing Stop**: Schuetzt Gewinne mit aggressiven Defaults (Breakeven bei 1.0× ATR, Trail bei 1.5× ATR). Aktiviert sich sobald der Trade profitabel ist
  - **Schicht 2 — Thesen-Invalidierung**: Schliesst den Trade wenn L/S Ratio UND Sentiment sich normalisieren (Kaskaden-Potenzial aufgebraucht). Mit 30min Cooldown nach Entry
  - **Schicht 3 — Max. Haltezeit**: Schliesst nach X Stunden, aber NUR wenn der Trade im Gewinn ist. Im Verlust bleibt er offen (verhindert unnoetige Verluste)
  - **Risikoprofil-Auswahl** im Bot Builder: Konservativ (weite Stops, 48h Haltezeit), Standard (ausgewogen, 24h), Aggressiv (enge Stops, 12h, schnelle Gewinnmitnahme)
  - Greift nur wenn der User KEIN eigenes TP/SL gesetzt hat
- **StrategyRegistry: Hidden-Flag** — Strategien koennen mit `hidden=True` registriert werden. Sie bleiben fuer bestehende Bots nutzbar, werden aber nicht mehr im Bot Builder angezeigt

### Geaendert
- **Contrarian Pulse ausgeblendet** — Strategie aus dem Bot Builder entfernt wegen 70% Signal-Ueberlappung mit Liquidation Hunter (gleiche Datenquellen, schlechtere Exit-Logik). Kann jederzeit wieder aktiviert werden (siehe [#107](https://github.com/EzR3aL/Trading-Bot/issues/107))
- **LLM Signal + Degen ausgeblendet** — KI-Strategien aus dem Bot Builder entfernt, da sie LLM API-Keys erfordern die normale User nicht haben. Wieder aktivierbar (siehe [#108](https://github.com/EzR3aL/Trading-Bot/issues/108))
- **LLM Keys Tab nur fuer Admins** — Der LLM-Schluessel-Tab in den Einstellungen ist nur noch fuer Admins sichtbar, nicht mehr fuer normale User

### Behoben
- **Leverage-Default immer 1x** — Wenn der User keinen Hebel konfiguriert, wird jetzt explizit 1x gesetzt. Vorher wurde der Fehler bei `set_leverage` still ignoriert und der zuletzt auf der Exchange gesetzte Leverage (z.B. 10x) weiterverwendet. Betrifft alle Exchanges (Bitget, Weex, BingX, Bitunix). Trade wird abgebrochen wenn Leverage nicht gesetzt werden kann
- **"Something went wrong" Fehler (removeChild)** — React-DOM-Crash wenn mehrere API-Requests gleichzeitig 401 zurueckgeben (z.B. bei Session-Ablauf). `handleSessionExpiry()` wurde mehrfach aufgerufen und manipulierte das DOM unkontrolliert. Fix: Guard gegen Mehrfachaufruf + ErrorBoundary erholt sich automatisch von DOM-Fehlern (max. 3 Retries)
- **Budget-Warnung bei offenen Positionen** — "Insufficient balance"-Warnung wurde faelschlicherweise angezeigt, obwohl Trades bereits ausgefuehrt waren. Die Pruefung verglich das gesamte Bot-Budget mit dem freien Guthaben, ohne die bereits gebundene Margin offener Positionen zu beruecksichtigen. Fix: Die Margin offener Trades wird nun zum verfuegbaren Guthaben hinzugerechnet
- **Frontend-Fehlermeldungen verbessert** — Umfassendes Audit und Fixes:
  - `getApiErrorMessage` verarbeitet jetzt FastAPI 422-Validierungsfehler korrekt (Array-Format mit Feldnamen)
  - Fehlender i18n-Key `common.loadError` hinzugefuegt (DE + EN)
  - Fehlender `.catch()` bei Strategy-Loading im BotBuilder ergaenzt
  - 5 hardcodierte `'Failed to load data'` Strings durch `t('common.loadError')` ersetzt
  - Settings: Alle `catch`-Bloecke nutzen jetzt `getApiErrorMessage()` statt generischem `t('common.error')`
  - Session-Ablauf-Meldung uebersetzt via `common.sessionExpired`
- **Automatische Spracherkennung** — Browser-/PC-Sprache wird beim ersten Besuch erkannt (DE/EN). Manuell gewaehlt Sprache wird in localStorage gespeichert und hat Vorrang
- **Hardcodierte Strings uebersetzt** — Backtest-Tabellen "Symbol", PnlChart "Netto", Settings Admin-UID-Tabelle (User/Exchange/Status/Aktion), BotPerformance "Distance" — alle durch i18n-Keys ersetzt
- **Trailing Stop von Trades nach Portfolio verschoben** — Trailing-Stop-Anzeige aus der Trade-Uebersicht entfernt und stattdessen in der Portfolio-Seite unter "Offene Positionen" eingebaut. Zeigt pro Position: Trailing-Stop-Preis, Distanz in % und Schutz-Icon. Backend berechnet Trailing-Stop live via ATR fuer jede offene Position

---

## [4.0.1] - 2026-03-12

### Hinzugefuegt
- **Anleitungen mit Navigation** — Seite "Erste Schritte" komplett ueberarbeitet: Sidebar-Navigation (Desktop) bzw. horizontale Tabs (Mobile) mit 6 Sektionen (Schnellstart, Schritt-fuer-Schritt, Strategien, Risiko & Konfig, Exchanges, Sicherheit). Prerequisite-Banner bleibt immer oben sichtbar
- **Bild kopieren fuer alle Trades** — In der Bot-Detailansicht kann nun jeder einzelne Trade (nicht nur der letzte) als kompaktes Bild in die Zwischenablage kopiert werden. Button im Trade-Detail-Modal. Affiliate-Link wird bei allen Trades im Bild angezeigt

### Geaendert
- **Affiliate-Link Layout** — Label und URL werden nun untereinander statt nebeneinander angezeigt fuer bessere Lesbarkeit in den kopierten Trade-Bildern

### Behoben
- **2FA nur unter API-Schluessel** — 2FA-Bereich wird nur noch im Tab "API-Schluessel" angezeigt, nicht mehr auf allen Einstellungs-Tabs
- **Letzter Trade Karte: Layout korrigiert** — Sichtbare Karte auf der Bots-Seite zeigt wieder das originale breite 4-Spalten-Layout. Kompaktes Design wird nur noch fuer die Bild-Kopie (Bild kopieren) verwendet, unsichtbar gerendert

---

## [4.0.0] - 2026-03-11

### Hinzugefuegt
- **2FA (TOTP)** — Authenticator-App Support mit QR-Code, 10 Backup-Codes (bcrypt), Temp-Token Login-Flow
- **Passwort-Reset** — Forgot-Password mit sicherem Token (15min Ablauf), Rate-Limited, invalidiert alle Sessions
- **Bot Crash Recovery** — PendingTrade-Tabelle trackt laufende Orders, Orphaned Detection beim Startup, manuelles Resolve
- **Notification History** — NotificationLog-Tabelle mit Delivery-Status, GET /api/notifications mit Filtern
- **Session Management** — Aktive Sessions anzeigen/widerrufen, Logout-All, Device-Tracking
- **Config Change Audit Trail** — Alle Config-Aenderungen (Bots, Presets, Exchanges) mit Old/New-Diffs geloggt
- **Backup Restore Testing** — scripts/test-backup-restore.sh fuer wöchentliche Backup-Verifikation
- **WebSocket Auto-Reconnect** — Exponential Backoff (1s→30s), Tab-Visibility Reconnect, Status-Banner

### Geaendert
- **Graceful Shutdown** — Wartet auf laufende Trades (max 20s), loggt offene Positionen, Fallback auf Hard-Stop
- **Rate Limits** — Alle mutierenden Endpoints konsistent limitiert (fehlende ergaenzt)
- **Error Messages** — Alle Inline-Strings in src/errors.py zentralisiert (12 neue Konstanten)
- **Docker Hardening** — Health Checks + Resource Limits fuer Prometheus, AlertManager, Grafana

### Verbessert
- **Accessibility (WCAG 2.1 AA)** — ARIA-Labels, role="alert", Keyboard-Navigation, Form-Labels, Farbblind-Indikatoren

### Datenbank
- 6 neue Migrationen (006-011): TOTP-Spalten, Password-Reset, PendingTrades, NotificationLogs, ConfigChangeLogs, UserSessions

---

## [3.40.0] - 2026-03-11

### Geaendert
- **Budget: Absolute USDT-Betraege statt Prozent** — Per-Asset Balance-Feld zeigt nun verfuegbaren Betrag in USDT, Eingabe als exakter Betrag statt Prozent. Warnung wenn Betrag die verfuegbare Balance uebersteigt. Backend unterstuetzt `position_usdt` (neu) und `position_pct` (Legacy-Kompatibilitaet)
- **Bot-Karten: Budget-Anzeige vereinfacht** — Separate Allokation-Spalte entfernt, Budget als einzeilige USDT-Anzeige mit Prozent-Hinweis

### Hinzugefuegt
- **Skill: /feierabend** — End-of-Day Automation: Test, Commit, Changelog, Push, Deploy, Verify, Summary

---

## [3.39.4] - 2026-03-11

### Behoben
- **Security: .mcp.json in .gitignore** — Verhindert versehentliches Committen von DB-Credentials
- **Security: Version aus /api/health entfernt** — Kein Informationsleck mehr ueber Server-Version
- **Code-Qualitaet: bots.py Imports an Dateianfang verschoben** — asyncio/time Imports waren mitten in der Datei
- **Security: Postgres-Passwort rotiert** — Nach Credential-Leak in Git-History neues Passwort gesetzt

---

## [3.39.3] - 2026-03-11

### Behoben
- **Security: WebSocket Connection-Limits** — Max 5 Verbindungen pro User, 100 gesamt. Verhindert Resource-Exhaustion-Angriffe
- **Security: /api/status gibt keine Version/Features mehr preis** — Reduziert Informationsleck fuer Angreifer
- **Security: Audit-Log Path-Truncation** — Verhindert DB-Fehler bei extrem langen URLs (max 500 Zeichen)
- **Security: CLI Admin-Passwort-Validierung** — Gleiche Komplexitaetsanforderungen wie API (Gross/Klein/Zahl/Sonderzeichen)
- **API-Routing: /api/bots/budget-info** — Route vor /{bot_id} verschoben, verhindert 422-Fehler
- **Frontend-Test: client.test.ts** — `toHaveBeenCalledWith` auf `objectContaining` geaendert (timeout-Feld)

### Hinzugefuegt
- **Skills: Alembic Migrations** — Skill fuer DB-Migrationen mit Namenskonvention und Tabellen-Referenz
- **Skills: Deployment, Bot-Ops, Backtest-Runner** — Standardisierte Operations-Skills
- **Hooks: Pre-Deploy Check** — Warnt bei Push/Deploy mit uncommitteten Aenderungen
- **Hooks: CHANGELOG-Erinnerung** — Erinnert nach Code-Edits an CHANGELOG-Update
- **Plugins: code-simplifier** — Code-Cleanup nach Sessions
- **MCP: Playwright + PostgreSQL** — UI-Verifikation und DB-Abfragen

---

## [3.39.2] - 2026-03-11

### Hinzugefuegt
- **Kline/Zeitplan-Warnung im Bot Builder** — Zeigt ein Info-Banner wenn das Analyse-Intervall kuerzer ist als das Kline-Intervall (z.B. 15m Schedule + 4h Kline). Verhindert unnoetige Mehrfachanalysen derselben Kerze.

### Entfernt
- **"Position schliessen" Button aus 3-Dot-Menu** — Der Button wird bereits direkt in der Bot-Karte angezeigt wenn ein Trade offen ist

---

## [3.39.1] - 2026-03-11

### Behoben
- **Schriftfarbe vereinheitlicht** — Alle Labels und Ueberschriften verwenden jetzt einheitlich `text-gray-400` statt teils `text-gray-500` fuer bessere Lesbarkeit. Betrifft: Bots, BotPerformance, Portfolio, Settings, AppLayout
- **Horizontales Scrollen auf Desktop behoben** — `overflow-x-hidden` auf Main-Container, unnoetige `min-w-[640px]` und uebergrosse Paddings aus Tabellen entfernt
- **Trailing Stop Spalte zentriert** — War vorher `text-right` und dadurch leicht versetzt; jetzt `text-center` in allen Tabellen (Trades, BotDetail, Bots)

---

## [3.39.0] - 2026-03-09

### Hinzugefuegt
- **Risikoprofil-Auswahl fuer EdgeIndicator** — Im Bot Builder kann jetzt ein Risikoprofil gewaehlt werden (Konservativ / Standard / Aggressiv) statt 10+ Einzelparameter manuell zu konfigurieren.
  - **Konservativ:** Weniger Trades, weite Stops, 4h-Intervall (ADX 22, Momentum ±0.40, Trail 3.0 ATR)
  - **Standard:** Ausgewogene Defaults, 1h-Intervall (bisheriges Verhalten, keine Aenderung)
  - **Aggressiv:** Mehr Trades, enge Stops, 15m-Intervall (EMA 5/13, ADX 15, Momentum ±0.25, Trail 2.0 ATR)
  - Dropdown erscheint als erstes Element im Bot Builder (select-Typ)
  - Explizite User-Parameter ueberschreiben Profil-Werte (Profil = Ausgangsbasis, nicht Zwang)
  - Bestehende Bots ohne `risk_profile` nutzen automatisch "Standard" — kein Breaking Change

---

## [3.38.0] - 2026-03-09

### Hinzugefuegt
- **Nativer Bitget Trailing Stop** — Nach dem Trade-Entry wird automatisch ein nativer Trailing Stop (`track_plan`) auf der Boerse platziert. Der Stop laeuft direkt auf Bitget und schuetzt die Position auch wenn der Bot offline ist.
  - Neues Bitget API Endpoint: `place-plan-order` mit `planType="track_plan"`
  - `place_trailing_stop()` Methode im Bitget Client (und als optionale Methode im Base Client)
  - Trail-Distanz und Aktivierungspreis werden aus ATR-Parametern der EdgeIndicator-Strategie berechnet (`trailing_trail_atr` und `trailing_breakeven_atr`)
  - `TradeSignal` um `trailing_callback_pct` und `trailing_trigger_price` Felder erweitert
  - Trade Executor platziert den nativen Trailing Stop automatisch nach der Market Order
  - Bei Fehler: Software-Trailing-Stop bleibt als Backup aktiv (kein Trade-Abbruch)
  - Trailing-Info in Logs aufgenommen
  - **Auto-Placement fuer bestehende Positionen**: Der Position Monitor erkennt offene Positionen ohne nativen Trailing Stop und platziert ihn automatisch nach (innerhalb 1 Minute)
  - Neues DB-Feld `native_trailing_stop` auf `trade_records` verhindert doppelte Platzierung
  - Alembic-Migration 003 + SQLite-Inline-Migration

---

## [3.37.0] - 2026-03-09

### Hinzugefuegt
- **Trailing Stop im Dashboard** — Bot-Statistik-API (`/bots/{id}/statistics`) liefert jetzt Trailing-Stop-Daten fuer offene Trades (Preis, Distanz, Shield-Status)
- **Trailing Stop in Frontend** — Anzeige in Bot-Detail Trades-Tabelle, Dashboard Trade-History Modal, Bot-Performance Latest-Trade-Card und Trade-Detail-Modals mit ShieldCheck-Icon

### Geaendert
- `src/api/routers/bots_statistics.py` — `_compute_trailing_stop()` Import und Enrichment fuer offene Trades
- `frontend/src/pages/BotDetail.tsx` — Neue Spalte "Trailing Stop" in Trades-Tabelle
- `frontend/src/pages/Bots.tsx` — Trailing Stop in Trade-History-Tabelle und Trade-Detail-Modal
- `frontend/src/pages/BotPerformance.tsx` — Open-Trade Trailing-Stop-Card und Trade-Detail-Modal

---

## [3.36.0] - 2026-03-09

### Hinzugefuegt
- **Exchange-Konstanten zentralisiert** — `EXCHANGE_NAMES`, `EXCHANGE_PATTERN`, `CEX_EXCHANGES`, `CEX_EXCHANGE_PATTERN`, `EXCHANGE_OR_ANY_PATTERN` in `src/models/enums.py`. Neue Exchanges nur noch an einer Stelle (ExchangeType Enum) hinzufuegen
- **PII-Verschluesselung** — `telegram_chat_id` und `whatsapp_recipient` werden jetzt Fernet-verschluesselt gespeichert (waren vorher Klartext). Migration 004 verschluesselt bestehende Werte idempotent
- **Grafana-Passwort-Validierung** — `config_validator.py` warnt bei schwachem `GF_ADMIN_PASSWORD`

### Geaendert
- **40+ hardcodierte Exchange-Patterns ersetzt** — 11 Regex-Patterns und 6 Listen/Sets in Schemas und Routern nutzen jetzt die zentralen Konstanten aus `enums.py`
- **Rate Limiter erweitert** — `bitunix` und `bingx` zu `EXCHANGE_LIMITS` hinzugefuegt (fehlten vorher, fielen auf Defaults zurueck)
- **Datenbank-Spaltentypen** — `telegram_chat_id` von `String(50)` auf `Text`, `whatsapp_recipient` von `String(20)` auf `Text` (fuer verschluesselte Werte)

### Betroffene Dateien
- `src/models/enums.py` — 5 abgeleitete Konstanten
- `src/api/schemas/bots.py`, `config.py`, `preset.py` — Pattern-Imports
- `src/api/routers/bots.py`, `config.py`, `bots_lifecycle.py`, `affiliate.py` — Konstanten-Imports
- `src/models/database.py` — Spaltentyp-Aenderungen
- `src/bot/notifications.py` — decrypt_value fuer chat_id und recipient
- `src/exchanges/rate_limiter.py` — 2 neue Exchange-Eintraege
- `src/utils/config_validator.py` — Grafana-Passwort-Check
- `migrations/versions/004_encrypt_pii_fields.py` — Neue Migration

---

## [3.35.2] - 2026-03-04

### Geaendert
- **Contrarian Pulse v2 Defaults auf Real-Data optimiert** — Basierend auf echten historischen Daten (Alternative.me F&G, Binance Klines+Funding, 90 Tage):
  - F&G-Schwellen von 30/70 auf **35/65** geweitet (mehr Signale, bessere Win Rate)
  - Ultra-F&G von 20/80 auf **25/75** angepasst
  - Schema-Defaults synchronisiert
- **Backtest-Datenqualitaetspruefung verbessert** — Prueft jetzt F&G und Preise statt L/S und OI. Binance speichert L/S/OI nur 30 Tage; aeltere Backtests nutzen korrekt Defaults statt auf Mock-Daten zu fallen
- **Real-Data Backtest-Script** (`scripts/backtest_contrarian_real.py`) — Dokumentiert Datenabdeckung und testet mit echten historischen Daten

### Real-Data Backtest-Ergebnisse (90 Tage, echte Daten, Bitget Standard Fees)
- Datenabdeckung: F&G 98%, Klines 100%, Funding 100%, L/S 0%, OI 0%
- **Bester Setup: F&G 35/65 @ 1h — 34 Trades, 44% WR, +2.13%, Sharpe 2.29**
- Zweitbester: F&G 35/65 @ 30m — 43 Trades, 42% WR, +2.09%, Sharpe 1.94
- 4h-Timeframe durchgehend negativ, nicht empfohlen

---

## [3.35.1] - 2026-03-04

### Geaendert
- **Contrarian Pulse v2 Optimierung** — 3 strukturelle Schwaechen behoben:
  1. **EMA-Bypass fuer ultra-extreme F&G** — Bei F&G < 20 oder > 80 wird der EMA-Trendfilter uebersprungen (kontraeres Signal stark genug), erfordert aber +1 extra Bestaetigung
  2. **RSI-Divergenz ersetzt CVD** — CVD war redundant zu Volume buy/sell split. RSI-Divergenz ist ein staerkeres kontraeres Signal (bullish: price lower low + RSI higher low)
  3. **EMA200-Naehe ersetzt OI>0** — OI>0 war immer true (free pass). Jetzt: Preis innerhalb ±3% von EMA200 als echte Support/Resistance-Zone
- **Graduierte Confidence-Bewertung** — F&G-Bonus proportional zur Extremitaet (F&G=5 gibt vollen Bonus, F&G=25 gibt partiellen Bonus statt binaer)
- **Min. Bestaetigungen von 2 auf 1 gesenkt** — Da alle 5 Bestaetigungen jetzt aussagekraeftig sind (kein Free Pass mehr), reicht 1 aus
- **Neue konfigurierbare Parameter** — `fg_ultra_fear`, `fg_ultra_greed`, `rsi_divergence_lookback`, `ema200_proximity_pct` im Frontend-Schema verfuegbar
- **Strategie-Beschreibung aktualisiert** — Docstring und `get_description()` reflektieren v2-Aenderungen

### Backtest-Ergebnisse v2 (90 Tage, Mock-Daten, Bitget Standard Fees)
- **v2 1-confirm @ 30m: +12.94%, 62% WR, 53 Trades** ← NEUER BESTER (vs v1 +10.62%)
- v2 aggressive @ 30m: +12.22%, 55% WR, 71 Trades
- v2 no-bypass @ 15m: +7.37%, 100% WR, 12 Trades
- v2 default @ 30m: +6.53%, 57% WR, 44 Trades
- 15m und 30m konsistent beste Timeframes

---

## [3.35.0] - 2026-03-04

### Hinzugefuegt
- **Neue Strategie: Contrarian Pulse** — Rein algorithmische Fear & Greed Kontra-Scalping-Strategie fuer BTC. Nutzt den F&G Index als Kontraindikator (Long bei Extreme Fear, Short bei Extreme Greed), bestaetigt durch 50/200 EMA-Trend, RSI und 5 Derivate-Signale (CVD, L/S Ratio, Volume, OI, Funding). Kein LLM erforderlich.
- **Backtest-Script** (`scripts/backtest_contrarian_pulse.py`) — Testet 8 Parameter-Varianten ueber 5 Timeframes (15m, 30m, 1h, 4h, 1d) mit Bitget-Gebuehren
- **Frontend-Integration** — Contrarian Pulse im Bot Builder Wizard verfuegbar mit festen Datenquellen und konfigurierbaren Parametern (F&G-Schwellen, Min. Bestaetigungen, L/S-Limits, RSI-Grenzen)
- **i18n** — Deutsche und englische Strategiebeschreibung hinzugefuegt

### Geaendert
- **Backtest-Datenqualitaetspruefung** (`strategy_adapter.py`) — Erkennt fehlende Derivate-Daten (L/S=1.0, OI=0) und faellt automatisch auf Mock-Daten zurueck statt mit fehlerhaften Live-API-Daten zu arbeiten
- **Optimierte TP/SL-Defaults** — Basierend auf Backtest-Ergebnissen: 2.0% TP / 1.0% SL (2:1 R:R-Verhaeltnis). Bestes Ergebnis: +10.62% Return auf 15m-Timeframe

### Backtest-Ergebnisse (90 Tage, Mock-Daten, Bitget Standard Fees)
- Bester Timeframe: 15m (+4.57% bis +10.62% je nach Parametern)
- Bester Setup: TP 2.0% / SL 1.0% auf 15m — 15 Trades, 100% Win Rate, +10.62%
- 1d-Timeframe durchgehend negativ (-13% bis -20%), nicht empfohlen
- Hoehere Confirmations (3) erhoehen Win Rate auf 100%, reduzieren aber Trade-Anzahl

---

## [3.34.0] - 2026-02-28

### Hinzugefuegt
- **Trailing Stop im Trades-API** (#102) — `GET /api/trades` und `GET /api/trades/{id}` liefern jetzt live Trailing-Stop-Daten fuer offene Edge-Indicator-Trades: `trailing_stop_active`, `trailing_stop_price`, `trailing_stop_distance`, `trailing_stop_distance_pct`, `can_close_at_loss`. ATR wird live von Binance Klines berechnet
- **Zentralisierte Fehlerkonstanten** (`src/errors.py`) — Alle deutschen Fehlermeldungen als importierbare Konstanten. Source-Code und Tests referenzieren dieselbe Konstante, sodass Wording-Aenderungen nie wieder Tests brechen
- **8 neue Trailing-Stop-Tests** — LONG aktiv, SHORT aktiv, nicht profitabel, geschlossener Trade, Nicht-Edge-Strategie, Listen-Endpoint, Kline-Fehler, fehlender highest_price

### Behoben
- **81 fehlgeschlagene CI-Tests** — Deutsche Fehlermeldungen in Source vs. englische Assertions in Tests. Geloest durch zentrale Konstanten in `src/errors.py` + Import in 11 Source- und 21 Test-Dateien
- **Risk Manager Tests** — `patch('settings')` entfernt (Modul existiert nicht mehr), Tests direkt auf `RiskManager()` umgestellt
- **Position Monitor Tests** — `trade.highest_price = None` zu Test-Mocks hinzugefuegt
- **BotConfigResponse margin_mode** — `getattr()` gibt MagicMock zurueck statt Default; Fix: `getattr(..., None) or "cross"`
- **Bitget Client Tests** — Flash-Close API: `holdSide` statt `side`, Response-Format `successList` aktualisiert
- **Optional TP/SL Tests** — Assertions an neue Optionalitaet und deutsche Validierungsmeldungen angepasst

---

## [3.33.0] - 2026-02-26

### Geaendert
- **"Position schließen" Button direkt sichtbar** — Wenn ein Bot offene Trades hat, erscheint jetzt ein prominenter Amber-Button direkt auf der Bot-Karte (statt versteckt im Drei-Punkte-Menue). Bei Single-Pair-Bots: 1-Klick-Schließen. Bei Multi-Pair-Bots: Dropdown-Auswahl. Open-Trades-Zaehler wird amber mit Puls-Indikator hervorgehoben
- **Tests korrigiert** — SignalDirection Enum-Count auf 3 aktualisiert (LONG, SHORT, NEUTRAL), Edge Indicator DEFAULTS-Test an v2-Werte angepasst (0.35/-0.35)

### Entfernt
- **Claude Edge Indicator komplett entfernt** — A/B-Tests zeigten, dass Edge Indicator v2 auf 1h durchschnittlich +6.2% Return liefert vs Claude Edge ~+3%. Alle wertvollen Features (MACD Floor, default_sl_atr) waren bereits als optionale Parameter in Edge v2 portiert. 7 Dateien geloescht, 30 Dateien bereinigt
- **Backend:** `src/strategy/claude_edge_indicator.py` geloescht, Routing und Signal-Methode aus Backtest-Engine entfernt, KLINE_STRATEGIES bereinigt
- **Tests:** 4 dedizierte Test-Dateien geloescht, Claude Edge Referenzen aus 4 Shared-Test-Dateien entfernt
- **Scripts:** `backtest_v331.py` geloescht, Strategie-Listen in backtest_timeframes, backtest_altcoins, run_backtest_matrix bereinigt
- **Frontend:** Claude-Edge aus BotBuilder, Bots, Backtest, BotDetail, BotPerformance, GettingStarted entfernt
- **i18n:** stratClaudeEdge Keys und strategyDesc_claude_edge_indicator aus en.json und de.json entfernt
- **Dokumentation:** Alle Anleitungen, FAQ, README, STRATEGY.md aktualisiert (6 Strategien → 5 Strategien)

---

## [3.32.0] - 2026-02-26

### Geaendert
- **Edge Indicator v2: Exit-Tuning** — Momentum-Schwellen von 0.20 auf 0.35, Trailing Stop von 1.5 auf 2.5 ATR, Smoothing von 3 auf 5 erhoht. A/B-Test ueber 10 Coins x 3 Timeframes zeigt: 1h Return verdreifacht (+2.0% auf +6.2%), Sharpe verdoppelt (0.33 auf 0.67), v2 gewinnt 7/10 auf 1h. Trades werden laenger gehalten, profitable Positionen laufen weiter statt frueh geschlossen zu werden
- **Edge Indicator: MACD Floor + Default SL** — use_macd_floor (Default: True) und default_sl_atr (Default: 0, optional) aus Claude Edge portiert. MACD Floor als Sicherheitsfeature, Default SL optional aktivierbar
- **Backtest-Ergebnisse aktualisiert** — Claude Edge Indicator Zahlen basieren jetzt auf v3.31.0 (90d Backtest). Alte Zahlen (+14.2%, Sharpe 1.40) durch ehrliche v3.31 Ergebnisse ersetzt: BTC 1h +1.4% (Sharpe 0.33), ETH 1h +8.5% (Sharpe 1.00)
- **Frontend-Beschreibungen (de.json + en.json)** — Edge Indicator: v2 Exit-Optimierung erwaehnt, neue Altcoin-Performance-Zahlen. Claude Edge: v3.31.0 Features (Default SL, MACD Floor) und neue Backtest-Zahlen. Timeframe-Empfehlung von "1h / 4h" auf "1h" geaendert
- **Backend get_description()** — Edge Indicator erwaehnt v2 Exit-Optimierung. Claude Edge erwaehnt ATR-basiertes Default-SL, MACD Noise Floor und Timeframe-Empfehlung (1h)
- **kline_interval Schema-Beschreibung** — Timeframe-Empfehlung (1h) direkt im Parameter-Hint sichtbar
- **Strategien-Uebersicht (DE + EN)** — Edge Indicator: neue Exit-Parameter in Tabelle (Momentum Threshold, Trailing ATR, Smooth). Claude Edge: 3 neue Features (Default SL, MACD Floor, Seitwaertsmarkt-Filter), Backtest-Tabelle
- **Empfehlungen** — Claude Edge Indicator jetzt auch fuer Einsteiger empfohlen (Default SL als Sicherheitsnetz)

### Hinzugefuegt
- **Backtest-Ergebnisse-BTC.md** — v3.31.0 Abschnitt mit ehrlicher Bewertung, ETH-Ergebnisse, Edge v2 Altcoin-Performance, Hinweis auf Trendmarkt-Abhaengigkeit
- **5 Backtest-Scripts** — backtest_altcoins.py, backtest_edge_v2.py, backtest_edge_v2_macd_only.py, backtest_macd_floor_ab.py, backtest_exit_tuning.py fuer A/B-Tests und Strategie-Vergleiche

### Behoben
- **_calculate_targets() Signatur-Bug** — Backtest-Engine uebergibt 3 Argumente (direction, price, klines), aber EdgeIndicator, LiquidationHunter und SentimentSurfer akzeptierten nur 2. Behoben durch optionalen klines=None Parameter in allen 3 Strategien

---

## [3.31.0] - 2026-02-26

### Geaendert
- **Fallback-Logik entschaerft** — `_determine_direction()` gibt jetzt NEUTRAL zurueck wenn Regime und Ribbon sich widersprechen (z.B. Regime=1 bei bear_trend). Vorher wurde im Seitwaertsmarkt immer eine Richtung erzwungen, was zu Verlusttrades fuehrte
- **Default Stop-Loss bei 2x ATR** — Jeder Trade hat jetzt ein Sicherheitsnetz: wenn kein expliziter SL konfiguriert ist, wird automatisch ein SL bei 2x ATR gesetzt. Prioritaets-Kette: stop_loss_percent > atr_sl_multiplier > default_sl_atr (2.0) > deaktiviert (0)
- **MACD stdev Floor** — Verhindert extreme macd_norm Werte (±1.0) bei niedriger Vola. Floor = 1% des ATR. Bei BTC 1h (ATR ~$500) ist der Floor $5, was falsche Regime-Flips in Seitwaertsmaerkten daempft
- **TradeExecutor bewahrt Strategy-SL** — Wenn kein User-SL (stop_loss_percent) konfiguriert ist, wird der Strategy-berechnete SL (z.B. Default ATR SL) nicht mehr auf None gesetzt

### Hinzugefuegt
- **Neuer Parameter `default_sl_atr`** — Konfigurierbares Sicherheitsnetz-SL (Default 2.0x ATR). Per UI anpassbar (0.0-5.0, 0 = deaktiviert). Wird von stop_loss_percent und atr_sl_multiplier ueberschrieben
- **10 neue Tests** — Fallback NEUTRAL (3), Default SL Prioritaets-Kette (4), MACD Floor (2), Schema/Defaults (1)

---

## [3.30.0] - 2026-02-26

### Geaendert
- **Exit-Logik gehaertet: AND-Bedingung** — Ribbon allein reicht nicht mehr fuer Exit. Jetzt muessen EMA-Ribbon UND Momentum-Regime uebereinstimmen (z.B. SHORT-Exit nur bei bull_trend + regime >= 1). Verhindert Fehl-Exits durch einzelne gruene Kerzen bei engem Ribbon
- **trend_bonus von 0.6 auf 0.3 reduziert** — Momentum-Score wird jetzt unabhaengiger vom EMA-Ribbon berechnet. Bei 0.3 reicht der Trend-Bonus allein nicht mehr um den Regime-Threshold (0.35) zu ueberschreiten — MACD oder RSI muessen mindestens +0.05 beitragen
- **should_exit() akzeptiert entry_time** — Neuer optionaler Parameter fuer Haltezeit-Pruefung, rueckwaertskompatibel via **kwargs in Base- und Edge-Strategie

### Hinzugefuegt
- **Mindest-Haltezeit (min_hold_hours)** — Trades werden mindestens 4h gehalten bevor Indikator-Exits (Layer 2) greifen. Trailing-Stop (Layer 1) bleibt immer aktiv. Guard sitzt zwischen Layer 1 und Layer 2 in should_exit(). Default: 4.0h, per UI anpassbar (0-72h)
- **Post-Trade Cooldown (cooldown_hours)** — Nach Trade-Schliessung wird 4h gewartet bevor ein neuer Trade fuer dasselbe Symbol geoeffnet wird. Verhindert Open-Close-Open-Schleifen. Default: 4.0h, per UI anpassbar (0-72h, 0 = deaktiviert)
- **3 neue UI-Parameter** — `trend_bonus_weight`, `min_hold_hours`, `cooldown_hours` im Strategy-Schema sichtbar und vom User anpassbar
- **15 neue Tests** — AND-Bedingung (4), trend_bonus-Reduktion (2), Haltezeit (3), Cooldown (3), neue Defaults + Schema (2), plus existierende 12 bestanden

---

## [3.29.0] - 2026-02-26

### Geaendert
- **should_exit() Schwellen erhoeht** — Weniger Fehl-Exits durch angepasste Defaults: `momentum_bull/bear_threshold` 0.20→0.35, `trailing_trail_atr` 1.5→2.5, `trailing_breakeven_atr` 1.0→1.5, `momentum_smooth_period` 3→5. Reduziert aggressive Fruehaus-Exits (vorher 17/35 Trades < 2 Min)
- **TP/SL an Exchange gesendet** — User-definierte TP/SL-Werte (per-asset oder bot-level) werden jetzt als absolute Preise an die Exchange uebergeben statt geloescht. Long: TP = Entry × (1 + tp%), SL = Entry × (1 - sl%). Short: invertiert
- **should_exit() bedingt deaktiviert** — Wenn ein Trade TP/SL auf der Exchange hat, wird should_exit() uebersprungen (Exchange handelt Exit). Ohne TP/SL laeuft should_exit() wie bisher als Fallback

### Hinzugefuegt
- **tpsl_failed Safety-Fallback** — Wenn die Exchange TP/SL nicht setzen kann, werden TP/SL auf None zurueckgesetzt und should_exit() greift automatisch als Backup
- **4 neue Pro-Mode Parameter im UI** — `trailing_breakeven_atr`, `trailing_trail_atr`, `momentum_smooth_period`, `atr_period` sind jetzt im Strategy-Schema sichtbar und vom User anpassbar
- **TP/SL Erfolgs-Logging** — Neuer Log-Eintrag wenn TP/SL erfolgreich an Exchange gesendet wird (vorher nur None- und Failed-Branch)
- **25 neue Tests** — 13 Unit-Tests (test_tpsl_passthrough.py) + 12 Integration-Tests (test_tpsl_flow.py) mit stateful Exchange-Mock und Beispiel-Trades
- **Demo-Trade Test-Script** — `scripts/test_tpsl_demo_trade.py` fuer Live-Verifikation auf Bitget Demo-API (5 Szenarien)

---

## [3.28.0] - 2026-02-25

### Hinzugefuegt
- **Trailing Stop + Breakeven Exit-Strategie** — Neues zweistufiges Exit-System fuer alle Strategien (Edge Indicator + Claude Edge). ATR-basierter Trailing Stop (1.5x ATR vom Hoechstpreis) sichert Gewinne dynamisch. Breakeven-Schutz verhindert, dass profitable Trades im Minus geschlossen werden. Hoechstpreis wird in DB gespeichert und ueberlebt Bot-Neustarts
- **Anleitung Trailing Stop** — Neue Dokumentation (`Anleitungen/Trailing-Stop-Exit-Strategie.md`) mit Erklaerung, Parametern und Beispiel-Szenarien

---

## [3.27.0] - 2026-02-25

### Geaendert
- **Position Monitor auf 1 Minute** — Erkennung von manuell geschlossenen Positionen reduziert von 5 Min auf 1 Min. Rate-Limit-Pruefung fuer alle Exchanges (Bitget, Hyperliquid, Weex) bestaetigt Sicherheit
- **TP/SL komplett aus Exchange-Orders entfernt** — `trade_executor.py` setzt `target_price` und `stop_loss` immer auf `None`. Exit wird ausschliesslich durch die Strategie-Logik gesteuert, nicht durch Exchange-Orders
- **TP/SL in API-Schema optional** — `TradeResponse.take_profit` und `TradeResponse.stop_loss` sind jetzt `Optional[float]` um Trades ohne TP/SL korrekt darzustellen

### Hinzugefuegt
- **Warnung bei Bot-Stop mit offenen Positionen** — Beim Stoppen eines Bots mit offenen Trades wird eine Warnung angezeigt: "X offene Position(en) werden NICHT automatisch geschlossen und nicht mehr ueberwacht"

---

## [3.26.0] - 2026-02-25

### Behoben
- **Weex Exchange Client komplett ueberarbeitet** — Alle API-Pfade von `/api/v2/mix/` (Bitget-Format) auf korrekte Weex-Pfade `/capi/v2/` umgestellt. Base-URL von nicht-existentem `api.weex.com` auf `api-contract.weex.com` korrigiert
- **Weex Demo-Modus korrekt implementiert** — Weex hat kein separates Testnet. Demo-Modus nutzt jetzt die selbe URL wie Live, aber mit SUSDT-Symbolen (z.B. `cmt_btcsusdt` statt `cmt_btcusdt`). Stellt sicher dass Demo-Bots nur Demo-Assets handeln
- **Weex Symbol-Transformation** — Neue `_to_api_symbol()` / `_from_api_symbol()` Methoden wandeln DB-Symbole (BTCUSDT) automatisch in Weex-API-Format um (`cmt_btcusdt` fuer Live, `cmt_btcsusdt` fuer Demo)
- **Weex close_position** — Nutzt jetzt Flash-Close Endpoint (`/capi/v2/order/closePositions`) statt fehleranfaelligem place-order
- **Weex Order-Format** — Korrekte `type`-Parameter (1=Open Long, 2=Open Short, 3=Close Long, 4=Close Short) statt Bitget-Format (`side`+`tradeSide`)
- **Symbol-Map aktualisiert** — Weex nutzt jetzt konsistentes BTCUSDT-Format (Client transformiert intern)

---

## [3.25.0] - 2026-02-25

### Hinzugefuegt
- **Strategie-basierte Exit-Signale** — Neue `should_exit()` Methode in BaseStrategy. Edge Indicator und Claude Edge Indicator pruefen alle 5 Min ob der Trend noch intakt ist (EMA-Ribbon, Predator Momentum, Regime Flips). Positionen werden automatisch geschlossen wenn die Indikatoren drehen
- **Neuer Exit-Grund `STRATEGY_EXIT`** — Wird in Trade-History, Logs und Notifications angezeigt wenn die Strategie eine Position schliesst
- **TP/SL-Warnung im BotBuilder** — Gelbe Warnung bei fehlendem Stop-Loss, orange Warnung wenn weder TP noch SL gesetzt. Review-Step zeigt "Kein TP/SL (Strategie-Exit)" pro Asset

### Geaendert
- **TP/SL nicht mehr standardmaessig gesetzt** — Alle Strategien (Edge Indicator, Claude Edge, Liquidation Hunter, Sentiment Surfer) haben keine TP/SL-Defaults mehr. User muss TP/SL explizit in der Per-Asset-Config oder via Preset setzen. Ohne TP/SL verlaesst sich der Bot auf die Strategie-Exit-Logik
- **Claude Edge Indicator** — ATR-basierte TP/SL-Multiplikatoren (`atr_tp_multiplier`, `atr_sl_multiplier`) aus Defaults entfernt, `should_exit()` implementiert

### Behoben
- **Manuelles Position-Schliessen verifiziert jetzt den Exchange-Status** — Bisher wurde der Trade in der DB als geschlossen markiert auch wenn der Exchange-Close fehlschlug. Jetzt wird nach dem Close-Versuch geprueft ob die Position wirklich weg ist. Bei Fehler erhaelt der User eine klare Fehlermeldung statt einer stillen Fehlinformation

---

## [3.24.0] - 2026-02-24

### Hinzugefuegt
- **Margin-Modus-Auswahl im BotBuilder** — Neues `margin_mode`-Feld (Cross/Isolated) pro Bot waehlbar. Cross teilt Margin ueber alle Positionen, Isolated begrenzt das Risiko pro Position. Standard: Cross (wie bisher)
- **Alembic-Migration 002** — Neue Spalte `margin_mode` in `bot_configs` mit Server-Default "cross" fuer bestehende Bots
- **API-Schemas erweitert** — `margin_mode` in Create/Update/Response/RuntimeStatus Schemas
- **Exchange-Clients aktualisiert** — Bitget, Weex und Hyperliquid verwenden den gewaehlten Margin-Modus bei `set_leverage()`, `place_market_order()`, `close_position()` und `place_raw_order()`
- **BotBuilder UI** — Margin-Modus-Selector (Cross/Isolated Buttons) in Step 4 (Exchange) mit Erklaerungstext, Anzeige im Review-Step
- **i18n** — Deutsche und englische Uebersetzungen fuer Margin-Modus

### Geaendert
- **Kein globaler Trading-Parameter-Fallback mehr** — RiskManager verwendet keine globalen Settings (`config/settings.py`) mehr als Fallback. Wenn `max_trades_per_day`, `daily_loss_limit_percent` oder `position_size_percent` nicht in der Bot-Config gesetzt sind, gilt: NULL = kein Limit bzw. volles Budget. User muss Werte explizit per Bot-Erstellung oder Preset setzen

---

## [3.23.0] - 2026-02-24

### Hinzugefuegt
- **Symbol-Konflikt-Erkennung** — Warnung im BotBuilder (Step 4 + Review) wenn Trading-Paare mit bestehenden aktiven Bots kollidieren. Erstellen/Bearbeiten bleibt moeglich, nur Starten wird bei Konflikten blockiert (Defense-in-Depth)
- **GET `/api/bots/symbol-conflicts`** — Neuer Endpoint prueft Trading-Pair-Konflikte mit bestehenden aktiven Bots (Mode-Konflikt-Matrix: demo↔demo/both, live↔live/both, both↔alle)
- **Manuelles Position-Schliessen** — Close-Position-Optionen immer im 3-Punkte-Menue verfuegbar (pro Trading-Pair). Endpoint `POST /api/bots/{bot_id}/close-position/{symbol}` schliesst die Position auf der Exchange und markiert den Trade-Record als closed. Robust bei bereits geschlossenen Positionen
- **3-Punkte-Menue auf Bot-Karten** — Bearbeiten, Kopieren, Position schliessen und Loeschen in ein kompaktes Dropdown-Menue verschoben
- **Vollstaendige deutsche Lokalisierung** — Alle Backend-Fehlermeldungen (HTTPException) in allen API-Routers auf Deutsch uebersetzt: auth, bots, config, backtest, presets, trades, users, affiliate, exchanges

---

## [3.22.1] - 2026-02-24

### Hinzugefuegt
- **"Alle speichern" Button fuer Affiliate-Links** — Neuer Button neben der Ueberschrift "Affiliate-Links pro Exchange konfigurieren" speichert alle Exchanges mit URL parallel via `Promise.all`. Erspart das einzelne Speichern jeder Zeile

### Behoben
- **Affiliate-Link Daten verschwinden bei Inaktiv-Toggle** — `GET /api/affiliate-links` gab nur aktive Links zurueck. Wenn ein Admin einen Link auf inaktiv setzte und speicherte, wurden URL und Label beim naechsten Laden geloescht. Fix: Admins sehen jetzt alle Links (auch inaktive), normale User weiterhin nur aktive
- **Bot tradet sofort beim Start trotz Market-Session-Schedule** — `start()` rief `_analyze_and_trade_safe()` immer sofort auf, unabhaengig vom Schedule-Typ. Bei `market_sessions` und `custom_cron` wurde der CronTrigger umgangen und ein Trade ohne Ruecksicht auf die konfigurierten Stunden ausgefuehrt. Fix: Initiale Analyse nur wenn die aktuelle UTC-Stunde in den konfigurierten Session-Stunden liegt. Andernfalls wird geloggt, wann die naechste Session startet

---

## [3.22.0] - 2026-02-24

### Hinzugefuegt
- **Strategie-Dokumentation** — Vollstaendiges technisches Dokument (`Anleitungen/Strategie-Dokumentation.md`) fuer alle 5 Trading-Strategien: Edge Indicator, Claude Edge Indicator, Liquidation Hunter, Sentiment Surfer und Degen. Erklaert die zugrundeliegende Handelslogik, Datenquellen, Entscheidungsregeln, Konfidenz-Berechnung und Beispiel-Szenarien
- **Exchange-Balance Uebersicht im BotBuilder** — Step 3 zeigt jetzt eine kompakte Tabelle aller verbundenen Exchanges mit Equity, bereits allokiertem Guthaben und verfuegbarem Budget. Ausgewaehlte Exchange wird hervorgehoben. Amber-Warnung bei Ueberallokation (>100%) oder unzureichendem Guthaben
- **Multi-Exchange Balance-Overview Endpoint** — Neuer API-Endpoint `GET /api/bots/balance-overview` liefert Balance-Daten fuer alle konfigurierten Exchanges parallel (asyncio.gather). Unterstuetzt `exclude_bot_id` Parameter fuer Edit-Modus (keine Doppelzaehlung)
- **Einzel-Exchange Balance-Preview Endpoint** — Neuer API-Endpoint `GET /api/bots/balance-preview` zeigt Balance + Allokation fuer eine spezifische Exchange/Mode-Kombination. Wird fuer Dollar-Betraege neben Prozenten in der Per-Asset-Konfiguration verwendet

---

## [3.21.0] - 2026-02-23

### Hinzugefuegt
- **Budget/Balance-Warnung im Bot-Dashboard** — Neuer API-Endpoint `GET /api/bots/budget-info` zeigt pro Bot: verfuegbares Guthaben, allokiertes Budget, Gesamt-Allokation pro Exchange. Bot-Cards zeigen Budget-Zeile und amber Warnbanner wenn Mittel nicht ausreichen oder Bots ueberallokiert sind (>100%). Verhindert stilles Scheitern wenn mehrere Bots dasselbe Konto teilen
- **Graceful Degradation fuer SentimentSurfer ohne News** — Wenn GDELT keine Artikel liefert (Timeout/Ausfall), wird die News-Quelle komplett aus der Signal-Berechnung entfernt statt als neutrales Signal gezaehlt. Agreement-Check passt sich dynamisch an (z.B. "3/5" statt "3/6"). Verbleibende 5 Quellen (Fear&Greed, VWAP, Supertrend, Volume, Momentum) entscheiden allein

### Geaendert
- **GDELT-Parameter optimiert** — `max_records`: 25→10, Query: `"bitcoin OR cryptocurrency OR crypto"`→`"bitcoin"`, `lookback_hours`: 24→12, Timeout: 15s→10s. Kleinere Queries = schnellere Antworten von der ueberlastetem GDELT-API
- **GDELT Circuit Breaker gelockert** — `reset_timeout`: 300s→120s (schneller erneut versuchen bei intermittierender Verfuegbarkeit)

---

## [3.20.2] - 2026-02-23

### Behoben
- **Logging im Docker-Container komplett fehlend** — `setup_logging()` wurde im API-Einstiegspunkt (`main_app.py`) nie aufgerufen, da Docker uvicorn direkt startet statt ueber `main.py`. Alle INFO-Level Logs (Analysen, Budgets, Signale) waren unsichtbar — nur ERROR-Meldungen kamen durch Pythons Last-Resort-Handler. Fix: `setup_logging()` wird jetzt in `main_app.py` aufgerufen
- **Falsches Balance-Feld bei Bitget Cross-Margin** — `get_account_balance()` nutzte `available` (auszahlbarer Betrag) statt `crossedMaxAvailable` (tatsaechlich fuer neue Positionen verfuegbar). Bei bestehenden Positionen zeigte `available` den vollen Kontostand (~$20k), obwohl die Margin durch andere Positionen belegt war (~$19k). Ergebnis: Orders wurden von Bitget abgelehnt ("order amount exceeds balance"). Fix: Prioritaet auf `crossedMaxAvailable` geaendert
- **Debug-Logging fuer Order-Vorbereitung** — Vor jeder Orderplatzierung werden jetzt verfuegbares Guthaben, Leverage, Position-Groesse und Entry-Preis geloggt, um Balance-Fehler schneller zu diagnostizieren

---

## [3.20.1] - 2026-02-23

### Behoben
- **NoneType-Crash in Strategien** — Wenn Binance/GDELT-APIs intermittierend `None` zurueckgeben, crashte `generate_signal()` mit `unsupported operand type(s) for /: 'NoneType' and 'int'`. Betroffen: Liquidation Hunter (741x), Claude Edge (149x), Sentiment Surfer. Alle Metrik-Felder werden jetzt mit Fallback-Werten abgesichert
- **Trade-Execution Balance-Fehler** — Bot 1 scheiterte mit `The order amount exceeds the balance` weil `entry_price` nicht vor der Position-Size-Berechnung validiert wurde. Frueher Guard gegen ungueltige Preise hinzugefuegt
- **GDELT-Timeout-Kaskade** — News-Sentiment-API-Timeouts kaskadierten in NoneType-Fehler. Sentiment Surfer setzt jetzt explizite Fallback-Werte bei fehlenden Metriken
- **None TP/SL aus Bot-Config ueberschreibt Strategy-Defaults** — Wenn `take_profit_percent` und `stop_loss_percent` in der Bot-Config `NULL` sind, wurde `None` in die Strategy-Params injiziert und ueberschrieb die Defaults (4.0% / 1.5%). Fix: None-Werte werden nicht mehr an Strategien weitergegeben
- **Fehlende Tracebacks in Bot-Logs** — Error-Handler loggten nur die Fehlermeldung ohne Stacktrace, was Debugging unmoeglich machte. `exc_info=True` hinzugefuegt
- **Order exceeds balance bei 100% Position** — Position-Size-Berechnung nutzte 100% des Budgets als Margin, aber Bitget benoetigt Reserve fuer Gebuehren/Funding. Jetzt 95% Safety-Margin
- **Circuit Breaker vergiftet durch set_leverage** — `set_leverage` Fehler bei existierenden Positionen wurden als API-Fehler gezaehlt und oeffneten den Circuit Breaker fuer ALLE Bitget-Calls. Fix: set_leverage umgeht jetzt den Circuit Breaker

---

## [3.20.0] - 2026-02-22

### Hinzugefuegt
- **Trade-Fehler Benutzerbenachrichtigung** — Bei fehlgeschlagener Orderplatzierung wird der Benutzer sofort via WebSocket (`trade_failed` Event) und Discord/Telegram (`TRADE_FAILED` Risk Alert) benachrichtigt. Nur echte Fehler — "minimum amount" Warnungen werden nicht eskaliert
- **Atomare Daily-Loss-Limit Pruefung** — Per-User `asyncio.Lock` im Orchestrator stellt sicher, dass Risk-Check + Trade-Execution atomar ablaufen. Verhindert, dass parallele Bots gleichzeitig das Tageslimit umgehen
- **Datenbank-Performance-Indexes** — Neue Indexes `ix_trade_bot_status` (bot_config_id, status) und `ix_trade_entry_time` (entry_time) auf TradeRecord fuer schnellere Abfragen im Position Monitor
- **Log-Rotation** — `RotatingFileHandler` mit 100 MB pro Datei, 10 Backups. Automatisches JSON-Format in Production (`LOG_FORMAT=json` oder `ENVIRONMENT=production`)
- **Request-ID Middleware** — Jede Response enthaelt `X-Request-ID` Header fuer Log-Korrelation. Akzeptiert Client-Header oder generiert UUID
- **System-Metriken** — Neue Prometheus-Gauges: `process_resident_memory_bytes` (Speicherverbrauch), `disk_usage_percent` (Festplatte). Background-Collector erfasst alle 15 Sekunden
- **Trade-Failure Counter** — Neuer Prometheus-Counter `trade_failures_total` mit Labels `exchange` und `error_type`
- **PostgreSQL Backup Sidecar** — Automatisches taegliches Backup via `pg_dump` im Docker-Compose. Behaelt 7 Tage, loescht aeltere automatisch
- **Alertmanager Integration** — Vollstaendige Alertmanager-Konfiguration mit Webhook-Receiver. Separate Route fuer kritische Alerts (1h Wiederholung). Prometheus sendet Alerts an Alertmanager
- **Erweiterte Alert-Regeln** — 4 neue Prometheus-Alerts: `HighMemoryUsage` (>768MB), `HighDiskUsage` (>85%), `CriticalDiskUsage` (>95%), `TradeExecutionFailures`
- **Graceful Shutdown** — `STOPSIGNAL SIGTERM` + `--timeout-graceful-shutdown 25s` im Dockerfile, `stop_grace_period: 30s` in Docker-Compose
- **CPU-Limit** — Trading-Bot Container auf 2.0 CPUs begrenzt
- **35 neue Tests** — Trade-Failure-Notification (4), Per-User Trade Lock (6), DB-Indexes (2), Log-Rotation (2), Request-ID (2), Health-Check (1), Prometheus-Metriken (3), Metrics-Collector (2), Docker/DevOps-Konfiguration (13)

### Geaendert
- **Health-Check Endpoint** — Erweitert um `checks`-Objekt mit `database` und `bots` Status. Zeigt Anzahl der Bots im Error-State
- **Erweiterter Metrics-Collector** — Sammelt jetzt auch Prozess-Speicher (Linux: `resource.getrusage`, Windows: Fallback) und Disk-Usage (`shutil.disk_usage`)

### Frontend
- **i18n: Hardcoded Strings entfernt** — Alle `" - OK"` Suffixe und `"Failed to load data"` durch `t()` Uebersetzungen ersetzt (Bots, BotDetail, Dashboard, Backtest, BotPerformance, GettingStarted, Trades)
- **Modal Accessibility** — `role="dialog"`, `aria-modal="true"`, `aria-label`, Escape-Key-Handler auf TradeDetailModal und BotTradeHistoryModal
- **Toast Store** — Maximum 10 Toasts gleichzeitig (aeltere werden automatisch entfernt)
- **Realtime Store** — `removeBotStatus()` Methode fuer Cleanup hinzugefuegt
- **Portfolio Performance** — `chartData` mit `useMemo` optimiert (abhaengig von `dailyData`)

---

## [3.19.0] - 2026-02-22

### Hinzugefuegt
- **Metrics Endpoint IP-Restriction** — `/metrics` ist in Production nur von localhost, Docker-Netzwerken und `METRICS_ALLOWED_IPS` erreichbar (403 fuer andere IPs)
- **HTTPS Redirect Middleware** — Automatische HTTP→HTTPS Weiterleitung (301) in Production ueber `X-Forwarded-Proto` Header (fuer Nginx/Caddy/Traefik)
- **Default-Passwort Erkennung** — Config Validator lehnt schwache Passwoerter (`tradingbot_dev`, `changeme`, etc.) bei `ENVIRONMENT=production` ab — App startet nicht
- **11 neue Security-Tests** — Metrics IP-Restriction (5), HTTPS Redirect (3), Default-Passwort Validator (3)

### Geaendert
- **docker-compose.yml** — Produktions-Checkliste als Kommentar ergaenzt (POSTGRES_PASSWORD, GF_ADMIN_PASSWORD, ENVIRONMENT)

---

## [3.18.0] - 2026-02-22

### Hinzugefuegt
- **Toast-Benachrichtigungen im Frontend** — Alle `console.error`-Only-Catches durch `useToastStore.addToast()` ergaenzt (8 Dateien, 15+ Stellen). Benutzer sehen jetzt Fehlermeldungen bei API-Fehlern
- **Rate Limiting auf allen Endpoints** — 16 ungeschuetzte Endpoints in 5 Router-Dateien mit `@limiter.limit()` versehen:
  - `admin_logs.py` (5 Endpoints: 60/min Lesen, 5/min Loeschen)
  - `exchanges.py` (2 Endpoints: 30/min)
  - `funding.py` (2 Endpoints: 30/min)
  - `portfolio.py` (4 Endpoints: 20-30/min)
  - `statistics.py` (3 Endpoints: 30/min)
- **Exchange-Name Validierung** — `GET /api/exchanges/{name}/info` validiert Parameter mit Regex `^[a-zA-Z][a-zA-Z0-9_-]{0,29}$`, gibt 400 bei ungueltigem Namen
- **Log-Redaktion** — `RedactionFilter` in `logger.py` maskiert automatisch API-Keys, Bearer-Tokens und JWTs in allen Log-Ausgaben
- **Prometheus Alert Rules** — 9 Alerting-Regeln fuer kritische Events:
  - `HealthCheckFailing`, `HighErrorRate`, `NoBotsRunning`, `BotInErrorState`
  - `BotConsecutiveErrors`, `HighRequestLatency`, `SlowDatabaseQueries`
  - `HighWebSocketConnections`, `HighRateLimitHits`
- **Docker Health Check verbessert** — Parst jetzt `/api/health`-Response und prueft `status == "healthy"` (statt nur HTTP 200)
- **18 neue Tests** — Auth-Integration (Login Lockout Flow, Password Change + Token Revocation), Exchange-Validierung, Log-Redaktion (5 Faelle), Rate-Limiting Coverage (5 Router-Dateien)

### Behoben
- **Frontend: Stille Catches endgueltig behoben** — Alle `catch { /* ignore */ }` durch `console.error` + Toast-Benachrichtigung ersetzt
  - Backtest.tsx: 4 Catches (Submit, Load, Delete + Polling-Error-Logging)
  - BotPerformance.tsx: 2 Catches (Copy-to-Clipboard Error-Logging)
  - Bots.tsx: 2 Catches (Trade History Load + Copy-Image Error-Logging)

---

## [3.17.0] - 2026-02-22

### Behoben
- **CRITICAL: Path Traversal in SPA Routing** — `serve_spa()` validiert jetzt, dass aufgeloeste Pfade innerhalb des Frontend-Verzeichnisses bleiben. Verhindert `../../etc/passwd`-Angriffe
- **CRITICAL: TP/SL Fehlerbehandlung (Bitget)** — TP/SL-Fehler werden jetzt als ERROR (statt WARNING) geloggt, mit automatischem Retry (2 Versuche) und 200ms Verzoegerung fuer Order-Fill
- **CRITICAL: Daily Loss Limit in Trade Execution** — `can_trade()` wird jetzt direkt vor Orderplatzierung geprueft, nicht nur waehrend der Analyse
- **CRITICAL: Position Sizing Logik** — Vereinfacht: `asset_budget` wird immer direkt verwendet wenn gesetzt, unabhaengig von `position_size_percent`
- **HIGH: Weex Client Retry/Circuit Breaker** — Gleiche `@with_retry` und Circuit Breaker Logik wie Bitget hinzugefuegt (3 Versuche, Exponential Backoff)
- **HIGH: Stille `.catch(() => {})` im Frontend** — 14 leere Catch-Bloecke in 8 Dateien durch `console.error`-Logging ersetzt
- **HIGH: `dangerouslySetInnerHTML` in BotBuilder** — Durch sichere `<Trans>`-Komponente von react-i18next ersetzt
- **HIGH: Docker Image Pinning** — `prom/prometheus:v3.2.1` und `grafana/grafana:11.5.2` statt `:latest`
- **HIGH: X-Forwarded-For IP-Validierung** — IP-Format wird jetzt per Regex validiert, Fallback auf `request.client.host` bei ungueltigem Format
- **MEDIUM: Passwort-Komplexitaet** — Neues Passwort erfordert min. 8 Zeichen, 1 Grossbuchstabe, 1 Kleinbuchstabe, 1 Ziffer, 1 Sonderzeichen
- **MEDIUM: Account Lockout Eskalation** — Exponentielles Backoff: 15min, 30min, 60min, ... max 24h (statt fixer 15min)
- **MEDIUM: Health Check DB-Verifizierung** — `/api/health` prueft DB-Konnektivitaet mit `SELECT 1`, gibt 503 bei Fehler zurueck
- **MENTOR: TP/SL Failure Propagation** — `Order.tpsl_failed` Flag hinzugefuegt, trade_executor sendet Risk Alert bei fehlgeschlagenem TP/SL
- **MENTOR: IP-Validierung** — Regex durch `ipaddress.ip_address()` ersetzt fuer echte IPv4/IPv6-Validierung
- **MENTOR: Health Check Imports** — Module-Level Imports statt Function-Level fuer bessere Sichtbarkeit

### Geaendert
- **Orchestrator Kommentar** — Dokumentiert, warum `restore_on_startup()` keine Race Condition hat (laeuft vor API-Start)
- **Status-Endpoint Version** — `/api/status` und `/api/health` zeigen jetzt korrekt Version `3.0.0`

### Hinzugefuegt
- **36 neue Tests** — `test_production_hardening.py` mit Integration/Unit-Tests fuer alle Hardening-Fixes:
  - Path Traversal (HTTP-Integration), can_trade Guard (Denial + Allow), TP/SL Failure Propagation,
  - Lockout Eskalation (8 parametrisierte Faelle), Passwort-Komplexitaet (6 Faelle),
  - IP-Validierung (9 Faelle inkl. IPv4/IPv6/Garbage), Health Check DB (200 + 503),
  - Weex Circuit Breaker (Registrierung, Fehler, Bypass)

---

## [3.16.0] - 2026-02-22

### Hinzugefuegt
- **PostgreSQL Support:** docker-compose.yml enthaelt PostgreSQL 16 Alpine als Produktionsdatenbank mit Healthcheck und benanntem Volume
- **SPA Catch-All Routing:** FastAPI serviert index.html fuer alle Frontend-Routen — Seitenaktualisierung auf /settings etc. funktioniert jetzt korrekt
- **.env.example:** PostgreSQL- und Grafana-Konfiguration dokumentiert

### Geaendert
- **DateTime Timezone:** Alle DateTime-Spalten verwenden jetzt `DateTime(timezone=True)` fuer PostgreSQL-Kompatibilitaet (verhindert offset-naive vs offset-aware Fehler)
- **Dockerfile:** `--legacy-peer-deps` fuer npm, `NODE_OPTIONS=--max-old-space-size=1536` fuer speicherbeschraenkte Builds, korrekter Frontend-Output-Pfad
- **docker-compose.yml:** CPU-Limit auf 0.90 (1-vCPU-Droplet), Grafana nur auf localhost gebunden, Passwort ueber Umgebungsvariable, trading-bot haengt von postgres ab
- **Settings:** Referral-Registrierung fuer Admin-Benutzer ausgeblendet

---

## [3.15.2] - 2026-02-21

### Hinzugefuegt
- **Backtest-Ergebnisse BTC:** Vollstaendige Ergebnisse aller 42 Backtests als Markdown (DE + EN) in Anleitungen/
- **Strategie-Empfehlungen:** Backtest-basierte Hinweise in jeder Strategiebeschreibung (i18n DE + EN) mit Disclaimer
- **Portfolio Exchange-Merge:** Exchange-Karten zeigen nun alle Exchanges (auch ohne Trades, z.B. nur mit Live-Balance)
- **OfflineIndicator i18n:** Banner-Texte uebersetzt (DE/EN), Dismiss-Button hinzugefuegt

### Geaendert
- **Token-Refresh ohne Rotation:** `token_version` wird beim Refresh nicht mehr inkrementiert — verhindert ungewollte Logouts bei mehreren Tabs/Requests
- **OfflineIndicator weniger aggressiv:** 3 statt 2 konsekutive Fehler, 30s Intervall, 8s Timeout, 5s Verzoegerung beim Start, gelbes statt rotes Banner
- **Portfolio Donut-Chart:** Tooltip zeigt jetzt Exchange-Name + formatierte Zahl; Farben sind Exchange-spezifisch statt Index-basiert
- **GettingStarted Timeframes:** Empfohlene Intervalle aktualisiert basierend auf Backtest-Daten (Edge: 1h/4h, Degen: 4h, Liquidation: 15m)
- **Settings Hyperliquid-Tab:** User-Status-Karten (Builder Code, Empfehlung) entfernt — nur Admin-relevante Inhalte (Earnings, Konfiguration) bleiben

### Behoben
- **Auth Token-Rotation Bug:** Refresh inkrementierte token_version, was parallele Requests und Multi-Tab-Sessions sofort invalidierte

---

## [3.15.1] - 2026-02-21

### Hinzugefuegt
- **Portfolio In-Memory Cache:** 10s TTL-Cache fuer `/positions` und `/allocation` Endpoints — wiederholte Aufrufe werden sofort bedient
- **Portfolio Cache Tests:** 4 Unit-Tests fuer Cache-Logik (hit, miss, TTL-Ablauf, Key-Isolation)

### Geaendert
- **Portfolio progressive Loading:** Schnelle DB-Queries (Summary, Daily) laden sofort, Exchange-API-Calls (Positions, Allocation) im Hintergrund mit eigenem Spinner
- **Settings resilientes Laden:** `Promise.allSettled` statt `Promise.all` — einzelne API-Fehler blockieren nicht mehr die gesamte Seite
- **Settings Verbindungen-Tab:** Nur noch fuer Admins sichtbar, nicht mehr in der User-Ansicht
- **OfflineIndicator robuster:** Erfordert 2 aufeinanderfolgende Fehler bevor Banner erscheint, Pruefintervall von 30s auf 15s verkuerzt
- **Axios Timeout:** 15s globaler Timeout hinzugefuegt um endloses Haengen zu verhindern

---

## [3.15.0] - 2026-02-21

### Hinzugefuegt
- **Englische Anleitungen:** Alle 13 Guides vollstaendig ins Englische uebersetzt (Anleitungen/en/)
- **Anleitungen-Index:** README.md mit Links zu allen Guides (DE + EN)
- **PDF-Export Template:** generate-pdf.html mit Trading Department Branding
- **Professional README.md:** GitHub-Uebersicht komplett neu geschrieben

### Entfernt
- **execute_signal.py geloescht:** Deprecated Datei die geloeschtes TradingBot-Modul referenzierte
- **_write_test.js geloescht:** Temporaeres Test-Generator-Skript
- **35 __pycache__ Verzeichnisse bereinigt**
- **9 stale Remote-Branches geloescht**

### Geaendert
- **.gitignore/.dockerignore:** .ruff_cache/ hinzugefuegt

---

## [3.14.1] - 2026-02-21

### Sicherheit
- **Login Rate Limit verschaerft:** Von 10/min auf 5/min fuer Brute-Force-Schutz
- **Exchange-Test Rate Limit verschaerft:** Von 10/min auf 3/min
- **SQL Injection Fix:** Migration-Code verwendet jetzt Whitelist-validierte Identifier mit Quoting

---

## [3.14.0] - 2026-02-21

### Sicherheit
- **Account Lockout:** 5 fehlgeschlagene Login-Versuche sperren Account fuer 15 Minuten
- **WebSocket token_version Pruefung:** WS-Verbindungen pruefen jetzt Token-Revocation gegen DB
- **Passwort-Aenderung Endpoint:** PUT /api/auth/change-password mit Rate-Limiting (3/min), revoziert bestehende Tokens
- **passlib entfernt:** Ungenutzte Dependency entfernt (bcrypt wird direkt verwendet)

### Hinzugefuegt
- **BotStatus/ExchangeType/TradeStatus/TradeSide Enums:** Typ-sichere String-Enums statt Magic Strings
- **MAX_BOTS_PER_USER Enforcement:** Orchestrator begrenzt auf 10 laufende Bots pro User
- **TradeCloserMixin:** Gemeinsame Trade-Close-Logik aus position_monitor und rotation_manager extrahiert
- **API Error Utility:** Zentrales `getApiErrorMessage()` fuer Frontend Error-Handling
- **Skip-to-Content Link:** Accessibility-Verbesserung im AppLayout
- **ChangePasswordRequest Schema:** Pydantic-Schema mit min_length=8 Validierung

### Behoben
- **164x datetime.utcnow() ersetzt:** Alle Vorkommen durch datetime.now(timezone.utc) ersetzt (47 Dateien)
- **Timezone-aware Subtraction Fix:** Naive/aware datetime Mismatch in trades.py und trade_closer.py behoben
- **Hardcoded German Strings:** ~20 deutsche Fallback-Strings in BotBuilder durch i18n-Keys ersetzt
- **Dashboard Tests geloescht:** Tests fuer geloeschte legacy Dashboard-Module entfernt

### Entfernt
- **Legacy Module geloescht:** trading_bot.py, trade_database.py, src/dashboard/, src/websocket/ (ersetzt durch FastAPI + Exchange-WS)
- **Legacy Tests geloescht:** 12 Test-Dateien fuer geloeschte Module entfernt

### Geaendert
- **Exchange Factory:** Verwendet jetzt ExchangeType Enum statt String-Vergleiche
- **BotWorker/Orchestrator:** Verwendet jetzt BotStatus Enum statt Magic Strings
- **main.py --dashboard:** Startet jetzt FastAPI statt legacy Dashboard

---

## [3.13.0] - 2026-02-21

### Sicherheit
- **python-jose durch PyJWT ersetzt:** python-jose ist unmaintained mit bekannten CVEs — Migration auf PyJWT[crypto] v2.11+
- **WebSocket JWT-Token nicht mehr in URL:** Token wird jetzt als erste Nachricht nach Connect gesendet, nicht mehr als Query-Parameter (verhindert Log-Exposure)
- **Login Rate Limit verschaerft:** Von 30/min auf 10/min reduziert

### Behoben
- **Frontend Build repariert:** Unused `INTERVAL_BACKTEST_HINTS` Konstante entfernt (blockierte `tsc`)
- **13 failing Frontend-Tests gefixt:** ErrorBoundary i18n-Mock + Portfolio Test-Stabilisierung
- **54 failing Backend-Tests gefixt:** Integration-Test Fixture-Mismatch (DB Engine), Affiliate-Router fehlte, seed_exchanges Mock, FundingPayment Schema
- **CircuitBreakerError:** Doppelter `super().__init__()` Aufruf entfernt
- **Silent Exception Swallowing:** `except Exception: pass` in exchange factory durch Logging ersetzt
- **aiohttp Session Leak:** Context Manager Support fuer LLM Provider hinzugefuegt
- **_signal_degen TypeError:** Fehlender `history` Parameter in zweiter Definition ergaenzt
- **50+ Test-Lint-Fehler behoben:** E741, F841, E402, F401 in 28 Test-Dateien

### Geaendert
- **CI linted jetzt auch tests/:** `ruff check src/ tests/` statt nur `src/`
- **Hardcoded German String entfernt:** `'Speichern fehlgeschlagen'` durch `t('common.saveFailed')` ersetzt
- **Leere Komponentenverzeichnisse entfernt:** `components/bot/` und `components/exchanges/`

---

## [3.12.1] - 2026-02-21

### Behoben
- **CI-Pipeline repariert:** 134 ruff-Lint-Fehler behoben (unused imports, E402, E712, E741, E731, F821, F841, F811)
- **Doppelte Methoden entfernt:** 6 duplizierte Funktionen in `MarketDataFetcher` (calculate_atr, calculate_ema, calculate_adx, calculate_macd, calculate_rsi, detect_rsi_divergence)
- **Undefined Name Bugs:** `BacktestResult` und `history` Referenzen in backtest engine korrigiert
- **SQLAlchemy Best Practices:** `== True` Vergleiche durch `.is_(True)` ersetzt
- **Test fix:** `test_date_range.py` nutzte Kline-Strategy-Pfad der in CI wegen Binance Geo-Block (HTTP 451) fehlschlug — auf Data-Pfad umgestellt

---

## [3.13.0] - 2026-03-03

### WhatsApp-Benachrichtigungen, Bitunix & BingX Exchange-Integration

Drei grosse Features in einem Release: WhatsApp als dritter Benachrichtigungskanal, zwei neue Exchanges (Bitunix, BingX) mit komplettem Full-Stack-Support, und erweiterter Affiliate-Bereich.

#### Hinzugefuegt

**WhatsApp Business Cloud API Notifier**
- **`src/notifications/whatsapp_notifier.py`** — Neuer `WhatsAppNotifier` ueber Meta Graph API v21.0
- Alle 8 Standard-Methoden: `send_trade_entry`, `send_trade_exit`, `send_daily_summary`, `send_risk_alert`, `send_bot_status`, `send_alert`, `send_error`, `send_test_message`
- Async Context Manager mit `aiohttp.ClientSession` und Bearer-Token-Auth
- `@async_retry` mit exponentiellem Backoff fuer 429/5xx-Fehler
- Per-Bot WhatsApp-Konfiguration: `whatsapp_phone_number_id`, `whatsapp_access_token`, `whatsapp_recipient` (verschluesselt in DB)
- `POST /api/bots/{id}/test-whatsapp` — Test-Endpoint fuer WhatsApp-Konfiguration
- `NotificationsMixin._get_notifiers()` um WhatsApp erweitert

**Bitunix Exchange Client**
- **`src/exchanges/bitunix/`** — Komplettes Client-Package (Futures REST API v1)
- `BitunixClient(ExchangeClient)` mit allen 12 ABC-Methoden + 4 optionalen Fee-Methoden
- Zwei-Stufen SHA256 Signatur (nonce + timestamp + apiKey + params + body)
- Circuit Breaker und Retry mit Backoff
- `constants.py` mit 28 Endpoint-Pfaden, Base-URL `https://fapi.bitunix.com`

**BingX Exchange Client**
- **`src/exchanges/bingx/`** — Komplettes Client-Package (Perpetual Swap V2/V3)
- `BingXClient(ExchangeClient)` mit allen 12 ABC-Methoden + 4 optionalen Fee-Methoden
- HMAC-SHA256 Auth via `X-BX-APIKEY` Header, Signatur als Query-Parameter
- Demo-Modus ueber VST-Domain (`open-api-vst.bingx.com`)
- Symbol-Format: `BTC-USDT` (mit Bindestrich)
- `constants.py` mit 30+ Endpoints, Error Codes, Order/Position/Margin Types

**Exchange-Logos**
- `BitunixLogo` SVG-Component (Markenfarbe #B9F641)
- `BingXLogo` SVG-Component (Markenfarbe #2954FE)
- `ExchangeIcon` und `ExchangeLogo` um Bitunix/BingX erweitert

**Backend-Integration (Full-Stack)**
- `Exchange Factory`: `create_exchange_client()` und `get_exchange_info()` um bitunix/bingx erweitert
- `DB Models`: `BotConfig` um 3 WhatsApp-Felder erweitert, alle `exchange_type`-Kommentare aktualisiert
- `Pydantic Schemas`: Exchange-Type-Regex auf 5 Exchanges erweitert, WhatsApp-Felder in Create/Update/Response
- `API Endpoints`: Ping-URLs, Config-Validation, Bot-CRUD um neue Exchanges erweitert
- `Affiliate System`: `VALID_EXCHANGES` und `UID_VALIDATORS` um bitunix/bingx erweitert
- `Bot Lifecycle`: Affiliate-Gate-Checks um bitunix/bingx erweitert
- `Symbol Map`: Mappings und Konvertierungslogik fuer bitunix (BTCUSDT) und bingx (BTC-USDT)
- `ExecutionSimulator`: Fee Schedules fuer bitunix (0.06%/0.02%) und bingx (0.04%/0.02%)
- `Exchange Seeding`: `_seed_exchanges()` um bitunix/bingx erweitert

**Frontend-Integration**
- `BotBuilder.tsx`: Exchanges-Array, BingX-Pairs, WhatsApp-Felder (Step 4), Trading-Pair-Konvertierung
- `BotDetail.tsx`: WhatsApp-Status-Anzeige, Test-Buttons fuer Telegram/WhatsApp
- `Settings.tsx`: Affiliate-Link-Verwaltung fuer 5 Exchanges (dynamisch)
- `Portfolio.tsx`: Exchange-Farben fuer bitunix/bingx
- `GettingStarted.tsx`: Setup-Cards, Prerequisite-Banner, Vergleichstabelle fuer neue Exchanges
- `i18n`: Alle WhatsApp- und Exchange-Keys in de.json und en.json

**Tests**
- `test_whatsapp_notifier.py` — 14 Tests (Init, Context Manager, Session, Messages, alle Notification-Methoden)
- `test_bitunix_client.py` — 19 Tests (Init, Auth, Balance, Ticker, Funding, Leverage, Positions, Orders, Constants)
- `test_bingx_client.py` — 22 Tests (Init, Demo-Mode, Auth, Balance, Ticker, Funding, Leverage, Positions, Orders, Constants)
- Bestehende Tests aktualisiert: Exchange Factory (5 statt 3), Symbol Map (Bitunix/BingX), Bot Worker (WhatsApp), Seed Exchanges

---

## [3.12.0] - 2026-02-20

### Freie Datumswahl im Backtesting (Option A)

**Problem geloest:** Der Backtest-Fetcher holte historische Daten immer ab "heute rueckwaerts". Nutzer konnten keine beliebigen historischen Zeitraeume (z.B. Jan 2024 bis Maerz 2024) testen — es wurden immer die letzten N Tage verwendet.

**Loesung:** Komplette Date-Range-Unterstuetzung durch den gesamten Stack: Frontend → API → Strategy-Adapter → HistoricalDataFetcher.

#### Hinzugefuegt
- **`HistoricalDataFetcher.set_date_range(start_date, end_date)`** — Setzt den Datumbereich fuer alle Sub-Fetcher (Binance, CoinGecko, Alternative.me, etc.)
- **`_get_time_range_ms(days)`** — Helper der start_ms/end_ms aus Datumbereich oder Fallback (now-days) berechnet
- **`_cache_suffix()`** — Cache-Keys enthalten jetzt den Datumbereich, damit verschiedene Perioden unabhaengig gecacht werden
- **`GET /api/backtest/date-limits`** — Neuer API-Endpoint der Timeframe-spezifische Limits zurueckgibt
- **Timeframe-spezifische Validierung** im Backend:
  - 1m: max. 7 Tage
  - 5m: max. 30 Tage
  - 15m: max. 90 Tage
  - 30m: max. 180 Tage
  - 1h/4h/1d: max. 365 Tage
  - Fruehestes Datum: 01.01.2020 (Binance Futures Start)
  - Kein Enddatum in der Zukunft
- **DatePicker min/max Constraints** — Deaktiviert Tage ausserhalb des erlaubten Bereichs
- **Frontend-Validierung** — Zeigt Timeframe-Limit-Info und Fehlermeldungen in Echtzeit
- **i18n-Keys** fuer de.json und en.json (dateLimitInfo, dateLimitExceeded, dateBeforeEarliest, dateFuture)
- **13 neue Tests** (`tests/backtest/test_date_range.py`) — Date-Range-Helpers, API-Validierung, Adapter-Propagation, Integration

#### Geaendert
- `HistoricalDataFetcher.__init__()` speichert `_start_ms` und `_end_ms` Attribute
- Alle 11 Sub-Fetcher verwenden `_get_time_range_ms()` statt `datetime.now() - timedelta(days)`
- `strategy_adapter.run_backtest_for_strategy()` berechnet `fetch_start` (mit Warmup-Buffer) und `fetch_end`, uebergibt sie an den Fetcher
- `BacktestRunRequest` API-Validation prueft Datumgrenzen und Timeframe-Limits
- Cache-Keys aller Sub-Fetcher enthalten optionalen Datums-Suffix fuer Range-Caching

#### Timeframe-Limit-Matrix
| Timeframe | Max. Tage | Candles (30d) | Grund |
|---|---|---|---|
| 1m | 7 | 10.080 | Extrem viele Datenpunkte |
| 5m | 30 | 8.640 | Viele Datenpunkte, API-Pagination |
| 15m | 90 | 8.640 | Moderate Datenmenge |
| 30m | 180 | 8.640 | Moderate Datenmenge |
| 1h | 365 | 8.760 | Gute Balance |
| 4h | 365 | 2.190 | Wenig Datenpunkte |
| 1d | 365 | 365 | Minimale Datenmenge |

---

## [3.11.0] - 2026-02-20

### ExecutionSimulator — Realistische Handelskosten im Backtest

**Problem geloest:** Das Backtest-Kostenmodell verwendete fest kodierte Werte (Slippage 0.03%, Fees 0.04%×2, Funding 1/3-Wahrscheinlichkeit), die erheblich von den tatsaechlichen Live-Trading-Kosten abwichen. Insbesondere wurden Funding-Kosten bei Mehrtages-Positionen um Faktor 9× unterschaetzt.

**Loesung:** Neuer `ExecutionSimulator` der die Exchange-Ausfuehrungsschicht 1:1 nachbildet.

#### Hinzugefuegt
- **`ExecutionSimulator`** (`src/backtest/execution_simulator.py`) — Professionelles Kostenmodell:
  - **Volatilitaets-basierte Slippage**: `slip = base + factor × (high-low)/close` statt fester 0.03%. Ruhiger Markt (0.2% Range) = 0.02% Slippage, volatiler Markt (3% Range) = 0.16%.
  - **Exchange-spezifische Fees**: Bitget Taker 0.06%, Hyperliquid 0.035%, Binance 0.04% — statt pauschaler 0.04%. Unterstuetzt VIP-Tiers und Hyperliquid Builder-Fee.
  - **Exakte 8h-Funding-Windows**: Zaehlt praezise wie viele 00:00/08:00/16:00 UTC-Grenzen eine Position kreuzt. Ersetzt die alte Heuristik (Intraday: rate×0.33, Multi-Day: rate×1) die Funding massiv unterschaetzte.
- **`entry_timestamp` und `entry_candle_range`** in `BacktestTrade` — Speichert Einstiegszeitpunkt und Candle-Volatilitaet fuer praezise Kostenberechnung beim Schliessen.
- **`_close_trade_simulated()`** in `BacktestEngine` — Schliesst Trades ueber den ExecutionSimulator. Automatisch aktiviert im Unified Mode, Legacy Mode bleibt unveraendert.
- **Exchange-Parameter** (`exchange`, `fee_tier`) in Strategy-Adapter — Konfigurierbar ueber `strategy_params`.
- **48 neue Tests** (`tests/backtest/test_execution_simulator.py`) — Slippage-Modell, Fee-Modell, Funding-Windows, Complete PnL, Old-vs-New-Vergleich.

#### Geaendert
- `BacktestEngine._close_trade()` prueft auf vorhandenen ExecutionSimulator und delegiert automatisch.
- `BacktestEngine.run_unified()` speichert Entry-Timestamp und Entry-Candle-Range auf jedem Trade, uebergibt Exit-Candle beim Schliessen.
- `strategy_adapter._run_unified_backtest()` erstellt automatisch einen ExecutionSimulator (Standard: Bitget).

#### Kostenvergleich Alt vs. Neu
| Kosten | Alt (fest) | Neu (ExecutionSimulator) |
|---|---|---|
| Slippage | 0.03% pauschal | 0.02%-0.16% je nach Volatilitaet |
| Fees (Bitget) | 0.08% RT | 0.12% RT (realer Taker-Satz) |
| Fees (Hyperliquid) | 0.08% RT | 0.07% RT |
| Funding (3-Tage-Hold) | rate × 1.0 | rate × 9.0 (9 Windows) |
| Funding (Intraday) | rate × 0.33 | rate × 0 oder 1 (exakt) |

---

## [3.10.0] - 2026-02-20

### Unified Backtest Architecture — Live Strategy Code wiederverwenden

**Problem geloest:** Bisher war jede Strategie DOPPELT implementiert — einmal fuer Live-Trading und einmal als Kopie im Backtest-Engine. Das fuehrte zu 5-50% Abweichung zwischen Backtest- und Live-Ergebnissen.

**Loesung:** Dependency Injection. Der Backtest ruft jetzt den **exakt gleichen** Strategy-Code auf wie das Live-Trading, nur mit historischen Daten statt API-Calls.

#### Hinzugefuegt
- **`BacktestMarketDataFetcher`** (`src/backtest/backtest_data_provider.py`) — Drop-in Replacement fuer `MarketDataFetcher`, das historische Daten im Binance-API-Format zurueckgibt. Erbt alle statischen Indicator-Methoden (EMA, RSI, ADX, etc.).
- **`BacktestEngine.run_unified()`** — Neue async Methode, die Live-Strategy-Code mit Mock-Daten ausfuehrt. Gleiche Position-Management-Logik wie `run()` (TP/SL, Fees, Slippage, Daily Limits, Next-Candle-Open Entry).
- **Unified Mode im Strategy Adapter** — Nicht-LLM-Strategien (EdgeIndicator, ClaudeEdgeIndicator, SentimentSurfer, LiquidationHunter) nutzen automatisch den Unified Mode. LLM-Strategien (Degen, LLMSignal) fallen auf den Legacy Mode zurueck.
- **Timeframe-Synchronisation** — `kline_interval` wird automatisch auf das Backtest-Timeframe gesetzt, damit Strategien Klines im korrekten Interval anfordern.
- **`data_fetcher` Parameter** fuer Degen und LLMSignal Strategien (Vorbereitung fuer zukuenftigen Unified-Support).
- **Umfangreiche Tests** (`tests/backtest/test_unified_backtest.py`) — Kline-Format, MarketMetrics, alle Timeframes, Legacy-Fallback, Constructor-Kompatibilitaet.

#### Erwartete Genauigkeitsverbesserung
| Strategie | Vorher (Kopie) | Nachher (Unified) |
|---|---|---|
| EdgeIndicator | ~95% | ~99% |
| ClaudeEdgeIndicator | ~85% | ~97% |
| SentimentSurfer | ~70% | ~95% |
| LiquidationHunter | ~90% | ~99% |
| Degen / LLMSignal | ~60% | ~60% (Legacy, LLM nicht wiederholbar) |

#### Behoben (Tests)
- **BacktestConfig `trading_fee_percent`** — Test erwartete 0.06 statt dem aktuellen Wert 0.04 (seit v3.9.0)
- **`btc_open`/`eth_open` in Tests** — Fehlende Pflichtfelder in `test_backtest_data.py`, `test_historical_data_extra.py`, `test_remaining_coverage.py` und `test_backtest_engine.py` ergaenzt
- **`_generate_signal()` Signatur** — `history` Parameter in Mock-Funktionen ergaenzt
- **Obsolete Strategie-Referenz** — `"contrarian"` durch `"liquidation_hunter"` ersetzt (6 Stellen)
- **Funding Rate Pagination Test** — Page-Size auf 1000 gesetzt damit Pagination ausgeloest wird
- **`_get()` Timeout-Test** — `aiohttp.ClientTimeout(total=30)` statt `timeout=30`
- **Encryption Test** — An aktuelle `_get_or_create_key()` Logik angepasst (kein `.env` File mehr, ephemerer Key)
- **Signal Reason Test** — An aktuelle Liquidation-Hunter 3-Schritt-Logik angepasst (Leverage + Sentiment statt OI + TopTraders)

#### Unveraendert
- `BacktestEngine.run()` bleibt vollstaendig erhalten (Legacy Mode)
- Alle `_signal_*()` Methoden in `engine.py` bleiben bestehen
- `KlineBacktestEngine` bleibt unveraendert
- Position Management (TP/SL, Fees, Slippage, Funding) bleibt identisch
- Frontend und API-Endpoints bleiben unveraendert

---

## [3.9.1] - 2026-02-20

### Backtest: Look-Ahead Bias eliminiert & Open-Price-Realismus

#### Behoben (Critical)
- **Look-Ahead Bias im Entry** — Backtest nutzte den Close-Preis des Signal-Candles als Entry-Preis. In der Realitaet kann man erst zum Open des NAECHSTEN Candles einsteigen. Jetzt: `next_candle.btc_open` statt `current_candle.btc_price`.
- **Funding Rate zu hoch bei Intraday-Trades** — Volle Daily-Funding-Rate auch fuer Trades die < 8h offen waren. Jetzt skaliert: Intraday = 33% der Funding-Rate (1/3 Chance eine Funding-Periode zu kreuzen), Multi-Day = 100%.
- **Mock-Daten ohne Open-Preis** — `btc_open`/`eth_open` fehlten in Mock-Daten. OHLC-Kontinuitaet: `next_candle.open == prev_candle.close` verifiziert.
- **Mock-Daten OHLC unrealistisch** — High/Low wurden nur vom Close abgeleitet. Jetzt: High = max(Open, Close) + Volatility, Low = min(Open, Close) - Volatility.

#### Hinzugefuegt
- `btc_open`/`eth_open` Felder in `HistoricalDataPoint` und Mock-Daten-Generator
- Open-Price Kontinuitaetstest fuer alle Timeframes (1d, 4h, 1h, 30m)

---

## [3.9.0] - 2026-02-20

### Backtest-Realismus: Produktions-reife Handels-Simulation

#### Behoben (Critical)
- **Funding Rate nie geladen** — Binance Funding Rate API wurde ohne `startTime` aufgerufen, lieferte Daten ab 2019 die alle rausgefiltert wurden. Funding-Kosten waren IMMER $0.00. Jetzt Forward-Pagination von `startTime`, 90+ Datenpunkte (3x/Tag).
- **Sentiment Surfer 0 Trades** — VWAP-Berechnung erforderte min. 7 Candles/24h, aber 4h-Candles liefern nur 6. News-Quelle (nicht verfuegbar im Backtest) wurde trotzdem im Agreement-Gate gezaehlt (3/6 statt 2/5). Beides gefixt.
- **Metrics inkonsistent mit Trade-Liste** — Metrics kamen vom gesamten Engine-Lauf inkl. Warmup-Trades. Jetzt Neuberechnung aus gefilterten Trades: PnL, Win Rate, Drawdown, Equity Curve, Sharpe Ratio.
- **Profit Factor bei 0 Trades** — Zeigte 999.99 statt 0.0 an.

#### Hinzugefuegt (Realismus)
- **Slippage-Modell** — 0.03% pro Seite (Entry + Exit), realistisch fuer BTC/ETH Futures. Macht Backtest konservativer.
- **TP/SL Same-Candle: Konservativ** — Wenn TP und SL im selben Candle getroffen werden, wird SL angenommen (Worst Case statt Best Case).
- **Binance-realistische Fees** — 0.04% Taker (vorher 0.06%) entspricht Binance Futures VIP0.

#### Geaendert
- **Equity Curve** — Startet jetzt mit User-Startkapital, nicht Engine-internem Kapital
- **Max Drawdown** — Wird nur aus gefilterten Trades berechnet
- **Funding Rate** — Jetzt als eigene Datenquelle (10 statt 9 Sources)

#### Verifizierte Strategien
Alle 6 Strategien generieren realistisch Trades mit Fees, Funding und Slippage:
| Strategie | Trades | Win Rate | Funding |
|---|---|---|---|
| Claude Edge Indicator | 15 | 53% | realistische Kosten |
| Edge Indicator | 35 | 37% | realistische Kosten |
| Sentiment Surfer | 7 | 43% | realistische Kosten |
| Liquidation Hunter | 33 | 36% | realistische Kosten |
| Degen | 7 | 14% | realistische Kosten |
| LLM Signal | 4 | 25% | realistische Kosten |

---

## [3.8.5] - 2026-02-20

### Code Quality & Type Safety (Review — Runde 5)

#### Behoben
- **Backtest Polling Stale setState** — Polling-Interval in `Backtest.tsx` konnte nach Unmount State-Updates ausloesen, jetzt `cancelled`-Flag verhindert veraltete Updates
- **Dashboard `as any` Casts** — Dynamische i18n-Keys `t(\`dashboard.days${p}\` as any)` durch typisierte `PERIOD_LABELS`-Map ersetzt
- **CORS-Logging zu laut** — `logger.info("CORS allowed origins: ...")` auf `logger.debug` reduziert (kein Spam in Production-Logs)

#### Verbessert (Type Safety)
- **`LlmConnection` Interface** — Neuer Typ in `types/index.ts` statt `useState<any[]>` in `BotDetail`, `BotPerformance`, `Bots`, `Settings`
- **`AdminUidEntry` Interface** — Typisiert statt `useState<any[]>` in `Settings.tsx`
- **`HlRevenueInfo` Interface** — Typisiert statt `useState<any>(null)` in `Settings.tsx`
- Alle `useState<any>` Deklarationen im Frontend durch typisierte Interfaces ersetzt

---

## [3.8.4] - 2026-02-20

### Frontend UX Fixes (Code Review)

#### Behoben (Critical)
- **WebSocket nie verbunden** — `useWebSocket.ts` las `localStorage.getItem('token')` statt `'access_token'`, Echtzeit-Benachrichtigungen waren komplett kaputt
- **Presets Duplicate/Delete ohne Error-Handling** — API-Fehler crashten ohne Feedback, jetzt try/catch + Toast
- **BotDetail fetchData nicht awaited** — Nach Start/Stop wurde Bot-Status nicht aktualisiert (Fire-and-forget), jetzt `await fetchData()`
- **BotPerformance Stale Closure** — `loadCompareData`/`loadBotDetail` schlossen ueber veralteten `demoParam`, jetzt `useCallback` mit korrekten Dependencies
- **BotDetail Bar in AreaChart** — `<Bar>` innerhalb von `<AreaChart>` (ungueltig), jetzt `<ComposedChart>` fuer korrektes Rendering

#### Behoben (i18n)
- **ErrorBoundary** — Hardcoded Englisch "Something went wrong" / "Try again" → `i18n.t()` mit `common.errorBoundaryTitle`/`common.tryAgain`
- **BotPerformance "Netto"** — Hardcoded Deutsch → `t('common.net')`
- **AdminUsers** — "Create", "Keine Benutzer vorhanden.", Placeholders (Username/Password/Email) waren nicht uebersetzt
- **BotDetail Fehlermeldung** — Hardcoded "Failed to load bot data" → `t('common.error')`
- **TaxReport t() Fallback** — Falscher Fallback-Syntax `t('key', 'default')`, Key `tax.downloadError` in beiden JSON-Dateien ergaenzt
- Neue i18n-Keys: `common.net`, `common.errorBoundaryTitle`, `common.tryAgain`, `admin.create`, `admin.noUsers`, `admin.usernamePlaceholder`, `admin.passwordPlaceholder`, `admin.emailPlaceholder`, `tax.downloadError`

---

## [3.8.3] - 2026-02-20

### Backtest Engine Fixes (Deep Code Review — Runde 2)

#### Behoben
- **Drawdown-Berechnung falsche Reihenfolge** — Drawdown wurde in Trade-Eroeffnungsreihenfolge statt nach Exit-Datum berechnet, jetzt chronologisch sortiert
- **Division by Zero bei starting_capital=0** — `_save_daily_stats` und `_close_trade` konnten bei Kapital=0 crashen, Guards eingefuegt
- **ETH VWAP nutzte BTC-Volumen** — Sentiment Surfer berechnete VWAP fuer ETH mit BTC-Handelsvolumen, neues `eth_volume` Feld eingefuegt
- **Liquidation Hunter ignorierte Config-Thresholds** — `crowded_longs`/`crowded_shorts` waren hardcoded (2.5/0.4) statt aus BacktestConfig (user-konfigurierbar)
- **O(N²) in _save_daily_stats** — Taegliche Fees/Funding wurden per O(N)-Scan ueber alle Trades berechnet, jetzt inkrementelle Akkumulatoren
- **bot_worker.stop() AttributeError** — `self._config.name` wurde ohne None-Guard aufgerufen, Crash bei fehlgeschlagener Initialisierung
- **Degen TP/SL Fallback auf entry_price** — TP und SL fielen auf `current_price` zurueck (sofortige Ausloesung), jetzt +3%/-2% Defaults

---

## [3.8.2] - 2026-02-20

### Architecture Fixes (Mentor Review — Runde 3)

#### Behoben
- **Encryption Key Auto-Write entfernt** — `_get_or_create_key()` schrieb Auto-Keys direkt in `.env` (Race Condition, unerwartete Datei-Mutation). Jetzt nur noch in-memory + Warning-Log
- **BotWorker Error→Running ohne Log** — Bot wechselte nach Cooldown von `error` zu `running` ohne Log-Eintrag, Debugging erschwert
- **WebSocket Exception Swallowing** — 3 Stellen (`orchestrator.py`, `trade_executor.py`, `position_monitor.py`) verschluckten WS-Fehler komplett (`except: pass`), jetzt `logger.debug()`
- **Stale Backtests nach Server-Restart** — Backtests im Status `pending`/`running` blieben nach Crash/Restart fuer immer haengen. Startup markiert sie jetzt als `failed`
- **AdminRoute Flash-Redirect** — Admin-Seite redirectete beim Page-Refresh sofort zu `/`, weil `user` noch nicht geladen war. Zeigt jetzt Loader bis `fetchUser()` abschliesst
- **Frontend Build brach wegen Test-Files** — `tsconfig.json` inkludierte Test-Dateien im Build-Check, fehlende vitest-Types blockierten `tsc`. Tests jetzt in `exclude`

---

## [3.8.1] - 2026-02-20

### Code Quality, Security & Bug Fixes (Mentor Review)

Umfassender Code-Review mit Fixes fuer 4 kritische, 9 wichtige und 2 kleinere Bugs plus Frontend/Security-Verbesserungen.

#### Behoben (Critical)
- **NameError in BacktestEngine** — `Any` fehlte im typing-Import, Engine-Instantiierung schlug fehl
- **Stale Worker State im Orchestrator** — `_stop_bot_locked` entfernte Worker nicht aus dem Dict, Memory Leak bei jedem Stop/Start-Zyklus
- **Kein HTTP-Timeout bei API-Requests** — `aiohttp` timeout als Integer statt `ClientTimeout`-Objekt, Requests konnten endlos haengen
- **HistoricalDataPoint.from_dict Crash** — Fehlende Pflichtfelder in Cache-Daten fuehrten zu TypeError statt klarer Fehlermeldung

#### Behoben (Major)
- **Loss Limit zu lasch** — Berechnung nutzte `starting_capital` statt aktuellen Tages-Startwert, Limit griff nicht bei geschrumpftem Konto
- **Profit-Lock-Feature kaputt** — `locked_profit` wurde berechnet aber nie verwendet, Verluste bis 87.5% statt 25% des Tagesgewinns erlaubt
- **O(n²) Memory bei Intraday-Backtests** — History-Slice wurde pro Candle komplett kopiert, jetzt auf 200 Candles begrenzt
- **Bot-Crash bei korrupter trading_pairs JSON** — `json.loads` ohne Error-Handling im Worker und Status-Endpoint
- **Warmup-Candles verworfen** — Strategy Adapter filterte Warmup-Daten vor Engine-Run, Indikatoren hatten keine Initialisierung
- **Supertrend Boundary Guard** — `close_idx` konnte Array-Grenzen ueberschreiten
- **Pagination-Endlosschleifen** — 5 API-Pagination-Loops hatten keinen Iterations-Cap und keinen Fortschritts-Check
- **Exchange-Seeding nicht idempotent** — Neue Exchanges (z.B. Weex) wurden nie eingefuegt wenn bereits ein Exchange existierte

#### Behoben (Minor)
- **ETH Mock-Daten unrealistisch** — ETH-Preis hatte keinen persistenten State, jetzt eigener Random Walk
- **json.loads in get_status_dict** — Fehlende Error-Behandlung im Bot-Status-Endpoint

#### Behoben (Security)
- **SQL Injection in session.py** — f-String mit Environment-Variable in SQL-Query, ersetzt durch gebundenen Parameter (`:rate`)
- **console.error in Production** — ErrorBoundary loggte Stack-Traces in Browser-Console, jetzt nur noch in DEV-Modus
- **i18n-Keys fehlend** — `proModeParamsHint` und `proModeParamsActiveHint` in de.json und en.json ergaenzt
- **Dashboard Animation Stale Closure** — AnimatedNumber nutzte veralteten Display-Wert bei schnellen Updates, jetzt via useRef
- **Dashboard useEffect Dependency** — `t` fehlte in Dependency-Array

#### Behoben (Security Audit — Runde 2)
- **Tax Report Endpoints ohne Auth** — 3 Endpoints (`/api/tax-report/years`, `/{year}`, `/{year}/download`) waren ohne Authentifizierung aufrufbar, `Depends(verify_api_key)` ergaenzt
- **innerHTML XSS im Dashboard** — Health-Check-Modal injizierte Server-Daten ohne Escaping, `escapeHtml()` Funktion eingefuegt
- **Health-Check leakt Exception-Details** — Unauthentifizierter `/api/health` Endpoint zeigte interne Fehlermeldungen, jetzt nur "healthy"/"unhealthy"
- **db.commit() fehlend bei Affiliate UID** — Aenderung wurde nur geflusht aber nie committed, ging beim Session-Ende verloren
- **db.commit() fehlend bei User-Loeschung** — Token-Revocation (token_version Increment) wurde nicht persistiert, geloeschte User blieben eingeloggt
- **Exception-Details in HTTP-Responses** — `str(e)` in 400-Antworten konnte interne Details leaken, ersetzt durch generische Meldung mit Server-Log
- **Rate Limiting auf Trades-Endpoint** — `GET /api/trades` hatte kein Rate Limit, jetzt 60/Minute
- **trading_pairs Input-Validation** — Keine Validierung auf Inhalt der Pair-Strings, jetzt Regex `^[A-Z0-9_-]{1,30}$`

---

## [3.8.0] - 2026-02-20

### Backtest Timeframe-Support

#### Hinzugefuegt
- Backtest unterstuetzt jetzt alle Zeitfenster (1m, 5m, 15m, 30m, 1h, 4h, 1d) — der Frontend Timeframe-Selector funktioniert jetzt wie vorgesehen
- Klines werden im gewaehlten Interval von Binance Futures geholt (mit Pagination fuer >1500 Candles)
- Taegliche Daten (FGI, L/S, OI, Taker, etc.) werden auf Intraday-Candles forward-gefuellt
- ETH-Klines werden per exaktem Timestamp statt Date gemappt (korrekte Intraday-Zuordnung)
- Backtest respektiert jetzt das gewaehlte Handelspaar (nur BTC oder ETH statt immer beide)
- Mock-Daten unterstuetzen Intraday-Generierung fuer Offline-Backtests
- Warmup-Buffer im Strategy Adapter stellt sicher, dass Indikatoren genug Candles zum Initialisieren haben

#### Behoben
- Backtest Timeframe-Parameter wurde ignoriert — Klines wurden immer als Daily (1d) geholt, Intraday-Strategien waren unmoeglich
- Edge Indicator / Claude Edge Indicator lieferten 0 Trades bei kurzen Zeitraeumen weil Daily-Candles fuer Indikator-Warmup nicht ausreichten
- ETH-Kline-Daten gingen bei Intraday-Intervallen verloren (mehrere Candles pro Tag auf einen kollabiert durch Date-Key Deduplizierung)

### Backtest Signal-Generatoren — Live-Matching Rewrite

Alle 4 nicht-KI Strategien im Backtest wurden komplett neu geschrieben, damit sie exakt die gleiche Logik wie ihre Live-Pendants verwenden.

#### Geaendert

- **Edge Indicator** — ADX-Multiplier von 1.5 auf 0.8 korrigiert (Live-Wert), ADX-Penalty nutzt `int()` statt `*1.2`, Score-Series mit EMA(3)-Smoothing fuer Regime-Erkennung, Regime-Flip wird durch Vergleich mit vorherigem Regime erkannt (nicht Entry-Crosses), Choppy-Market → Confidence = 0
- **Claude Edge Indicator** — Eigener Signal-Generator (war vorher identisch mit Edge Indicator), implementiert alle 6 Live-Enhancements: ATR-basierte TP/SL (ATR×2.5/ATR×1.5), Volume Confirmation via Taker Buy/Sell Ratio, HTF-Proxy ueber EMA 21/50, Trailing-Stop Metadata, Regime-basierte Positionsgroesse (0.5–1.0), RSI-Divergenz-Erkennung (+8/−10 Confidence)
- **Sentiment Surfer** — 6 Scoring-Quellen exakt wie Live: News (0, nicht verfuegbar), FGI (kontaer, threshold_distance×3), VWAP (deviation×2000), Supertrend (+70/−70 via eigener Berechnung), Volume ((buy_ratio−0.5)×400), Momentum (price_change×20/×15). Gewichte: news=1.0, fg=1.0, vwap=1.2, supertrend=1.2, volume=0.8, momentum=0.8. Gate: 3/6 Uebereinstimmung UND Confidence ≥ 40
- **Liquidation Hunter** — Von 11 Schritten auf 3 reduziert (Live-Logik): Leverage + Sentiment + Funding. Live-Schwellenwerte: crowded_longs=2.5, crowded_shorts=0.4, extreme_fear=20, extreme_greed=80, high_confidence_min=85, low_confidence_min=60

#### Hinzugefuegt

- **`_supertrend_direction()`** — Modul-Level Hilfsfunktion fuer Supertrend-Indikator-Berechnung (ATR-basiert mit Band-Tracking)
- **`_detect_rsi_divergence()`** — Erkennung von bullischen/baerischen RSI-Divergenzen ueber konfigurierbares Lookback-Fenster
- **`_build_score_series_backtest()`** — Baut Momentum-Score-Serie fuer EMA(3)-Smoothing (Predator Momentum Score: MACD Histogram + RSI Drift + Trend Bonus)
- **`_get_min_confidence()`** — Per-Strategie Mindest-Confidence: Edge/Claude Edge/Sentiment = 40, Liquidation Hunter = 60
- **`_signal_metadata`** — Neues Dict fuer strategie-spezifische TP/SL-Overrides und Positionsgroessen-Skalierung (genutzt von Claude Edge Indicator)
- **Signal-Dispatcher** — Separates Routing fuer `claude_edge_indicator` (war vorher auf `edge_indicator` gemappt)
- **24h-Preisaenderung aus Historie** — Sentiment Surfer berechnet echte 24h-Preisaenderung aus der Candle-Historie statt per-Candle `btc_24h_change` (korrektes Intraday-Verhalten)

#### Behoben

- Edge Indicator und Claude Edge Indicator lieferten identische Ergebnisse — Claude Edge hat jetzt eigenen Signal-Generator mit 6 zusaetzlichen Enhancements
- Sentiment Surfer erzeugte 0 Trades auf Intraday-Timeframes — `btc_24h_change` war per-Candle (±0.3% bei 30m) statt echte 24h-Aenderung (±2–5%)
- VWAP-Fenster war fuer Intraday zu klein (hardcoded 24 Candles) — jetzt dynamisch basierend auf `candles_24h`
- Liquidation Hunter nutzte 11 Schritte die in der Live-Strategie nicht existieren — reduziert auf die 3 echten Live-Schritte

### Bot-Lifecycle & Risk Notifications

#### Hinzugefügt
- **Bot-Start/Stop Notifications** via Discord & Telegram — beim Starten wird Name, Strategie und Modus gesendet, beim Stoppen eine Bestätigung
- **Error Notifications** bei 5+ aufeinanderfolgenden Fehlern — einmalig beim Übergang in den Error-Status (kein Spam bei jedem Zyklus)
- **Risk Alert Notifications** bei Trading-Halt durch Limit-Überschreitung — einmalig pro Halt-Grund pro Tag (global und per Symbol), Set wird täglich zurückgesetzt
- **Tägliche Zusammenfassung (Daily Summary)** um 23:55 UTC — automatischer Cron-Job sendet Tagesstatistiken (Trades, PnL, Win-Rate, Fees, Funding, Max Drawdown) via Discord & Telegram
- **Telegram `send_daily_summary()`** — neue HTML-formatierte Tagesübersicht mit Emoji-basiertem Layout
- **Telegram `send_risk_alert()`** — neue Risiko-Warnung mit Alert-Typ, Nachricht und optionalen Schwellenwerten

#### Behoben
- **Discord Notification Crash** — `send_bot_status`, `send_error`, `send_daily_summary` akzeptieren jetzt `**kwargs` für cross-notifier Kompatibilität (vorher TypeError bei unbekannten Parametern)
- **Telegram Status-Emoji** — case-insensitiver Vergleich (STARTED/STOPPED statt started/stopped)
- **Stop-Notification Reihenfolge** — wird jetzt VOR dem Client-Shutdown gesendet statt danach
- **Risk-Alert-Typ** — dynamisch `TRADE_LIMIT` vs. `DAILY_LOSS_LIMIT` je nach Halt-Grund (statt immer `DAILY_LOSS_LIMIT`)
- **Bot-Name in Telegram Daily Summary** — zeigt jetzt an, welcher Bot die Zusammenfassung sendet

### Alerts-Feature entfernt (verschoben auf späteres Release)

#### Entfernt
- **Gesamtes Alerts-System** temporär entfernt und als GitHub Issue für zukünftiges Feature angelegt
  - Backend: AlertEngine, Alert-Router, Alert-Schemas, Alert/AlertHistory DB-Modelle
  - Frontend: Alerts-Seite, Navigation, i18n-Keys, TypeScript-Typen
  - Tests: Alle Alert-bezogenen Unit-Tests
  - Orchestrator: AlertEngine-Integration und Bot-Alert-Trigger
- DB-Tabellen `alerts` und `alert_history` bleiben bestehen (keine destruktive Migration)

#### Behoben
- **KI-Bot Icon** wird jetzt bei allen KI-Strategien angezeigt (`llm_signal` und `degen`), nicht nur bei `llm_signal`
  - Betrifft: Bot-Karten, Bot-Detail, Bot-Builder, Bot-Performance
- **Umlaute in Strategie-Beschreibungen** — "ue"/"oe"/"ae" durch echte Umlaute (ü/ö/ä) ersetzt in allen 6 Strategien und BotBuilder-Fallback-Texten

#### Geändert
- **Strategie-Parameter auf Deutsch übersetzt** — alle Labels und Beschreibungen in den 6 Strategien (Edge Indicator, Claude Edge Indicator, Degen, KI-Companion, Sentiment Surfer, Liquidation Hunter) sind jetzt deutschsprachig
- **Kline Intervall Info-Hinweis** — bei Edge Indicator und Claude Edge Indicator wird im Kline-Intervall-Feld ein Tipp angezeigt, dass der Analyse-Takt (Zeitplan) nicht deutlich kürzer als das Kline Intervall sein sollte
- **Parameter-Beschreibungen sichtbar** — Descriptions werden jetzt als Text unter den Feldern angezeigt (statt nur als unsichtbarer Hover-Tooltip)
- **BotBuilder Fallback-Strings auf Deutsch** — alle englischen Fallback-Texte im BotBuilder durch deutsche ersetzt

---

## [3.7.0] - 2026-02-20

### Advanced Alerting, Multi-Exchange Portfolio, Technical Fixes, Docs & Tests

Grosses Feature-Update: Advanced Alerting System (Preis/Strategie/Portfolio Alerts mit Discord+Telegram),
Multi-Exchange Portfolio View (aggregiertes PnL ueber alle Exchanges), 5 technische Luecken behoben,
Dokumentation aktualisiert, und umfangreiche Test-Abdeckung fuer alle neuen Features.

#### Hinzugefuegt

##### Advanced Alerting System (Backend)

- **Datenbank-Modelle** (`src/models/database.py`):
  - Neues `Alert` Modell: user_id, bot_config_id (nullable), alert_type (price/strategy/portfolio),
    category, symbol, threshold, direction, is_enabled, cooldown_minutes, last_triggered_at, trigger_count
  - Neues `AlertHistory` Modell: alert_id, triggered_at, current_value, message (Audit-Trail)
  - Index `ix_alert_user_enabled` fuer schnelle Abfragen
  - SQLite-Migrationen fuer beide Tabellen in `src/models/session.py`

- **API Schemas** (`src/api/schemas/alerts.py`):
  - `AlertCreate` mit model_validator: Preis-Alerts erfordern symbol+direction, threshold > 0
  - `AlertUpdate` fuer partielle Aktualisierungen
  - `AlertResponse` und `AlertHistoryResponse` mit from_attributes

- **API Router** (`src/api/routers/alerts.py`):
  - `GET /api/alerts` — Liste aller Alerts (optional Filter by type)
  - `POST /api/alerts` — Alert erstellen (max 50 pro User)
  - `GET /api/alerts/{id}` — Alert Details
  - `PUT /api/alerts/{id}` — Alert aktualisieren
  - `DELETE /api/alerts/{id}` — Alert loeschen
  - `PATCH /api/alerts/{id}/toggle` — Aktivieren/Deaktivieren
  - `GET /api/alerts/history` — Globale Alert-History (letzte 50)
  - Rate Limit: 30/min auf Schreib-Endpoints

- **Alert Engine** (`src/bot/alert_engine.py`):
  - `AlertEngine` Klasse als Background Task im Orchestrator
  - `_check_price_alerts()`: Alle 60s, nutzt MarketDataFetcher, gruppiert nach Symbol
  - `_check_portfolio_alerts()`: Alle 5min, aggregiert Tages-PnL pro User
  - `_trigger_alert()`: Cooldown-Check, DB-Update, AlertHistory-Eintrag, Notification, WebSocket
  - `check_strategy_alerts()`: Inline-Funktion fuer BotWorker (low_confidence, consecutive_losses, signal_missed)

- **Notification Erweiterung**:
  - `DiscordNotifier.send_alert()` — Eigene Embed-Farbe `COLOR_ALERT = 0xFF6600` (Orange),
    typspezifische Emojis (Preis, Strategie, Portfolio)
  - `TelegramNotifier.send_alert()` — HTML-formatierte Alert-Nachrichten

- **Orchestrator Integration** (`src/bot/orchestrator.py`):
  - AlertEngine startet in `restore_on_startup()`, stoppt in `shutdown_all()`

##### Multi-Exchange Portfolio View (Backend)

- **API Schemas** (`src/api/schemas/portfolio.py`):
  - `ExchangeSummary`, `PortfolioSummary`, `PortfolioPosition`, `PortfolioAllocation`, `PortfolioDaily`

- **API Router** (`src/api/routers/portfolio.py`):
  - `GET /api/portfolio/summary?days=30` — Aggregiertes PnL gruppiert nach Exchange
  - `GET /api/portfolio/positions` — Live Positionen von allen verbundenen Exchanges (parallel, 10s Timeout)
  - `GET /api/portfolio/daily?days=30` — Taegliche PnL-Aufschluesselung pro Exchange
  - `GET /api/portfolio/allocation` — Balance-Verteilung pro Exchange

- **Exchange Factory** (`src/exchanges/factory.py`):
  - Neue Funktion `get_all_user_clients(user_id, db)` — Erstellt Client-Instanzen fuer alle verbundenen Exchanges

##### Alerts Frontend

- **Alerts-Seite** (`frontend/src/pages/Alerts.tsx`):
  - Drei Tabs: Preis, Strategie, Portfolio (plus "Alle") zum Filtern
  - Alert-Liste mit Toggle On/Off und Loeschen
  - Erstellungs-Dialog mit typspezifischen Feldern (Symbol, Schwellenwert, Richtung, Cooldown)
  - Verlaufs-Sektion mit den letzten 20 ausgeloesten Alerts
  - Live WebSocket-Unterstuetzung fuer `alert_triggered` Events

##### Portfolio Frontend

- **Portfolio-Seite** (`frontend/src/pages/Portfolio.tsx`):
  - Header mit Gesamtguthaben und Tages-PnL (farbkodiert)
  - Exchange-Karten (Bitget=Blau, Hyperliquid=Gruen, Weex=Orange)
  - Gestapeltes Flaechendiagramm: Taeglicher PnL pro Exchange (Recharts AreaChart)
  - Positionstabelle: sortierbar nach PnL, alle Exchanges
  - Allokations-Donut (Recharts PieChart)
  - Periodenwahl (7/14/30/90 Tage)

##### Navigation & Routing

- **Routing** (`frontend/src/App.tsx`): Lazy-Imports und Routen fuer `/portfolio` und `/alerts`
- **Navigation** (`frontend/src/components/layout/AppLayout.tsx`): Portfolio (Briefcase) und Alerts (Bell) Links
- **TypeScript Interfaces** (`frontend/src/types/index.ts`): Alert, AlertHistory, AlertCreate,
  PortfolioSummary, ExchangeSummary, PortfolioPosition, PortfolioDaily, PortfolioAllocation
- **i18n** (`frontend/src/i18n/de.json` + `en.json`): ~70 neue Keys fuer alerts.* und portfolio.* Namespaces

##### Technical Fixes

- **Affiliate UID Verification** (`src/api/routers/affiliate.py`):
  - `POST /api/affiliate-links/verify-uid` — Validiert UID-Format (Bitget: numerisch, Weex: alphanumerisch)
  - Setzt `affiliate_verified = True` in ExchangeConnection
- **Affiliate UID Gate** (`src/bot/hyperliquid_gates.py`):
  - Blockiert Bot-Start wenn UID nicht verifiziert
- **AI Module Exports** (`src/ai/__init__.py`):
  - Vollstaendige `__all__` mit BaseLLMProvider, PROVIDER_REGISTRY, MODEL_CATALOG, etc.

##### Tests

- **Backend Tests (15 neue Dateien)**:
  - `tests/unit/api/test_alerts_router.py` — 15 Tests: CRUD, Toggle, Filter, Validierung, Auth
  - `tests/unit/api/test_portfolio_router.py` — 9 Tests: Summary, Positions, Daily, Allocation
  - `tests/unit/api/test_affiliate_verification.py` — 9 Tests: UID-Format, Verification Flow
  - `tests/unit/api/test_funding_case_fix.py` — 8 Tests: func.case Kompatibilitaet
  - `tests/unit/bot/test_alert_engine.py` — 18 Tests: Lifecycle, Price/Portfolio/Strategy Checks, Cooldown, Trigger
  - `tests/unit/test_alert_notifications.py` — 12 Tests: Discord/Telegram Alert Formatierung
  - `tests/unit/test_claude_edge_backtest.py` — 6 Tests: HTF Sync/Async Routing, Backtest-Modus

- **Frontend Tests (2 neue Dateien)**:
  - `frontend/src/pages/__tests__/Alerts.test.tsx` — 10 Tests: Render, Tabs, Create Modal, Alerts Display
  - `frontend/src/pages/__tests__/Portfolio.test.tsx` — 10 Tests: Render, Summary, Exchange Cards, Positions, Charts

##### Dokumentation

- **docs/API.md** — Komplett neu geschrieben mit allen aktuellen Endpoints
- **docs/FAQ.md** — Aktualisiert fuer v3.7.0 Features
- **docs/STRATEGY.md** — Alle 6 Strategien dokumentiert
- **6 neue Anleitungen** in `Anleitungen/`:
  - Backtesting, LLM Provider, Alerts, Portfolio, Strategien, Weex Setup

#### Geaendert

- **ClaudeEdge Backtest Fix** (`src/strategy/claude_edge_indicator.py`):
  - `backtest_mode=False` Parameter: nutzt `_check_htf_alignment_sync()` im Backtest-Modus

#### Behoben

- **SQLAlchemy `case()` Workarounds entfernt** — `pytest.skip()` Workarounds in Tests entfernt

#### Entfernt / Verschoben

- **Legacy Test Cleanup**:
  - `tests/test_auth.py` geloescht (redundant)
  - `tests/test_bots.py`, `test_statistics.py`, `test_trades.py` nach `tests/integration/` verschoben

---

## [3.6.0] - 2026-02-19

### Realistic Backtest Engine, Pro Mode Redesign & New Strategies

Komplette Ueberarbeitung der Backtest-Engine mit echten technischen Indikatoren,
neue Strategien (Edge Indicator, Claude Edge Indicator), Guided Tour, GettingStarted Redesign
und BotBuilder Pro Mode Neugestaltung.

#### Hinzugefuegt

##### Realistische Backtest-Engine
- **Technische Indikatoren** in `src/backtest/engine.py` — Pure-Python Implementierung:
  - `_ema()` — Exponential Moving Average
  - `_rsi()` — Relative Strength Index (14)
  - `_macd()` — MACD mit Signal Line und Histogram (12/26/9)
  - `_adx()` — Average Directional Index (14)
  - `_atr()` — Average True Range (14)
  - `_stdev()` — Rolling Standard Deviation
- **Signal-Methoden komplett ueberarbeitet**:
  - `_signal_edge_indicator`: EMA Ribbon (8/21), ADX, MACD, RSI mit Drift, Predator Momentum Score
  - `_signal_sentiment_surfer`: 6-Quellen gewichtetes Scoring (FGI 25%, Funding 20%, VWAP 15%, Supertrend 15%, Volume 10%, Momentum 15%)
  - `_signal_degen`: 10 Datenquellen + RSI + EMA, Funding Divergence, Signal Strength Gate
- **History-basierte Analyse**: `_generate_signal()` erhaelt kompletten Preisverlauf als `history` Parameter

##### Neue Strategien
- **Edge Indicator** (`src/strategy/edge_indicator.py`) — Rein technische Kline-Strategie
  - RSI, MACD, Bollinger Bands, Volume Analysis
  - Scoring-System mit konfigurierbarem Mindest-Score
  - Data Sources: spot_price, vwap, supertrend, spot_volume, volatility
- **Claude Edge Indicator** (`src/strategy/claude_edge_indicator.py`) — Hybrid-Strategie
  - Technische Analyse + LLM-Bewertung
  - Kombiniert Indikatoren mit Sentiment-Daten
  - Data Sources: spot_price, fear_greed, news_sentiment, vwap, supertrend, spot_volume, volatility, funding_rate

##### Guided Tour System
- **GuidedTour Komponente** (`frontend/src/components/ui/GuidedTour.tsx`)
  - Leichtgewichtiger Tour-Guide ohne externe Dependencies
  - Highlight-Overlay, Tooltip-Box, Fortschrittsanzeige
  - Scroll-to-Element, ESC zum Schliessen, localStorage Persistenz
- **Tour Store** (`frontend/src/stores/tourStore.ts`) — Zustand Store fuer Tour-State
- **Dashboard Tour** (4 Steps): Navigation, Demo/Live, KPI-Karten, Charts
- **data-tour Attribute** auf Dashboard und AppLayout Elementen

##### Backtest-Scripts
- **`scripts/backtest_edge_indicator.py`** — 15 Konfigurationen, JSON-Export
- **`scripts/backtest_timeframes.py`** — Multi-Timeframe + All-Strategy Vergleich

##### Admin & Event Logging
- **Admin Logs Router** (`src/api/routers/admin_logs.py`) — Audit-Log API
- **Event Logger** (`src/utils/event_logger.py`) — Strukturiertes Event-Logging
- **Kline Backtest Engine** (`src/backtest/kline_backtest_engine.py`) — Kline-basiertes Backtesting
- **Market Data Module** (`src/data/market_data.py`) — Erweiterte Marktdaten

#### Geaendert

##### BotBuilder Pro Mode Redesign
- **Numeric Params**: Range Bars entfernt, 2-Spalten Grid Layout
  - Jeder Parameter in eigenem Card mit Label und Input
  - `grid grid-cols-2 gap-2` statt vorheriger Range-Bar UI
- **Timeframe Empfehlung**: Fuer Edge Indicator und Claude Edge Indicator
  - Empfohlener Timeframe: **1h** (basierend auf 90-Tage Backtest)
  - Anzeige als kompakte Zeile mit Clock-Icon

##### GettingStarted Redesign
- Kompaktes 3-Karten Layout (Verbinden, Konfigurieren, Handeln)
- Workflow-Diagramm, Strategie-Uebersicht, Exchange-Vergleich
- i18n: ~60 neue Keys in DE + EN

##### Weitere Aenderungen
| Datei | Aenderung |
|-------|-----------|
| `frontend/src/pages/BotDetail.tsx` | STRATEGY_DISPLAY fuer neue Strategien |
| `frontend/src/pages/Bots.tsx` | STRATEGY_DISPLAY fuer neue Strategien |
| `src/strategy/__init__.py` | Neue Strategy Imports |
| `src/bot/bot_worker.py` | claude_edge_indicator als LLM-Strategie |
| `docker-compose.yml` | Bereinigt (Prometheus/Grafana entfernt) |

#### Backtest-Ergebnisse (90 Tage, BTCUSDT, $10k)

| Strategie | Return | Win Rate | Max DD | Sharpe | Trades | PF |
|-----------|--------|----------|--------|--------|--------|-----|
| **Liquidation Hunter** | +26.2% | 53.9% | 4.7% | 5.51 | 104 | 1.98 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 68 | 1.65 |
| Claude Edge Indicator | +18.6% | 47.1% | 9.8% | 2.91 | 68 | 1.65 |
| Degen | +0.8% | 40.0% | 3.8% | 0.43 | 35 | 1.08 |
| LLM Signal | +0.8% | 40.0% | 4.5% | 0.51 | 25 | 1.12 |
| Sentiment Surfer | -3.7% | 32.3% | 9.4% | -1.07 | 65 | 0.84 |

**Bester Gesamtwert**: 1h Conservative (TP 2%, SL 1%) — Sharpe 6.09, +27.4%, nur 3.9% DD

#### Neue Dateien

| Datei | Zweck |
|-------|-------|
| `src/strategy/edge_indicator.py` | Edge Indicator Strategie |
| `src/strategy/claude_edge_indicator.py` | Claude Edge Indicator Strategie |
| `src/backtest/kline_backtest_engine.py` | Kline-basierte Backtest Engine |
| `src/data/market_data.py` | Erweiterte Marktdaten |
| `src/api/routers/admin_logs.py` | Admin Audit-Log API |
| `src/api/schemas/admin_logs.py` | Admin Log Schemas |
| `src/utils/event_logger.py` | Event Logger |
| `frontend/src/components/ui/GuidedTour.tsx` | Guided Tour Komponente |
| `frontend/src/stores/tourStore.ts` | Tour State Store |
| `scripts/backtest_edge_indicator.py` | Edge Indicator Backtest Script |
| `scripts/backtest_timeframes.py` | Multi-Timeframe Backtest Script |

#### Tests

| Datei | Zweck |
|-------|-------|
| `tests/unit/test_edge_indicator.py` | Edge Indicator Unit Tests |
| `tests/unit/test_atr_and_divergence.py` | ATR + Divergence Tests |
| `tests/backtest/test_edge_indicator_backtest.py` | Backtest Integration Tests |
| `tests/integration/test_edge_indicator_integration.py` | Strategy Integration Tests |
| `frontend/src/components/ui/GuidedTour.test.tsx` | Guided Tour Tests |
| `frontend/src/stores/tourStore.test.ts` | Tour Store Tests |
| `frontend/src/i18n/i18n-completeness.test.ts` | i18n Vollstaendigkeit Tests |
| `frontend/src/pages/GettingStarted.test.tsx` | GettingStarted Tests |
| `frontend/src/pages/DashboardTour.test.tsx` | Dashboard Tour Tests |

---

## [3.5.1] - 2026-02-19

### Grafana Admin Dashboard & Infrastructure Modernization

Infrastruktur-Modernisierung mit Alembic Migrations, Shared Scheduler, Exchange Rate Limiter,
Risk Stats in DB und neue Datenquellen. Grafana Admin Support Dashboard fuer PostgreSQL.

#### Hinzugefuegt

##### Grafana Admin Support Dashboard (#78)
- **Admin Support Dashboard** (`monitoring/grafana/dashboards/admin-support.json`)
  - Vorkonfiguriertes Grafana Dashboard fuer PostgreSQL-Daten
  - Provisioning-Konfiguration fuer automatisches Dashboard-Loading
  - PostgreSQL Datasource Auto-Provisioning (`monitoring/grafana/provisioning/datasources/datasources.yml`)

##### Alembic Async Migration Framework (#44)
- **Alembic Integration** — Async-faehiges Migrations-Framework
  - `alembic.ini` + `migrations/env.py` mit async Engine Support
  - `migrations/versions/001_initial_schema.py` — Initiale Schema-Migration
  - Ersetzt die bisherigen inline SQLite-Migrationen fuer PostgreSQL

##### Shared APScheduler (#46)
- **Gemeinsamer Scheduler** — Ein APScheduler fuer alle BotWorker
  - Reduziert Thread-Overhead bei vielen parallel laufenden Bots
  - Zentrale Scheduler-Instanz im Orchestrator

##### Exchange Rate Limiter (#47)
- **Token Bucket Rate Limiter** (`src/exchanges/rate_limiter.py`)
  - Per-Exchange Rate Limiting (shared ueber alle Bots)
  - Verhindert API-Bans bei hoher Bot-Anzahl

##### Risk Stats in Datenbank (#48)
- **RiskManager Stats Migration** — Von JSON-Dateien in die Datenbank
  - `RiskDailyStats` DB-Modell fuer persistente Risiko-Statistiken
  - Migrations-Script: `scripts/migrate_risk_json.py`
  - Eliminiert Filesystem-basierte State-Haltung

##### Neue Datenquellen (#42)
- **5 Velo-replizierte Datenquellen** (kostenlose Alternativen zu Velo-Daten)
  - Neue Fetcher in `src/data/market_data.py` und `data_source_registry.py`
  - Verfuegbar in Bot Builder und Backtesting

##### Pro Mode Toggle (#56)
- **UI Pro Mode** — Toggle fuer erweiterte Datenquellen-Anzeige
  - Responsive Fix fuer mobile Darstellung

#### Behoben
- **Optimistic Preset Updates** (#41) — Preset-Speichern dauert nicht mehr 3-5s (IPv6/Vite Proxy Delay auf Windows)

---

## [3.5.0] - 2026-02-19

### Production-Ready Sprint: Monitoring, WebSocket, Quality

Komplettes Production-Hardening mit Prometheus Monitoring, Real-Time WebSocket-Updates,
CI/CD Pipeline und umfassender Test Suite (3707 Tests). Vorbereitung fuer DigitalOcean Droplet Deployment.

#### Hinzugefuegt

##### Prometheus Monitoring (#75)
- **Zentrales Metrics-Modul** (`src/monitoring/metrics.py`) — HTTP, Bot, Trade und System-Metriken
  - `http_requests_total` (Counter), `http_request_duration_seconds` (Histogram)
  - `bots_running_total`, `bots_by_status` (Gauges)
  - `trades_total` (Counter), `trade_pnl_percent` (Histogram)
  - `websocket_connections_active`, `db_query_duration_seconds`
- **PrometheusMiddleware** (`src/monitoring/middleware.py`) — Request Count & Latency Tracking
  - Pfad-Normalisierung (z.B. `/api/trades/123` → `/api/trades/{id}`) gegen Cardinality Explosion
  - `/metrics` Endpoint wird uebersprungen
- **`/metrics` Endpoint** (`src/api/routers/metrics.py`) — Prometheus-Format, unauthentifiziert
- **Bot-Metrics Collector** (`src/monitoring/collectors.py`) — Background Task, alle 15s
  - Liest Orchestrator-State: Running Count, Status-Verteilung, Consecutive Errors
- **Docker Compose Services** — Prometheus + Grafana
  - `prom/prometheus:latest` auf Port 9090 (nur localhost)
  - `grafana/grafana:latest` auf Port 3000
  - `monitoring/prometheus.yml` Scrape-Konfiguration
- **Neue Dependency**: `prometheus-client>=0.20.0`

##### WebSocket Real-Time Updates (#76)
- **ConnectionManager** (`src/api/websocket/manager.py`) — Per-User Pub/Sub
  - `connect()`, `disconnect()`, `broadcast_to_user()`, `broadcast_all()`
  - Thread-safe via `asyncio.Lock`
- **`/api/ws` Endpoint** (`src/api/routers/websocket.py`) — JWT-Authentifizierung via Query-Param
  - Ping/Pong Keep-Alive, automatische Disconnect-Erkennung
  - `WEBSOCKET_CONNECTIONS` Prometheus Gauge wird aktualisiert
- **Event Broadcasting** im Backend:
  - `BotOrchestrator`: `bot_started`, `bot_stopped` Events
  - `TradeExecutorMixin`: `trade_opened` Events
  - `PositionMonitorMixin`: `trade_closed` Events
- **React `useWebSocket` Hook** (`frontend/src/hooks/useWebSocket.ts`)
  - Auto-Reconnect nach 5s, Ping alle 30s
  - Stabile Handler-Referenzen via `useMemo`
- **Zustand `realtimeStore`** (`frontend/src/stores/realtimeStore.ts`)
  - `lastEvent`, `botStatuses`, `pushEvent()`, `updateBotStatus()`
- **AppLayout Integration** — Toast-Notifications bei Bot-Start/Stop und Trade-Events

##### Codebase Quality Sprint (#58–#65)
- **Code Cleanup** (#58) — Dead Code, unused Imports, unreachable Branches entfernt
- **Silent Error Handling Fix** (#59) — Bare `except: pass` durch spezifische Handler ersetzt
- **Notification Retry** (#60) — Exponential Backoff mit `tenacity` (3 Versuche, 1→2→4s)
- **Structured Logging** (#61) — `%s`-Format statt f-Strings in allen Loggern
- **Config Validation** (#62) — Startup-Validierung: JWT Key, DB URL, Encryption Key
- **Offline Indicator** (#63) — Frontend-Banner bei Netzwerkverlust (auto-dismiss bei Reconnect)
- **CI/CD Pipeline** (#64) — GitHub Actions: Lint, Tests, Frontend Build, Security Audit
- **Comprehensive Test Suite** (#65) — 3707 Tests, alle bestehenden Bugs gefixt

#### Geaendert

| Datei | Aenderung |
|-------|-----------|
| `requirements.txt` | `prometheus-client>=0.20.0` hinzugefuegt |
| `src/api/main_app.py` | PrometheusMiddleware, Metrics + WebSocket Router, Collector Task |
| `src/bot/orchestrator.py` | `_broadcast_event()` fuer WebSocket Events |
| `src/bot/trade_executor.py` | `trade_opened` WebSocket Broadcast |
| `src/bot/position_monitor.py` | `trade_closed` WebSocket Broadcast |
| `docker-compose.yml` | Prometheus + Grafana Services, neue Volumes |
| `frontend/src/components/layout/AppLayout.tsx` | WebSocket Hook + Toast Notifications |

#### Neue Dateien

| Datei | Zweck |
|-------|-------|
| `src/monitoring/__init__.py` | Package Init |
| `src/monitoring/metrics.py` | Prometheus Metric Definitionen |
| `src/monitoring/middleware.py` | HTTP Request Metrics Middleware |
| `src/monitoring/collectors.py` | Bot Metrics Background Collector |
| `src/api/routers/metrics.py` | `/metrics` Endpoint |
| `src/api/websocket/__init__.py` | Package Init |
| `src/api/websocket/manager.py` | WebSocket Connection Manager |
| `src/api/routers/websocket.py` | `/api/ws` WebSocket Endpoint |
| `frontend/src/hooks/useWebSocket.ts` | React WebSocket Hook |
| `frontend/src/stores/realtimeStore.ts` | Zustand Real-Time Store |
| `monitoring/prometheus.yml` | Prometheus Scrape Config |

#### Zugriff (DigitalOcean Droplet)

Nach `docker compose up -d`:
- **App**: `http://<droplet-ip>:8000`
- **Grafana**: `http://<droplet-ip>:3000` (Login: admin/admin → Passwort aendern)
- **Prometheus**: Nur intern via `http://prometheus:9090`
- In Grafana: Data Sources → Prometheus → URL `http://prometheus:9090`

#### Test-Ergebnis

| Metrik | Wert |
|--------|------|
| Tests Passed | 3707 |
| Tests Skipped | 5 |
| Tests Failed | 0 |
| Frontend Build | OK (9.76s) |

---

## [3.4.0] - 2026-02-17

### PostgreSQL-Migration (Multi-User / 10k+ User Support)

SQLite bleibt als Fallback fuer lokale Entwicklung erhalten. PostgreSQL wird als Produktionsdatenbank
fuer Multi-User-Betrieb mit Connection Pooling eingefuehrt.

#### Hinzugefuegt
- **PostgreSQL Support** — Dual-Backend Architektur (SQLite + PostgreSQL)
  - `asyncpg>=0.29.0` als PostgreSQL async Driver
  - `_build_engine_kwargs()` in `session.py` — automatische Backend-Erkennung
  - Connection Pooling: `pool_size` (default 20), `max_overflow` (default 30), `pool_pre_ping`, `pool_recycle` (default 1800s)
  - Pool-Parameter konfigurierbar via `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE` Umgebungsvariablen
- **PostgreSQL Docker Service** in `docker-compose.yml`
  - `postgres:16-alpine` mit Healthcheck (`pg_isready`)
  - Named Volume `pgdata` fuer Persistenz
  - `trading-bot` Service: `depends_on: postgres` mit `condition: service_healthy`
  - `DATABASE_URL` automatisch auf internen PostgreSQL Container gesetzt
- **Dedizierter Audit-Pool** fuer PostgreSQL in `audit_log.py` (`pool_size=5, max_overflow=10`)
- **Test Dual-Backend** — `TEST_DATABASE_URL` Env-Variable in `tests/conftest.py`
- **Anleitung** `Anleitungen/PostgreSQL Migration.md` (DE + EN)

#### Geaendert
- `src/models/database.py`: Boolean `server_default="0"` → `server_default=text("false")` auf 5 Spalten (PostgreSQL-kompatibel)
  - `TradeRecord.demo_mode`, `ExchangeConnection.builder_fee_approved`, `ExchangeConnection.referral_verified`,
    `ExchangeConnection.affiliate_verified`, `AffiliateLink.uid_required`
- `src/models/session.py`: SQLite-Migrationen in `_run_sqlite_migrations()` extrahiert, `_is_sqlite` Guard
- `src/api/middleware/audit_log.py`: Backend-Erkennung, PostgreSQL Pool-Settings
- `Dockerfile`: `libpq-dev` (Builder) + `libpq5` (Runtime) fuer asyncpg
- `.env.example`: PostgreSQL-Konfiguration und Pool-Parameter dokumentiert
- `.env`: `DATABASE_URL` auf PostgreSQL umgestellt

| Datei | Aenderung |
|-------|-----------|
| `requirements.txt` | `asyncpg>=0.29.0` hinzugefuegt |
| `src/models/session.py` | Dual-Backend Engine, Pool Config, Migrations extrahiert |
| `src/models/database.py` | Boolean `server_default` PostgreSQL-kompatibel |
| `src/api/middleware/audit_log.py` | Dedizierter PostgreSQL Audit-Pool |
| `docker-compose.yml` | PostgreSQL Service + Volume |
| `Dockerfile` | PostgreSQL Client-Libs |
| `.env.example` | Pool-Parameter Dokumentation |
| `.env` | `DATABASE_URL` auf PostgreSQL |
| `tests/conftest.py` | `TEST_DATABASE_URL` Support |

---

## [3.3.5] - 2026-02-17

### Architecture Hardening — BotWorker Decomposition & 3683 Tests

Grosse Architektur-Ueberarbeitung: BotWorker von 1286 Zeilen in 5 fokussierte Mixins zerlegt,
einheitliche Exception-Hierarchie, Security-Fixes und massive Test-Suite Erweiterung.

#### Hinzugefuegt

##### BotWorker Decomposition (#41)
- **5 Mixins** extrahiert aus `bot_worker.py` (1286 → 648 Zeilen):
  - `TradeExecutorMixin` (`src/bot/trade_executor.py`) — Trade-Ausfuehrung
  - `PositionMonitorMixin` (`src/bot/position_monitor.py`) — Position-Ueberwachung
  - `RotationManagerMixin` (`src/bot/rotation_manager.py`) — Symbol-Rotation
  - `HyperliquidGatesMixin` (`src/bot/hyperliquid_gates.py`) — HL Builder/Referral Gates
  - `NotificationsMixin` (`src/bot/notifications.py`) — Benachrichtigungs-Dispatch
- **Bots Router Split** — `bots.py` (1259 → 648 Zeilen) aufgeteilt in:
  - `bots_lifecycle.py` (327 Zeilen) — Start/Stop/Restart/Create/Delete
  - `bots_statistics.py` (323 Zeilen) — Performance, Compare, Statistiken

##### Exception & Error Handling
- **Globaler Error Handler** (`src/api/middleware/error_handler.py`)
  - Exception→HTTP Status Mapping: `ExchangeError`→502, `AuthError`→401, etc.
- **Einheitliche Exception-Hierarchie** (`src/exceptions.py`)
  - `BitgetClientError`, `HyperliquidClientError`, `WeexClientError` → `ExchangeError`
  - `DataFetchError` → `DataSourceError`
  - `CircuitBreakerError` → `TradingBotError`

##### Security Hardening
- **Refresh Token Rotation** mit `token_version` Revocation
- **JSON Field Size Limits** (10KB) auf Bot Config Dicts
- **Cross-Field Strategy Validation** (LLM erfordert Provider, Rotation erfordert Interval)
- **Auth Audit Logging** mit Client IP fuer Login/Refresh Events
- **FastAPI DI** — Globaler Orchestrator ersetzt durch `app.state`

##### Shared Utilities
- **`src/api/rate_limit.py`** — Zentraler Rate Limiter (8 Router aktualisiert)
- **`src/utils/json_helpers.py`** — `parse_json_field()` Helper (4 Duplikate → 1)
- **`src/utils/settings.py`** — `get_settings_batch()` batcht N+1 DB-Queries

##### Frontend Unit Tests
- **Vitest Konfiguration** (`frontend/vitest.config.ts`)
- **Unit Tests** fuer API Client, UI Components, Pages, Stores
- **ESLint Config** fuer Test-Dateien

##### Backend Test Suite
- **3683 Tests** (5 skipped, 0 failures) — Massive Erweiterung:
  - 139 neue Test-Dateien
  - Unit Tests fuer alle Router, Exchanges, Strategies, Providers
  - Integration Tests fuer Bot Worker, Orchestrator, Dashboard

| Datei | Aenderung |
|-------|-----------|
| `src/bot/bot_worker.py` | 1286 → 648 Zeilen, Mixins extrahiert |
| `src/api/routers/bots.py` | Aufgeteilt in lifecycle + statistics |
| `src/api/middleware/error_handler.py` | Exception→HTTP Mapping |
| `src/exceptions.py` | Einheitliche Hierarchie |
| `src/auth/jwt_handler.py` | Token Rotation + Revocation |
| `src/api/main_app.py` | FastAPI DI statt globaler State |

---

## [3.3.4] - 2026-02-15

### Degen Strategy & Settings Redesign

Neue "Degen" Strategie mit festem LLM-Prompt und 14 Datenquellen, komplett ueberarbeitete
Settings-Seite und verbesserter Tax Report.

#### Hinzugefuegt
- **Degen Strategy** (`src/strategy/degen.py`) — Fixed LLM Prompt fuer 1h BTC Predictions
  - 14 Datenquellen, aggressives Confidence-Mapping
  - Registriert in Strategy Registry mit eigenem Parameter-Schema
- **Order Book Depth Fetcher** — Binance Futures Depth API Integration in `market_data.py`
- **NumInput Komponente** (`frontend/src/components/ui/NumInput.tsx`)
- **Pagination Komponente** (`frontend/src/components/ui/Pagination.tsx`)
- **Strategy Display Names** im Frontend (Bot Cards, Grid View)

#### Geaendert

##### Settings Redesign
- **Tabbed Layout** — 3 Tabs: API Keys, LLM Keys, Affiliate Links
  - Komplett ueberarbeitete Settings-Seite (1781 → strukturierter)
  - Verbesserte LLM-Key-Verwaltung mit Model Chips

##### Tax Report
- **CSV Format Fix** — Verbesserter Export
- **Hyperliquid Builder Fee Signing Flow** Verbesserungen

##### Weitere Aenderungen
| Datei | Aenderung |
|-------|-----------|
| `src/strategy/degen.py` | NEU: Degen Strategy |
| `src/bot/bot_worker.py` | LLM Key Injection fuer Degen |
| `src/risk/risk_manager.py` | Multi-Bot Support Erweiterungen |
| `frontend/src/pages/Settings.tsx` | Tabbed Redesign |
| `frontend/src/pages/Presets.tsx` | Verbesserungen |
| `src/api/routers/tax_report.py` | CSV Fix + verbesserter Export |

---

## [3.3.3] - 2026-02-13

### Model Family Selection & Design System Overhaul

LLM Model-Auswahl pro Provider, einheitliches Design System und standardisierte Trade-Tabellen.

#### Hinzugefuegt
- **MODEL_CATALOG** — Per-Provider Model-Auswahl (je 3 Modelle)
  - Dependent Select im BotBuilder: Family → Model Kaskade
  - `model_override` Support fuer alle 7+ LLM Provider
  - LLM Connections API erweitert mit `family_name` und Models-Liste
- **DeepSeek Provider** (`src/ai/providers/deepseek.py`) — Neuer LLM-Provider
- **Latest Trade Hero Card** — Kopierbar, auf Bots Modal und Performance Page
- **Confidence/Reasoning/Details Spalten** in Trade-Tabellen
- **Legacy Bot LLM Detection** — Fallback aus Trade Reason Text

#### Geaendert
- **Trade-Tabellen standardisiert** — Dashboard-Format auf allen Seiten
  - Einheitliches `table-premium` Styling
- **Design System** — Konsistentes Glassmorphism, Badges, Table Styling
- **Settings LLM Accordion** mit Model Chips
- **Bots Modal** — Kompaktes Layout fuer scroll-freie Trade History
- i18n: Model Selection Keys in DE + EN

| Datei | Aenderung |
|-------|-----------|
| `src/ai/providers/__init__.py` | MODEL_CATALOG, Family Support |
| `src/ai/providers/deepseek.py` | NEU: DeepSeek Provider |
| `src/strategy/llm_signal.py` | model_override Support |
| `src/api/routers/config.py` | LLM Connections + Models API |
| `frontend/src/components/bots/BotBuilder.tsx` | Dependent Select |
| `frontend/src/pages/Bots.tsx` | Trade Table Standardisierung |
| `frontend/src/pages/BotPerformance.tsx` | Hero Card + Spalten |
| `frontend/src/pages/Settings.tsx` | LLM Accordion + Chips |

---

## [3.3.2] - 2026-02-13

### Quality & Security Sprint

Umfassender Quality-Sprint: i18n-Bereinigung, Exception-Hierarchie, Security-Fixes,
Circuit Breaker Erweiterung und erweiterte Test-Suite.

#### Hinzugefuegt

##### Exception Hierarchy (#20)
- **Zentralisierte Exception-Hierarchie** (`src/exceptions.py`)
  - Inheritance Tree: `TradingBotError` → `ExchangeError`, `DataSourceError`, etc.
  - Debug Logging fuer stille Exception-Handler in `bot_worker.py`
- **103 neue Tests**:
  - 29 Bot Worker Tests (Lifecycle, Trading, Monitoring)
  - 20 Discord Notifier Tests (Embeds, Webhooks)
  - 29 Circuit Breaker Tests (State Transitions, Recovery)
  - 25 Exception Hierarchy Tests (Inheritance, Catchability)

##### Circuit Breaker Erweiterung (#20)
- **Neue Circuit Breakers** fuer Top Trader L/S Ratio, OI History, Liquidations
- **Data Freshness Tracking** via `fetch_timestamps` in DataQuality
- **Performance Indexes** fuer `trade_records` und `bot_configs` Queries

##### HL Builder & Affiliate Tests (#28)
- **35 Tests** fuer Builder Fee Berechnung, Builder Kwargs Injection, Referral Gates
- Builder Check: Soft-Warning → Hard-Gate (blockiert Bot-Start)

#### Behoben

##### Security Hardening (#39)
- **C1 CRITICAL**: Admin-Query mit nicht-existierendem `User.is_admin` behoben
- **H1 HIGH**: Legacy Plaintext Key Loading aus BitgetConfig entfernt
- **H2 HIGH**: Rate Limit (10/min) auf `/api/auth/refresh` Endpoint
- **H3 HIGH**: Deprecated Plaintext Webhook URLs via Migration bereinigt
- **30 Security Regression Tests** hinzugefuegt

##### Frontend i18n (#19)
- **50+ i18n Keys** hinzugefuegt — Hardcoded Strings in BotDetail, Settings, Trades, Bots ersetzt
- **Responsive Layout** — Modal 4-col → 2-col auf Mobile, Flex-Wrap fuer Bot Card Actions
- **Light Mode** — Skeleton Opacity verbessert (0.06 → 0.10), Info Box Backgrounds

##### Preset & Telegram i18n (#31, #32)
- Telegram i18n Keys + Anleitung (#31)
- Preset i18n Keys + Anleitung (#32)

##### Discord Webhook (#30)
- Globaler Discord Webhook Fallback entfernt (nur noch per-Bot)

---

## [3.3.1] - 2026-02-12

### Backtesting Module

Vollstaendiges Backtesting-System mit Frontend und Backend, erweiterbare Datenquellen
und 11-Faktor Signal-Analyse.

#### Hinzugefuegt

##### Backend
- **BacktestRun DB-Modell** — Persistente Backtest-Ergebnisse
- **Backtest API Router** (`src/api/routers/backtest.py`) — 5 Endpoints
  - Backtest starten, Status abfragen, Ergebnisse laden, History, Loeschen
- **Strategy Adapter** (`src/backtest/strategy_adapter.py`) — Verbindet Strategien mit Backtest Engine
- **Background Task Execution** mit BacktestEngine
- **Pydantic Schemas** (`src/api/schemas/backtest.py`)

##### Erweiterte Backtest Engine
- **11-Faktor Signal-Analyse** — OI, Taker Volume, Top Trader L/S, Funding Divergence, Stablecoin Flows, Volatility, Macro
- **8 neue API-Integrationen** in Historical Data Fetcher:
  - Binance OI, Taker Buy/Sell, Top Trader L/S
  - Bitget Funding, DefiLlama, CoinGecko, Blockchain.info, FRED
- **5 neue Bot-Datenquellen** (jetzt 26 total):
  - Stablecoin Flows (DefiLlama), BTC Hashrate (Blockchain.info)
  - Bitget Funding Rate, DXY + Fed Funds Rate (FRED)

##### Frontend
- **Backtest Page** (`frontend/src/pages/Backtest.tsx`) — Vollstaendige UI:
  - Config Card mit FilterDropdown (Strategie, Trading Pairs, Timeframe)
  - DatePicker Side-by-Side, Equity Curve Chart
  - Metrics Cards, Trade Log Table, History mit Status Badges
  - Profit/Loss Spalte in Backtest History
- **Neue UI-Komponenten**: DatePicker, FilterDropdown
- **Unterstuetzte Timeframes**: 1m, 5m, 15m, 30m, 1h, 4h, 1D
- **Trading Pairs**: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, AVAXUSDT
- **Active Data Sources als Badges** in Backtest-Ergebnissen

##### Weitere Verbesserungen
- **Trades Page Filter** Verbesserungen
- **Win-Rate 3-Tier Colors** — Farbkodierung nach Performance
- **KI-Companion Custom Prompt** Support mit LLM Note
- **SQLite WAL Mode Fix** fuer concurrent Backtest Writes
- i18n: Vollstaendige DE/EN Uebersetzungen

| Datei | Aenderung |
|-------|-----------|
| `src/api/routers/backtest.py` | NEU: 5 Endpoints |
| `src/api/schemas/backtest.py` | NEU: Pydantic Schemas |
| `src/backtest/strategy_adapter.py` | NEU: Strategy Adapter |
| `src/backtest/engine.py` | 11-Faktor Signal-Analyse |
| `src/backtest/historical_data.py` | 8 neue API-Integrationen |
| `src/data/data_source_registry.py` | 5 neue Datenquellen |
| `src/data/market_data.py` | Neue Fetch-Methoden |
| `src/models/database.py` | BacktestRun Modell |
| `frontend/src/pages/Backtest.tsx` | NEU: Backtest UI |
| `frontend/src/components/ui/DatePicker.tsx` | NEU |
| `frontend/src/components/ui/FilterDropdown.tsx` | NEU |

---

## [3.3.0] - 2026-02-11

### Hyperliquid Builder Fee Wallet-Gate

### Hinzugefuegt
- **Hyperliquid Builder Fee Wallet-Gate** — Browser-basierte EIP-712 Signatur
  - Multi-Wallet Support via RainbowKit (MetaMask, WalletConnect, Coinbase, Ledger, Trust, 300+ Wallets)
  - `BuilderFeeApproval` Komponente mit 3-Step Wizard (Wallet verbinden → Signieren → Bestaetigung)
  - `GET /config/hyperliquid/builder-config` — Public Endpoint fuer Builder-Konfiguration (ersetzt admin-only)
  - `POST /config/hyperliquid/confirm-builder-approval` — On-Chain Verifizierung + DB-Tracking
  - Hard-Gate: Hyperliquid Bots starten nur nach Builder Fee Approval
  - DB-Tracking: `builder_fee_approved` + `builder_fee_approved_at` auf ExchangeConnection
  - `builder_fee_approved` Feld in Bot-API-Response
  - Affiliate-Link Integration im Approval-Flow
  - Anleitung: `Anleitungen/Hyperliquid Builder Fee genehmigen.md`
  - Neue Dependencies: `@rainbow-me/rainbowkit`, `wagmi`, `viem`, `@tanstack/react-query`
  - i18n: `builderFee` Namespace in DE + EN

### Entfernt
- Server-side `POST /config/hyperliquid/approve-builder-fee` (war broken fuer separate API Wallets)

### Geaendert
- `bot_worker.py`: Builder-Check von Soft-Warning zu Hard-Gate (blockiert Bot-Start)
- Builder-Status Endpoint von admin-only zu public (alle authentifizierten User)

---

## [3.2.0] - 2026-02-11

### Notifications Refactor + Preset-Integration im Bot Builder

#### Entfernt
- **Globaler Discord-Webhook** aus User-Settings entfernt — per-Bot Webhook bleibt bestehen
- Discord-Tab in Settings-Seite entfernt
- API-Endpoints `PUT /config/discord` und `POST /config/discord/test` entfernt
- `DiscordConfigUpdate` Schema und `DISCORD_WEBHOOK_PATTERN` entfernt
- User-Level Fallback in `bot_worker._get_discord_notifier()` entfernt (nur noch Bot-spezifisch)

#### Hinzugefügt
- **Telegram-Benachrichtigungen** (per Bot, optional)
  - Neuer `TelegramNotifier` (`src/notifications/telegram_notifier.py`) — nutzt Telegram Bot API via aiohttp
  - DB-Spalten: `telegram_bot_token` (verschlüsselt) + `telegram_chat_id` auf `BotConfig`
  - Bot-Token + Chat-ID Felder im Bot Builder (Step 4: Exchange & Modus)
  - Test-Endpoint: `POST /api/bots/{id}/test-telegram`
  - Anleitung: `Anleitungen/Telegram Benachrichtigungen einrichten.md`
- **Preset-Auswahl im Bot Builder**
  - "Von Preset laden" Dropdown in Step 1 (Name)
  - Automatisches Befüllen aller Felder aus gewähltem Preset
  - Exchange-übergreifende Presets (`exchange_type` = "any", Standard)
  - Automatische Trading-Pair-Konvertierung (BTCUSDT ↔ BTC je nach Exchange)
  - Anleitung: `Anleitungen/Presets im Bot Builder verwenden.md`
- **Preset-Umschaltung für bestehende Bots**
  - Preset-Dropdown auf "Meine Bots"-Seite pro Bot-Card
  - `POST /api/bots/{id}/apply-preset/{preset_id}` — Preset auf bestehenden Bot anwenden
  - `active_preset_id` + `active_preset_name` in Bot-API-Response
  - Nur möglich wenn Bot gestoppt ist
- **Multi-Notifier System** in `bot_worker.py` — Discord + Telegram gleichzeitig pro Bot
- **Projekt-CLAUDE.md** — Konventionen für Anleitungen, Issues und Changelog
- GitHub Issues: #30 (Discord entfernen), #31 (Telegram), #32 (Presets)

#### Geändert
- `BotConfig` Model: Neue Spalten `telegram_bot_token`, `telegram_chat_id`
- `ConfigPreset.exchange_type`: Default "any" (alle Exchanges), `PresetCreate` akzeptiert "any|bitget|weex|hyperliquid"
- `Presets.tsx`: "Alle Exchanges" als Standard-Option bei Preset-Erstellung
- i18n (EN + DE): Neue Keys für Telegram, Presets, Bot Builder

---

## [3.1.1] - 2026-02-10

### Test-Fixes & CodeAssist-Update

- **Integration Tests**: Rate Limiter in Test-Conftest deaktiviert (`limiter.enabled = False`)
- **Integration Tests**: 307-Redirect als akzeptierten Status-Code in Auth-Assertions aufgenommen
- **CodeAssist**: Skills, Templates und Commands aktualisiert (neue Version)

---

## [3.1.0] - 2026-02-10

### Hyperliquid Revenue Analytics

Vollstaendiges Tracking und Visualisierung von Builder-Fee-Einnahmen auf Hyperliquid.

#### Backend

- **Neue DB-Spalte** `builder_fee` auf `TradeRecord` — speichert berechnete Builder-Fee pro Trade
- **Automatische Migration** + Backfill fuer bestehende geschlossene HL-Trades
- **Hyperliquid Client**: `get_trade_total_fees()` und `get_funding_fees()` implementiert (vorher immer 0)
- **Neue Methode** `calculate_builder_fee()` — berechnet Builder-Fee aus Entry/Exit-Value und Fee-Rate
- **Builder-Fee-Berechnung** automatisch bei jedem Trade-Close im BotWorker
- **Neuer API-Endpoint** `GET /api/statistics/revenue` — dedizierte Revenue-Analytik mit Daily-Breakdown und Monthly-Estimate
- **Erweiterte Endpoints**: `/api/statistics` und `/api/statistics/daily` geben jetzt `total_builder_fees` / `builder_fees` zurueck
- **Revenue-Summary** (`/api/config/hyperliquid/revenue-summary`) zeigt jetzt `earnings`-Objekt mit 30-Tage-Totals

#### Frontend

- **Neue Komponente** `RevenueChart.tsx` — BarChart (Emerald) fuer taegliche Builder-Fee-Einnahmen
- **Dashboard**: Revenue-Widget mit Total + Monthly-Estimate erscheint automatisch wenn Builder-Fees vorhanden
- **Settings > Hyperliquid**: Neue Earnings-Sektion (verdiente Fees, Trades, monatliche Schaetzung)
- **TypeScript-Types** erweitert: `builder_fee` auf Trade, `builder_fees` auf DailyStats, `total_builder_fees` auf Statistics
- **i18n**: Neue Uebersetzungsschluessel (DE + EN) fuer Revenue-Analytik

---

## [3.0.1] - 2026-02-10

### CodeAssist Integration & Projektstruktur

- **CodeAssist Konfiguration** hinzugefuegt (`.claude/`): 70+ Slash-Commands, 6 Regelsaetze (Security, Testing, Git-Workflow, Coding-Style, Agents, Issue-First)
- **MCP-Konfiguration** (`.mcp.json`) fuer MCP-Server-Anbindung
- **Anleitungen-Verzeichnis** erstellt: Alle Dokumentationen werden ab sofort unter `Anleitungen/` gesammelt
- Bestehende Anleitung nach `Anleitungen/` verschoben
- `.gitignore` aktualisiert: `.claude/` wird getrackt, `settings.local.json` bleibt privat

---

## [3.0.0] - 2026-02-05

### Multibot Orchestration System

Komplettes Multibot-System mit Supervisor-Worker Architektur. Mehrere Bots koennen parallel auf verschiedenen Exchanges und Modi laufen, konfiguriert ueber ein Frontend-Wizard.

#### Neue Architektur

- **BotConfig** DB-Tabelle: Persistente Konfiguration pro Bot (Strategie, Exchange, Modus, Paare, Parameter, Schedule)
- **BotWorker** (`src/bot/bot_worker.py`): Unabhaengiger asyncio Worker pro Bot mit eigenem APScheduler
- **BotOrchestrator** (`src/bot/orchestrator.py`): Supervisor verwaltet alle BotWorker, Auto-Restore beim Server-Start
- **Strategy Registry** (`src/strategy/base.py`): Pluggable Strategien via `BaseStrategy` ABC + `StrategyRegistry`
- **Per-Bot Trade Isolation**: `bot_config_id` FK auf `TradeRecord` verknuepft jeden Trade mit seinem Bot

#### Strategy System

- **BaseStrategy** ABC mit `generate_signal()`, `should_trade()`, `get_param_schema()`, `get_description()`
- **StrategyRegistry**: Register/Lookup/Create Pattern — neue Strategien automatisch im Frontend verfuegbar
- **LiquidationHunter** refactored: Implementiert jetzt `BaseStrategy`, liest Parameter aus `self._p` Dict statt globaler Settings
- **Dynamische Parameter**: Strategien definieren ihr `param_schema` (Typ, Label, Range, Default) — Frontend rendert Formulare automatisch

#### Frontend

- **Bot Builder** (`frontend/src/components/bots/BotBuilder.tsx`): 6-Schritt Wizard
  - Schritt 1: Name & Beschreibung
  - Schritt 2: Strategie-Auswahl + dynamische Parameter
  - Schritt 3: Trading-Paare, Leverage, Position Size, TP/SL
  - Schritt 4: Exchange + Modus (demo/live/both)
  - Schritt 5: Schedule (Market Sessions / Interval / Custom)
  - Schritt 6: Review & Erstellen
- **Bot Overview** (`frontend/src/pages/Bots.tsx`): Card Grid mit Live-Status, PnL, Trade Count
  - Start/Stop/Edit/Delete Aktionen pro Bot
  - Running-Indikator mit Pulse-Animation
  - Auto-Refresh alle 5 Sekunden
  - Stop All Button

#### API Endpoints

| Endpoint | Beschreibung |
|----------|-------------|
| `GET /api/bots/strategies` | Verfuegbare Strategien mit Parameter-Schemas |
| `POST /api/bots` | Bot erstellen |
| `GET /api/bots` | Alle Bots mit Runtime-Status + Trade-Statistiken |
| `GET /api/bots/{id}` | Bot-Details |
| `PUT /api/bots/{id}` | Bot aktualisieren |
| `DELETE /api/bots/{id}` | Bot loeschen (nur gestoppt) |
| `POST /api/bots/{id}/start` | Bot starten |
| `POST /api/bots/{id}/stop` | Bot stoppen |
| `POST /api/bots/{id}/restart` | Bot neustarten |
| `POST /api/bots/stop-all` | Alle Bots stoppen |

#### Unterstuetzte Exchanges

- **Bitget** (Demo + Live)
- **Weex** (Demo + Live)
- **Hyperliquid** (Demo + Live)

### Geaendert

| Datei | Aenderung |
|-------|-----------|
| `src/models/database.py` | `BotConfig` Modell, `bot_config_id` FK auf TradeRecord/BotInstance |
| `src/models/session.py` | Migrations fuer neue Spalten |
| `src/strategy/base.py` | NEU: BaseStrategy ABC + StrategyRegistry |
| `src/strategy/liquidation_hunter.py` | Refactored auf BaseStrategy |
| `src/strategy/__init__.py` | Neue Exports |
| `src/bot/bot_worker.py` | NEU: BotWorker mit eigenem Scheduler |
| `src/bot/orchestrator.py` | NEU: BotOrchestrator Supervisor |
| `src/api/schemas/bots.py` | NEU: Pydantic Schemas |
| `src/api/routers/bots.py` | NEU: CRUD + Lifecycle Router |
| `src/api/main_app.py` | Orchestrator Integration, Version 3.0.0 |
| `frontend/src/components/bots/BotBuilder.tsx` | NEU: 6-Schritt Wizard |
| `frontend/src/pages/Bots.tsx` | NEU: Bot Overview |
| `frontend/src/App.tsx` | `/bots` Route |
| `frontend/src/components/layout/AppLayout.tsx` | "My Bots" Navigation |
| `frontend/src/i18n/en.json` + `de.json` | Bots + Builder i18n Keys |

---

## [2.2.0] - 2026-02-04

### Security Hardening

- **JWT Secret Key**: Server now refuses to start if `JWT_SECRET_KEY` is not set (no more insecure default)
- **Rate Limiting**: Login endpoint limited to 5 attempts per minute (slowapi)
- **Security Headers**: All responses now include `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`
- **CORS Hardening**: Explicit methods (`GET, POST, PUT, DELETE, OPTIONS`) and headers instead of wildcards
- **Discord Webhook Validation**: Pydantic validator ensures only valid `discord.com/api/webhooks` URLs are accepted (SSRF prevention)
- **Discord Webhook Encryption**: Webhook URLs are now encrypted at rest using Fernet (same as API keys)
- **HSTS**: Optional via `ENABLE_HSTS=true` environment variable

### Architecture Improvements

- **Bot Manager Thread Safety**: All bot start/stop operations protected by `asyncio.Lock()` to prevent race conditions
- **Database Compound Indexes**: Added `(user_id, status)` and `(user_id, symbol, side)` indexes on `trade_records` for faster queries
- **Migration Error Handling**: Catches specific `duplicate column` errors instead of blanket `except: pass`

### Frontend UX

- **Loading States**: Dashboard and Trades pages show loading indicator while fetching data
- **Error Handling**: Dashboard, Trades, and Settings pages display error messages on API failures
- **Empty States**: Trades table shows "No trades yet" message when empty
- **i18n Fixes**: Removed hardcoded German "Alle Status" and English "Demo Mode", "Strategy settings..." strings — all use i18n now

### Changed

| File | Change |
|------|--------|
| `src/auth/jwt_handler.py` | Crash on missing JWT_SECRET_KEY |
| `src/api/main_app.py` | Security headers middleware, CORS fix, rate limit handler |
| `src/api/routers/auth.py` | Rate limiting on login (5/min) |
| `src/api/schemas/config.py` | Discord webhook URL validation |
| `src/api/routers/config.py` | Encrypt/decrypt webhook URL |
| `src/api/routers/bot_control.py` | Decrypt webhook URL for notifications |
| `src/api/routers/trades.py` | Decrypt webhook URL for sync notifications |
| `src/bot/bot_manager.py` | asyncio.Lock on all state mutations |
| `src/models/database.py` | Compound indexes on TradeRecord |
| `src/models/session.py` | Specific migration exception handling |
| `frontend/src/pages/Dashboard.tsx` | Loading/error states |
| `frontend/src/pages/Trades.tsx` | Loading/error/empty states, i18n fix |
| `frontend/src/pages/Settings.tsx` | Error handling, i18n fixes |
| `.env.example` | JWT_SECRET_KEY now required |

---

## [2.1.0] - 2026-02-04

### Hinzugefuegt

#### Demo/Live Badge auf Trades
- **`demo_mode` Spalte** in `trade_records` Tabelle mit Auto-Migration
- **Demo/Live Badge** auf Trades-Seite und Dashboard (gelb = Demo, gruen = Live)
- **Mode-Filter** in der Trades-Tabelle (Spalte "Modus")
- i18n Keys fuer EN/DE

#### Dashboard Analytics Charts (Recharts)
- **PnL Chart** (Area + Line): Taeglicher PnL + kumulativer PnL im Zeitverlauf
- **Win/Loss Donut Chart**: Gewinne vs Verluste mit Win-Rate im Zentrum
- **Fees & Funding Bar Chart**: Gestapelte Balken fuer Gebuehren + Funding pro Tag
- **Zeitraum-Selector**: 7 / 14 / 30 / 90 Tage Filter fuer alle Charts
- **Erweiterte Statistik-Karten**: Net PnL (mit Fees/Funding Sub), Win Rate, Best/Worst Trade
- **Daily Stats API erweitert**: `/api/statistics/daily` liefert jetzt `funding`, `wins`, `losses` pro Tag

#### Discord Notifications bei Trade-Sync
- **Sync-Endpoint** (`POST /api/trades/sync`) sendet jetzt Discord-Benachrichtigungen wenn Trades geschlossen werden (TP/SL/Manual Close)
- Vorher wurden Trades beim Sync still geschlossen ohne Notification

### Behoben

#### TP/SL: Partial → Entire umgestellt
- **Problem:** TP/SL wurde als "Partial" gesetzt (nur Order-Groesse, nicht gesamte Position)
- **Ursache:** `presetStopSurplusPrice`/`presetStopLossPrice` auf dem Place-Order Endpoint erstellt Partial TP/SL
- **Fix:** Neue `_set_position_tpsl()` Methode nutzt `/api/v2/mix/order/place-pos-tpsl` Endpoint fuer Entire Position TP/SL
- **Hinweis:** `executePrice` Felder duerfen nicht mit "0" gesendet werden — werden komplett weggelassen fuer Market Execution

#### Bitget Demo API Header
- **Problem:** Demo-Trading schlug fehl mit "exchange environment is incorrect"
- **Ursache:** Header war `X-SIMULATED-TRADING` statt `paptrading: 1`
- **Fix:** `_get_headers()` in `client.py` nutzt jetzt korrekten Header

#### Discord Close Notification demo_mode Bug
- **Problem:** Close-Trade Endpoint sendete immer `demo_mode=True` unabhaengig vom tatsaechlichen Trade-Modus
- **Fix:** Nutzt jetzt `trade.demo_mode` statt hardcoded `True`

#### Vite Proxy Port Mismatch
- **Problem:** Frontend-Login schlug fehl im Development
- **Ursache:** Vite Proxy leitete an Port 8080 weiter, Backend laeuft auf Port 8000
- **Fix:** `vite.config.ts` Proxy-Target auf `localhost:8000` geaendert

### Geaendert

| Datei | Aenderung |
|-------|-----------|
| `src/exchanges/bitget/client.py` | `paptrading` Header, `_set_position_tpsl()`, Partial TP/SL entfernt |
| `src/models/database.py` | `demo_mode` Spalte |
| `src/models/session.py` | ALTER TABLE Migration |
| `src/api/schemas/trade.py` | `demo_mode` Feld |
| `src/api/routers/trades.py` | `demo_mode` in Response, Discord Sync Notifications |
| `src/api/routers/bot_control.py` | `demo_mode=True` bei Test-Trade, `trade.demo_mode` bei Close |
| `src/api/routers/statistics.py` | Daily Stats erweitert (funding/wins/losses) |
| `frontend/vite.config.ts` | Proxy-Port 8080 → 8000 |
| `frontend/src/types/index.ts` | `demo_mode` + `DailyStats` Interface |
| `frontend/src/pages/Dashboard.tsx` | Charts, Zeitraum-Selector, Demo/Live Badge |
| `frontend/src/pages/Trades.tsx` | Mode-Spalte mit Demo/Live Badge |
| `frontend/src/components/dashboard/` | NEU: PnlChart, WinLossChart, FeesChart, ChartTooltip |
| `frontend/src/i18n/en.json` + `de.json` | Neue Keys fuer Charts, Mode, Zeitraum |

### Neue Abhaengigkeiten (Frontend)

```
recharts (via npm)
```

---

## [1.10.0] - 2026-02-01

### Hinzugefuegt

#### Security Hardening v2
- **Explizite DEV_MODE Variable** (`DASHBOARD_DEV_MODE`)
  - Verhindert versehentlichen Auth-Bypass wenn API-Key vergessen wird
  - Startup-Warnung bei aktiviertem Dev-Mode
  - Bei fehlender Konfiguration: 503 Fehler statt stillschweigendem Bypass

- **WebSocket Header-basierte Authentifizierung**
  - Neuer Auth-Mechanismus via `Sec-WebSocket-Protocol: token.XXX`
  - Token nicht mehr in URL sichtbar (keine Log-Leakage)
  - Legacy URL-Parameter weiterhin unterstützt
  - JavaScript-Client aktualisiert für neue Auth-Methode

#### Performance & Stabilität
- **SQLite WAL-Mode** für bessere Concurrency
  - Write-Ahead Logging aktiviert in TradeDatabase und FundingTracker
  - `PRAGMA busy_timeout=5000` für Lock-Handling
  - Verhindert "database is locked" Fehler unter Last

### Geaendert

- **Dashboard Auth** (`src/dashboard/app.py`):
  - Neue Umgebungsvariable `DASHBOARD_DEV_MODE`
  - Bessere Fehlermeldungen bei Konfigurationsproblemen
  - WebSocket akzeptiert beide Auth-Methoden (Header + URL)

- **Tests**: Integration Tests patchen jetzt `DASHBOARD_DEV_MODE`

### Sicherheit

| Vorher | Nachher |
|--------|---------|
| Kein API-Key = Auth deaktiviert | Kein API-Key + kein DEV_MODE = 503 Fehler |
| WebSocket Token in URL (log-sichtbar) | WebSocket Token in Header (sicher) |
| SQLite ohne WAL (Locking-Probleme) | SQLite mit WAL (bessere Concurrency) |

### Konfiguration

Neue Umgebungsvariablen in `.env`:

```bash
# Development Mode (ONLY for local development!)
DASHBOARD_DEV_MODE=false

# Production: Always set API key
DASHBOARD_API_KEY=your-secure-api-key
```

---

## [1.9.0] - 2026-02-01

### Hinzugefuegt

#### Circuit Breaker & Retry Logic
Robuste Fehlerbehandlung für externe API-Aufrufe:

- **Circuit Breaker** (`src/utils/circuit_breaker.py`)
  - States: CLOSED → OPEN → HALF_OPEN → CLOSED
  - Automatische Erholung nach Timeout
  - Registry für mehrere Breaker (Bitget, Binance, etc.)
  - Decorator-basierte API: `@with_circuit_breaker("service_name")`

- **Retry mit Exponential Backoff**
  - tenacity-basiert
  - Konfigurierbare Wartezeiten und Versuche
  - Kombinierbar mit Circuit Breaker

- **Health Monitoring**
  - `/api/health/detailed` Endpoint
  - Circuit Breaker Status im Dashboard
  - Degraded-Status bei API-Ausfällen

#### Dashboard Erweiterungen
- **API Status Card**: Echtzeit-Status aller Komponenten
- **Error/Warning Banners**: Automatische Anzeige bei Problemen
- **Health Modal**: Detaillierte Systeminfo per Klick

### Test Suite
- **57 Unit Tests** für LiquidationHunter und RiskManager
- **15 Integration Tests** für Dashboard API
- Alle Tests bestehen (72 total)

### Technische Details

| Feature | Implementation |
|---------|----------------|
| Circuit Breaker | 3 States, konfigurierbarer Threshold |
| Retry | tenacity mit exponential backoff |
| Tests | pytest + pytest-asyncio |
| Coverage | LiquidationHunter, RiskManager, Dashboard API |

---

## [1.8.0] - 2026-01-31

### Hinzugefuegt

#### Bitget Demo Trading Integration
Vollständige Integration mit Bitget Demo Trading Account für realitätsnahes Paper Trading:

- **Separate Demo API Keys**: Unterstützung für dedizierte Demo Trading API Credentials
  - `BITGET_DEMO_API_KEY`, `BITGET_DEMO_API_SECRET`, `BITGET_DEMO_PASSPHRASE` in `.env`
  - Automatische Credential-Auswahl basierend auf `DEMO_MODE` Setting

- **BitgetClient Erweiterung** (`src/api/bitget_client.py`):
  - `demo_mode` Parameter im `__init__` für Modus-Auswahl
  - Automatisches Laden der korrekten API Keys (Demo vs. Live)
  - `X-SIMULATED-TRADING` Header für Demo Trading Requests
  - Logging zeigt aktiven Modus (DEMO/LIVE) bei Initialisierung

- **Settings Erweiterung** (`config/settings.py`):
  - `BitgetConfig.get_active_credentials(demo_mode)` - Liefert aktive Credentials
  - `BitgetConfig.validate(demo_mode)` - Validiert Demo oder Live API Keys
  - Separate Felder für Demo API Keys

- **Discord Notifications mit Mode Labels**:
  - `send_trade_entry()` und `send_trade_exit()` erweitert mit `demo_mode` Parameter
  - **🧪 DEMO** Label für Paper Trading Benachrichtigungen
  - **⚡ LIVE** Label für echte Trades
  - Mode Badge in Titel, Beschreibung und Footer
  - "Mode" als erstes Field für sofortige Sichtbarkeit

- **Trades im Bitget Account sichtbar**:
  - Demo Trades erscheinen im Bitget Demo Trading Account
  - Live Trades erscheinen im Bitget Live Account
  - Beide Modi nutzen echte Bitget Order Flow (REST API)

#### Steuerreport für Web Dashboard
Umfassende Steuerreport-Funktion für deutsche Steuerbehörden:

- **Backend**: `src/dashboard/tax_report.py`
  - `TaxReportGenerator` Klasse für Report-Generierung
  - Aggregation von Gewinnen, Verlusten, Gebühren, Funding-Kosten
  - Monatliche Aufschlüsselung der Performance
  - Zweisprachige Unterstützung (Deutsch/Englisch)
  - CSV-Export mit UTF-8 BOM für Excel-Kompatibilität

- **API Endpoints**:
  - `GET /api/tax-report/years` - Verfügbare Jahre mit Trade-Daten
  - `GET /api/tax-report/{year}?language={de|en}` - Tax-Report-Daten als JSON
  - `GET /api/tax-report/{year}/download?language={de|en}` - CSV-Download

- **Frontend**: Tax Report Sektion im Dashboard
  - Kalenderjahr-Auswahl (Dropdown mit verfügbaren Jahren)
  - Sprach-Toggle (Deutsch ⟷ English)
  - Live-Vorschau der Zusammenfassung (Gewinne, Verluste, Netto-PnL)
  - Chart.js Balkendiagramm für monatliche Performance
  - CSV-Download-Button

- **CSV-Format** (Steuerkonform):
  - Bilingual Headers (Deutsch/English)
  - 4 Sektionen: Header, Zusammenfassung, Einzeltransaktionen, Monatliche Aufschlüsselung
  - Haltedauer für jede Position (wichtig für deutsche Steuerberechnung)
  - Separate Funding Payments Auflistung
  - Disclaimer für Steuerberater-Konsultation

- **Deutsche Steuer-Compliance**:
  - Realized Gains/Losses Berechnung
  - Absetzbare Kosten (Gebühren, Funding) separiert
  - Haltedauer in Stunden für steuerliche Bewertung (<1 Jahr vs. ≥1 Jahr)

### Geaendert

- **TradeDatabase**: Neue Methode `get_trades_by_year(year)` für effizienten Jahres-basierten Zugriff
- **Dashboard UI**: Neue Tax Report Sektion nach Configuration-Card

### Dokumentation

- **DEPLOYMENT.md** (NEU): Umfassende Cloud-Deployment-Anleitung für DigitalOcean
  - Schritt-für-Schritt Setup für 24/7-Betrieb auf VPS
  - Droplet-Erstellung und Server-Konfiguration
  - Docker-Installation und Bot-Deployment
  - Nginx Reverse Proxy mit HTTPS/SSL (Let's Encrypt)
  - Firewall-Konfiguration (UFW) und SSH-Hardening
  - Systemd-Service für Auto-Start
  - Monitoring, Backups, und Wartungs-Skripte
  - Kosten-Übersicht (~$15/Monat für 2 GB Droplet)
  - Fehlerbehebung und Support-Ressourcen
- **SETUP.md**: Aktualisiert mit Hinweis auf Cloud-Deployment-Option (v1.8.0)
- **README.md**: DEPLOYMENT.md zur Dokumentations-Tabelle hinzugefügt

### Technische Details

| Komponente | Beschreibung |
|------------|--------------|
| Tax Report Generator | Python-Klasse mit i18n-Support |
| CSV Export | Built-in csv Modul mit UTF-8 BOM |
| Datenbank | SQLite mit Jahr-Filter via strftime('%Y', entry_time) |
| Frontend | Vanilla JavaScript + Chart.js für monatliches Diagramm |

---

## [1.7.0] - 2026-01-30

### Hinzugefuegt

#### Security Hardening
- **Environment-basierte Secrets**: Alle sensiblen Daten nur noch über Umgebungsvariablen
- **DASHBOARD_API_KEY**: Optionaler API-Key für Dashboard-Authentifizierung
  - Mode-Toggle-Endpoint erfordert API-Key wenn gesetzt
  - Read-Only Endpoints bleiben öffentlich
- **Dashboard Host Binding**: `DASHBOARD_HOST` konfigurierbar (Standard: 127.0.0.1)
  - Verhindert unbeabsichtigten externen Zugriff

#### Docker Support
- **Multi-Stage Dockerfile**: Optimierte Container-Images
  - Stage 1: Dependencies Build
  - Stage 2: Production Runtime
- **Docker Compose**: Vollständige Orchestrierung
  - Bot + Dashboard Service
  - Dashboard-Only Profile für Read-Only Betrieb
  - Health Checks integriert
  - Resource Limits (CPU/Memory)
- **Non-Root User**: Container läuft als unprivilegierter User (UID 1000)
- **Persistent Volumes**: `./data` und `./logs` gemountet

#### Dokumentation
- **Beginner Guide (German)**: Umfassende Anfänger-Anleitung
  - Schritt-für-Schritt Setup
  - Erklärungen zu allen Konzepten
  - Troubleshooting-Sektion

### Geaendert
- **`.env.example`**: Aktualisiert mit neuen Security-Parametern
- **README.md**: Docker-Anweisungen hinzugefügt
- **SETUP.md**: v1.7.0 Features dokumentiert

### Sicherheit
- Firewall-Empfehlungen in SETUP.md
- Reverse Proxy (nginx) Beispiel-Konfiguration
- IP-Whitelist Best Practices

---

## [1.6.0] - 2026-01-30

### Hinzugefuegt

#### WebSocket-Infrastruktur
- **Echtzeit-Updates**: WebSocket-Verbindung für Live-Daten
  - Position-Updates alle 5 Sekunden
  - Trade-Notifications bei Entry/Exit
  - Status-Updates bei Mode-Wechsel

#### Demo/Live Mode
- **Demo-Modus** (Standard): Simulierte Trades ohne echte Orderausführung
  - Alle Statistiken und Tracking funktionieren normal
  - Perfekt für Strategie-Tests
  - Empfohlen für 1-2 Wochen vor Live-Gang
- **Live-Modus**: Echte Trades auf Bitget
  - Echtes Geld involviert
  - Alle Sicherheitschecks aktiv
- **Mode-Toggle**:
  - Über Dashboard UI (mit Bestätigungs-Dialog)
  - Über API: `POST /api/mode/toggle`
  - Über Environment: `DEMO_MODE=true/false`
- **Persistenz**: Modus-Zustand wird in `data/bot_state.json` gespeichert

#### API-Endpunkte
- **`GET /api/mode`**: Aktuellen Trading-Modus abfragen
- **`POST /api/mode/toggle`**: Zwischen Demo/Live wechseln
  - Validierung: Keine offenen Positionen erlaubt
  - Bestätigung erforderlich

### Behoben (Critical Bug Fixes)
- **`execute_trade()` Fehler**: Live-Trading-Code wiederhergestellt
  - Bug: Demo-Modus-Check blockierte alle Order-Platzierungen
  - Fix: Korrekte Verzweigung Demo vs. Live
  - Impact: **Kritisch** - Bot konnte keine echten Trades platzieren
- **Position Monitoring**: Robustere Fehlerbehandlung
  - Timeout-Handling für API-Calls
  - Retry-Logik bei temporären Fehlern

### Technische Details
| Komponente | Technologie |
|------------|-------------|
| WebSocket | FastAPI WebSocketRoute |
| State Management | JSON-Persistenz in `data/bot_state.json` |
| Frontend Updates | JavaScript EventSource + WebSocket |

---

## [1.5.0] - 2026-01-29

### Hinzugefuegt

#### Web-Dashboard (Live-Monitoring)
Neues Echtzeit-Dashboard fuer den Trading Bot:

- **Backend**: FastAPI-basierter REST-API Server
  - `/api/status` - Bot-Status und Konfiguration
  - `/api/trades` - Trade-Historie und offene Positionen
  - `/api/statistics` - Performance-Statistiken
  - `/api/funding` - Funding-Rate Daten und Zahlungen
  - `/api/config` - Aktuelle Konfiguration
  - WebSocket fuer Echtzeit-Updates

- **Frontend**: Responsive Web-Interface
  - Equity-Kurve (30 Tage)
  - Funding-Rate Historie Chart
  - Offene Positionen Tabelle
  - Trade-Historie mit P&L
  - Konfigurations-Uebersicht

- **CLI**: `python main.py --dashboard [--dashboard-port 8080]`

#### Funding Rate Tracking
Vollstaendiges Tracking von Funding-Zahlungen:

- **`src/data/funding_tracker.py`**: Neues Modul
  - SQLite-Datenbank fuer Funding-Zahlungen
  - Automatische Aufzeichnung bei Funding-Zeiten (00:00, 08:00, 16:00 UTC)
  - Aggregierte Statistiken (total paid/received, avg rate)
  - Historische Funding-Rate Analyse

- **Integration in Trading Bot**:
  - Automatische Erfassung bei offenen Positionen
  - Korrekte PnL-Berechnung inkl. Funding-Kosten
  - Taeglich/woechentliche Funding-Uebersicht

- **API Endpoints**:
  - `GET /api/funding` - Funding-Statistiken
  - `GET /api/funding/history/{symbol}` - Rate-Historie

### Technische Details

| Komponente | Technologie |
|------------|-------------|
| Backend | FastAPI + uvicorn |
| Frontend | Tailwind CSS + Chart.js |
| Datenbank | SQLite (aiosqlite) |
| Updates | WebSocket (5s Intervall) |

### Neue Abhaengigkeiten
```
fastapi>=0.109.0
uvicorn>=0.27.0
```

---

## [1.4.0] - 2026-01-29

### Geaendert

#### Optimierte Strategie-Parameter
Basierend auf Backtest-Ergebnissen wurden folgende Parameter angepasst:

| Parameter | Alt | Neu | Grund |
|-----------|-----|-----|-------|
| Leverage | 3x | **4x** | Hoeherer Profit Factor erlaubt mehr Risiko |
| Take Profit | 3.5% | **4.0%** | Besseres R/R-Verhaeltnis |
| Stop Loss | 2.0% | **1.5%** | Schnellere Verlustbegrenzung |
| Position Size | 10% | **7.5%** | Geringere Kosten pro Trade |
| Max Trades/Tag | 3 | **2** | Fokus auf Qualitaet |
| Low Conf Min | 55% | **60%** | Weniger, bessere Trades |
| F&G Extreme Fear | <25 | **<20** | Nur echte Extreme |
| F&G Extreme Greed | >75 | **>80** | Nur echte Extreme |
| L/S Crowded Longs | >2.0 | **>2.5** | Staerkere Signale |
| L/S Crowded Shorts | <0.5 | **<0.4** | Staerkere Signale |

#### Alternative Datenquellen
- **CoinGecko API** als Fallback fuer Preisdaten wenn Binance nicht erreichbar
- Automatische Quellenauswahl in `fetch_klines_with_fallback()`

### Backtest-Vergleich (6 Monate, $10.000)

| Metrik | v1.3.0 (3x) | v1.4.0 (4x) | Aenderung |
|--------|-------------|-------------|-----------|
| Endkapital | $14,952.60 | **$22,259.47** | +48.9% |
| Gesamtrendite | +49.53% | **+122.59%** | +147.5% |
| Win Rate | 47.93% | 46.36% | -3.3% |
| Profit Factor | 1.33 | **1.89** | +42.1% |
| Max Drawdown | 9.23% | **7.24%** | -21.6% |
| Avg Win | $124.50 | **$163.50** | +31.3% |
| Avg Loss | -$86.45 | **-$74.66** | -13.6% |
| Kosten | $759.52 | **$656.76** | -13.5% |

#### Monatliche Performance (v1.4.0)
| Monat | P&L | Return |
|-------|-----|--------|
| 2025-08 | +$1,543.28 | +15.43% |
| 2025-09 | +$2,681.32 | +26.81% |
| 2025-10 | +$3,519.91 | +35.20% |
| 2025-11 | +$2,868.37 | +28.68% |
| 2025-12 | +$2,156.51 | +21.57% |
| 2026-01 | -$509.91 | -5.10% |

### Analyse
- **Win Rate unter 50% ist OK**: Der Profit Factor von 1.89 bedeutet, dass Gewinne im Schnitt 89% groesser sind als Verluste
- **Drawdown reduziert**: Trotz hoeherem Leverage sank der Max Drawdown von 9.23% auf 7.24%
- **Kosten gesenkt**: Durch weniger, aber bessere Trades sanken die Kosten um 13.5%

---

## [1.3.0] - 2026-01-29

### Hinzugefuegt

#### Backtesting-Modul
- **`src/backtest/historical_data.py`**: Historische Daten-Fetcher mit Caching
  - Fear & Greed Index (Alternative.me API)
  - Long/Short Ratio (Binance Futures)
  - Funding Rates (Binance)
  - Preisdaten OHLCV (Binance)
- **`src/backtest/engine.py`**: Backtest-Engine mit Trade-Simulation
  - Vollstaendige Strategie-Simulation
  - TP/SL basierend auf Intraday High/Low
  - Gebuehren- und Funding-Berechnung
- **`src/backtest/report.py`**: Report-Generator mit Empfehlungen
  - Konsolen-Report mit ASCII-Charts
  - JSON-Export fuer detaillierte Analyse
  - Automatische Empfehlungen basierend auf Metriken
- **`src/backtest/mock_data.py`**: Simulierte Daten fuer Offline-Tests
- **CLI-Integration**: `python main.py --backtest`
  - `--backtest-days N`: Anzahl Tage (Standard: 180)
  - `--backtest-capital N`: Startkapital (Standard: 10000)

#### Profit Lock-In Feature
Neues Risikomanagement-Feature in `risk_manager.py`:
- **Funktion**: Sperrt Gewinne dynamisch, um positive Tage zu schuetzen
- **Logik**: Bei Gewinn wird das Verlustlimit automatisch reduziert
- **Konfiguration**:
  - `enable_profit_lock`: Feature ein/aus (Standard: True)
  - `profit_lock_percent`: Anteil der gesperrten Gewinne (Standard: 75%)
  - `min_profit_floor`: Mindestgewinn der erhalten bleibt (Standard: 0.5%)

**Beispiel:**
| Tages-PnL | Standard Limit | Mit Profit Lock | Garantiert |
|-----------|----------------|-----------------|------------|
| +0% | -5% | -5% | -5% |
| +2% | -5% | -1.5% | +0.5% |
| +4% | -5% | -3.5% | +0.5% |

### Backtest-Ergebnisse (6 Monate, $10.000, 3x Leverage)

| Metrik | Wert | Bewertung |
|--------|------|-----------|
| Zeitraum | 2025-08-02 bis 2026-01-28 | 179 Tage |
| Startkapital | $10,000.00 | - |
| Endkapital | $14,952.60 | +49.53% |
| Max Drawdown | 9.23% | OK |
| Anzahl Trades | 338 | ~1.9/Tag |
| Win Rate | 47.93% | Unter Ziel |
| Profit Factor | 1.33 | OK |
| Gebuehren | $535.40 | 5.4% |
| Funding | $224.12 | 2.2% |

#### Monatliche Performance
| Monat | P&L | Return |
|-------|-----|--------|
| 2025-08 | +$955.83 | +9.56% |
| 2025-09 | +$1,788.03 | +17.88% |
| 2025-10 | +$1,006.08 | +10.06% |
| 2025-11 | +$1,037.60 | +10.38% |
| 2025-12 | +$1,244.69 | +12.45% |
| 2026-01 | -$1,079.62 | -10.80% |

### Empfehlungen basierend auf Backtest

Die Win Rate liegt mit 47.93% unter dem Ziel von 60%. Folgende Anpassungen werden empfohlen:

| Parameter | Aktuell | Empfohlen | Grund |
|-----------|---------|-----------|-------|
| Low Conf Min | 55% | 60% | Weniger Trades, hoehere Qualitaet |
| Take Profit | 3.5% | 4.0% | Besseres Risiko/Reward |
| Stop Loss | 2.0% | 1.5% | Schnellere Verlustbegrenzung |
| Position Size | 10% | 7.5% | Geringere Kosten |

**Strategie-Anpassungen:**
1. Nur bei echten Extremen handeln (F&G < 20 oder > 80)
2. L/S Ratio Thresholds erhoehen (>2.5 statt >2.0)
3. Trades pro Tag auf 2 reduzieren

---

## [1.2.0] - 2026-01-29

### Behoben (Bug Fixes)
- **Kritisch**: Preis-Validierung in `liquidation_hunter.py` hinzugefügt
  - Verhindert fehlerhafte TP/SL-Berechnung wenn Preis = 0 (API-Fehler)
  - Signal wird nun korrekt abgelehnt bei ungültigem Preis
- **Import-Fehler**: `timedelta` in `risk_manager.py` korrigiert
  - War am Ende der Datei (Zeile 503) statt am Anfang importiert
  - Konnte zu `NameError` bei historischen Statistiken führen

### Bereinigt (Code Cleanup)
- **`bitget_client.py`**: Unbenutzte Imports entfernt
  - `asyncio`, `Decimal`, `requests` entfernt
  - `json` Import an den Dateianfang verschoben
- **`market_data.py`**: Unbenutzte Imports entfernt
  - `timedelta`, `requests` entfernt
- **`trading_bot.py`**: Unbenutzte Imports entfernt
  - `time`, `TradeStatus` entfernt

### Code-Review Ergebnisse
| Datei | Problem | Schwere | Status |
|-------|---------|---------|--------|
| `liquidation_hunter.py:356` | Keine Preis-Validierung | **Hoch** | ✅ Behoben |
| `risk_manager.py:503` | `timedelta` am Dateiende | Mittel | ✅ Behoben |
| `bitget_client.py:6,13,16,118` | Unbenutzte/falsche Imports | Gering | ✅ Behoben |
| `market_data.py:14,18` | Unbenutzte Imports | Gering | ✅ Behoben |
| `trading_bot.py:18,29` | Unbenutzte Imports | Gering | ✅ Behoben |

---

## [1.1.1] - 2026-01-29

### Hinzugefügt
- **Dokumentation**: Umfassende Projekt-Dokumentation erstellt
  - `CHANGELOG.md` - Versions-Historie (dieses Dokument)
  - `docs/STRATEGY.md` - Detaillierte Strategie-Erklärung
  - `docs/SETUP.md` - Installations- und Konfigurations-Anleitung
  - `docs/API.md` - Technische API-Referenz
  - `docs/FAQ.md` - Häufig gestellte Fragen
- **README.md**: Dokumentations-Übersicht mit Links hinzugefügt

---

## [1.1.0] - 2026-01-29

### Geändert
- **Leverage reduziert**: Von 5x auf 3x für ausgewogeneres Risiko
- **Trading-Zeitplan optimiert**: Angepasst an globale Markt-Sessions

### Trading-Zeitplan (NEU)
| Zeit (UTC) | Session | Begründung |
|------------|---------|------------|
| 01:00 | Asia (Tokyo +1h) | Reaktion auf US-Session, Liquidation-Kaskaden |
| 08:00 | EU Open (London) | Europäische Trader steigen ein |
| 14:00 | US Open + ETFs | **Kritisch!** BTC-ETF Flows (IBIT, FBTC) |
| 21:00 | US Close | End-of-Day Profit-Taking |

### Begründung
- US-ETF-Handel (14:00 UTC) ist entscheidend für institutionelle Flows
- Bessere Abdeckung aller wichtigen Handelssessions
- Optimiert für Liquidation-Hunting bei Session-Übergängen

---

## [1.0.0] - 2026-01-29

### Hinzugefügt

#### Core Trading System
- **Bitget API Client** (`src/api/bitget_client.py`)
  - Vollständige Futures-API Integration
  - Order-Platzierung (Market/Limit)
  - Position Management
  - Leverage-Einstellung
  - Account Balance Abfragen

#### Daten-Module
- **Market Data Fetcher** (`src/data/market_data.py`)
  - Fear & Greed Index (Alternative.me API)
  - Long/Short Ratio (Binance Futures)
  - Funding Rates (Binance/Bitget)
  - Open Interest
  - 24h Ticker Data
  - Volatilitäts-Berechnung
  - Trend-Erkennung (SMA-basiert)

#### Strategie
- **Contrarian Liquidation Hunter** (`src/strategy/liquidation_hunter.py`)
  - Leverage-Analyse (L/S Ratio Thresholds)
  - Sentiment-Analyse (Fear & Greed)
  - Funding Rate Kosten-Analyse
  - Confidence-basierte Signal-Generierung
  - NO NEUTRALITY Prinzip - immer eine Richtung

#### Risk Management
- **Risk Manager** (`src/risk/risk_manager.py`)
  - Daily Loss Limit (Standard: 5%)
  - Maximum Trades pro Tag (Standard: 3)
  - Confidence-basierte Position Sizing
  - Automatischer Trading-Stopp bei Verlustgrenze
  - Tägliche Statistik-Persistenz

#### Benachrichtigungen
- **Discord Notifier** (`src/notifications/discord_notifier.py`)
  - Trade Entry Notifications
  - Trade Exit Notifications mit PnL, ROI, Fees
  - Daily Summary Reports
  - Risk Alerts
  - Bot Status Updates
  - Error Notifications

#### Persistenz
- **Trade Database** (`src/models/trade_database.py`)
  - SQLite-basierte Trade-Speicherung
  - Historische Statistiken
  - Performance-Tracking
  - Open/Closed Trade Queries

#### Bot Orchestrierung
- **Trading Bot** (`src/bot/trading_bot.py`)
  - Scheduler-basierte Marktanalyse
  - Position Monitoring (alle 5 Minuten)
  - Automatische TP/SL Erkennung
  - Graceful Shutdown Handling
  - Daily Summary Generation

#### Konfiguration
- Environment-basierte Konfiguration (`.env`)
- Alle Parameter anpassbar
- Testnet-Unterstützung

### Strategie-Parameter (Initial)
| Parameter | Wert |
|-----------|------|
| Daily Loss Limit | 5% |
| Max Trades/Tag | 3 |
| Take Profit | 3.5% |
| Stop Loss | 2.0% |
| Position Size | 10% (Basis) |
| Leverage | 5x (später 3x) |
| Fear & Greed Extreme Fear | <25 |
| Fear & Greed Extreme Greed | >75 |
| L/S Crowded Longs | >2.0 |
| L/S Crowded Shorts | <0.5 |

---

## Versions-Schema

- **MAJOR** (X.0.0): Breaking Changes, fundamentale Strategie-Änderungen
- **MINOR** (0.X.0): Neue Features, Parameter-Anpassungen
- **PATCH** (0.0.X): Bug Fixes, kleine Optimierungen

---

## Links

- [README](README.md) - Projektübersicht
- [Strategie-Dokumentation](docs/STRATEGY.md) - Detaillierte Strategie-Erklärung
- [Setup-Anleitung](docs/SETUP.md) - Installation und Konfiguration
- [API-Referenz](docs/API.md) - Code-Dokumentation
