"""Centralized error message constants.

All user-facing error strings live here so source code and tests share
the same constant.  Changing wording only requires editing this file.
"""

# ── Auth / Dependencies ──────────────────────────────────────────────
ERR_NOT_AUTHENTICATED = "Nicht authentifiziert"
ERR_INVALID_TOKEN = "Ungültiger oder abgelaufener Token"
ERR_INVALID_TOKEN_PAYLOAD = "Ungültiger Token-Inhalt"
ERR_USER_NOT_FOUND_OR_INACTIVE = "Benutzer nicht gefunden oder inaktiv"
ERR_TOKEN_REVOKED = "Token widerrufen — bitte erneut anmelden"
ERR_ADMIN_REQUIRED = "Admin-Zugriff erforderlich"

# ── Auth / Login ─────────────────────────────────────────────────────
ERR_INVALID_CREDENTIALS = "Ungültiger Benutzername oder Passwort"
ERR_ACCOUNT_LOCKED = "Konto vorübergehend gesperrt. Versuche es später erneut."
ERR_ACCOUNT_DISABLED = "Konto ist deaktiviert"
ERR_INVALID_REFRESH_TOKEN = "Ungültiger Refresh-Token"
ERR_CURRENT_PASSWORD_WRONG = "Aktuelles Passwort ist falsch"

# ── Auth / Two-Factor Authentication ────────────────────────────────
ERR_2FA_ALREADY_ENABLED = "Zwei-Faktor-Authentifizierung ist bereits aktiviert"
ERR_2FA_NOT_ENABLED = "Zwei-Faktor-Authentifizierung ist nicht aktiviert"
ERR_2FA_SETUP_NOT_STARTED = "2FA-Einrichtung nicht gestartet. Bitte zuerst /2fa/setup aufrufen."
ERR_2FA_INVALID_CODE = "Ungültiger 2FA-Code"
ERR_2FA_REQUIRED = "Zwei-Faktor-Authentifizierung erforderlich"
ERR_2FA_TEMP_TOKEN_INVALID = "Ungültiger oder abgelaufener temporärer Token"
ERR_2FA_RATE_LIMIT = "Zu viele 2FA-Versuche. Bitte warte eine Minute."

# ── Auth / Sessions ─────────────────────────────────────────────────
ERR_SESSION_NOT_FOUND = "Sitzung nicht gefunden"

# ── Bots / Lifecycle ─────────────────────────────────────────────────
ERR_BOT_NOT_FOUND = "Bot nicht gefunden"
ERR_BOT_NOT_RUNNING = "Bot läuft nicht"
ERR_SYMBOL_CONFLICT = "Symbol-Konflikt: {symbols} wird bereits von einem aktiven Bot auf dieser Exchange gehandelt"
ERR_NO_OPEN_TRADE = "Kein offener Trade für {symbol} gefunden"
ERR_NO_EXCHANGE_CONNECTION = "Keine Exchange-Verbindung konfiguriert"
ERR_EXCHANGE_CREDENTIALS_MISSING = "Exchange-Zugangsdaten nicht konfiguriert"
ERR_POSITION_CLOSE_FAILED = "Position {symbol} konnte auf der Exchange nicht geschlossen werden. Bitte manuell auf der Exchange schliessen."
ERR_POSITION_VERIFY_FAILED = "Position {symbol}: Status konnte nach dem Schliessen nicht verifiziert werden. Bitte auf der Exchange pruefen."
ERR_TELEGRAM_NOT_CONFIGURED = "Telegram nicht konfiguriert"
ERR_TELEGRAM_SEND_FAILED = "Telegram-Nachricht konnte nicht gesendet werden"
ERR_STOP_BOT_BEFORE_EDIT = "Stoppe den Bot bevor du die Konfiguration bearbeitest"
ERR_MAX_BOTS_REACHED = "Maximal {max_bots} Bots pro Benutzer erlaubt"
ERR_ORCHESTRATOR_NOT_INITIALIZED = "Bot-Orchestrator nicht initialisiert"
ERR_WHATSAPP_NOT_CONFIGURED = "WhatsApp nicht konfiguriert"
ERR_WHATSAPP_SEND_FAILED = "WhatsApp-Nachricht konnte nicht gesendet werden"
ERR_PENDING_TRADE_NOT_FOUND = "Ausstehender Trade nicht gefunden"
ERR_TRADE_ALREADY_RESOLVED = "Trade ist bereits abgeschlossen"

# ── Bots / Affiliate Gate ────────────────────────────────────────────
ERR_AFFILIATE_REQUIRED = "Registriere dich zuerst über unseren Affiliate-Link, trage dann deine UID unter Einstellungen → API Keys ein."
ERR_AFFILIATE_PENDING = "Deine UID wurde eingereicht, ist aber noch nicht freigegeben. Bitte warte auf die Freigabe durch einen Admin."

# ── Bots / Hyperliquid Gate ──────────────────────────────────────────
ERR_NO_HL_CONNECTION = "Keine Hyperliquid-Verbindung konfiguriert."
ERR_HL_REFERRAL_REQUIRED = "Referral erforderlich. Bitte registriere dich über https://app.hyperliquid.xyz/join/{referral_code} bevor du Hyperliquid Bots nutzen kannst."
ERR_HL_BUILDER_FEE_NOT_APPROVED = "Builder Fee nicht genehmigt. Bitte genehmige die Builder Fee auf der Website."

# ── Config / Exchange Keys ───────────────────────────────────────────
ERR_NO_API_KEYS_FOR = "Keine API-Keys für {exchange_type} konfiguriert"
ERR_NO_LIVE_API_KEYS = "Keine Live-API-Keys konfiguriert"
ERR_NO_DEMO_API_KEYS = "Keine Demo-API-Keys konfiguriert"
ERR_NO_API_KEYS = "Keine API-Keys konfiguriert"
ERR_CONNECTION_FAILED = "Verbindung fehlgeschlagen. Prüfe deine Zugangsdaten und versuche es erneut."
ERR_CONNECTION_TEST_FAILED = "Verbindungstest fehlgeschlagen"
ERR_LLM_CONNECTION_FAILED = "Verbindung fehlgeschlagen. Prüfe deinen API-Key und versuche es erneut."

# ── Config / Hyperliquid Admin ───────────────────────────────────────
ERR_INVALID_BUILDER_ADDRESS = "Builder-Adresse muss eine gültige Ethereum-Adresse sein (0x + 40 Hex-Zeichen)"
ERR_INVALID_REFERRAL_CODE = "Referral-Code muss alphanumerisch sein (max. 50 Zeichen)"
ERR_NO_DEMO_API_KEYS_HL = "Keine Demo-API-Keys für Hyperliquid"
ERR_NO_LIVE_API_KEYS_HL = "Keine Live-API-Keys für Hyperliquid"
ERR_NO_HL_CONNECTION_PLAIN = "Keine Hyperliquid-Verbindung konfiguriert"
ERR_BUILDER_FEE_NOT_FOUND = "Builder-Fee-Genehmigung nicht auf Hyperliquid gefunden. Bitte erneut signieren."
ERR_REFERRAL_NOT_FOUND = "Referral nicht gefunden. Bitte registriere dich zuerst über https://app.hyperliquid.xyz/join/{referral_code}"
ERR_REFERRAL_CHECK_FAILED = "Referral-Prüfung fehlgeschlagen. Siehe Server-Logs."
ERR_REVENUE_SUMMARY_FAILED = "Umsatzübersicht konnte nicht geladen werden. Siehe Server-Logs."

# ── Config / Affiliate UID ───────────────────────────────────────────
ERR_AFFILIATE_UID_NOT_FOUND = "Affiliate-UID nicht gefunden"
ERR_AFFILIATE_LINK_NOT_FOUND = "Affiliate-Link nicht gefunden"
ERR_UID_EMPTY = "UID darf nicht leer sein"
ERR_BITGET_UID_NUMERIC = "Bitget UID muss rein numerisch sein"
ERR_WEEX_UID_ALPHANUMERIC = "Weex UID muss alphanumerisch sein"
ERR_BITUNIX_UID_NUMERIC = "Bitunix UID muss rein numerisch sein"
ERR_BINGX_UID_NUMERIC = "BingX UID muss rein numerisch sein"

# ── Exchanges ────────────────────────────────────────────────────────
ERR_INVALID_EXCHANGE = "Ungültiger Exchange-Name"
ERR_EXCHANGE_NOT_FOUND = "Exchange '{name}' nicht gefunden"
ERR_NO_CONNECTION_FOR = "Keine Verbindung für {name} konfiguriert"
ERR_NO_API_KEY_FOR = "Kein API-Key für {name} konfiguriert"

# ── Validation ──────────────────────────────────────────────────────
ERR_INVALID_ETH_ADDRESS = "{label} muss eine gültige Ethereum-Adresse sein (0x + 40 Hex-Zeichen)"
ERR_INVALID_HEX_KEY = "{label} muss 64 Hex-Zeichen sein (mit oder ohne 0x-Prefix)"

# ── Strategy ────────────────────────────────────────────────────────
ERR_STRATEGY_NOT_FOUND = "Strategie nicht gefunden: {name}"

# ── Users ────────────────────────────────────────────────────────────
ERR_USERNAME_EXISTS = "Benutzername existiert bereits"
ERR_USER_NOT_FOUND = "Benutzer nicht gefunden"
ERR_CANNOT_DELETE_SELF = "Du kannst dich nicht selbst löschen"

# ── Trades ─────────────────────────────────────────────────────────
ERR_TRADE_NOT_FOUND = "Trade nicht gefunden"
