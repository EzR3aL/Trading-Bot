"""Centralized error message constants.

All user-facing error strings live here so source code and tests share
the same constant.  Changing wording only requires editing this file.

Messages are bilingual (German + English).  The API returns the German
string by default; the frontend's i18n layer can map error codes to the
user's language.  Each constant has a corresponding _EN variant for
direct English access when needed.
"""

# ── Auth / Dependencies ──────────────────────────────────────────────
ERR_NOT_AUTHENTICATED = "Nicht authentifiziert"
ERR_NOT_AUTHENTICATED_EN = "Not authenticated"
ERR_INVALID_TOKEN = "Ungültiger oder abgelaufener Token"
ERR_INVALID_TOKEN_EN = "Invalid or expired token"
ERR_INVALID_TOKEN_PAYLOAD = "Ungültiger Token-Inhalt"
ERR_INVALID_TOKEN_PAYLOAD_EN = "Invalid token payload"
ERR_USER_NOT_FOUND_OR_INACTIVE = "Benutzer nicht gefunden oder inaktiv"
ERR_USER_NOT_FOUND_OR_INACTIVE_EN = "User not found or inactive"
ERR_TOKEN_REVOKED = "Token widerrufen — bitte erneut anmelden"
ERR_TOKEN_REVOKED_EN = "Token revoked — please log in again"
ERR_ADMIN_REQUIRED = "Admin-Zugriff erforderlich"
ERR_ADMIN_REQUIRED_EN = "Admin access required"

# ── Auth / Login ─────────────────────────────────────────────────────
ERR_INVALID_CREDENTIALS = "Ungültiger Benutzername oder Passwort"
ERR_INVALID_CREDENTIALS_EN = "Invalid username or password"
ERR_ACCOUNT_LOCKED = "Konto vorübergehend gesperrt. Versuche es später erneut."
ERR_ACCOUNT_LOCKED_EN = "Account temporarily locked. Please try again later."
ERR_ACCOUNT_DISABLED = "Konto ist deaktiviert"
ERR_ACCOUNT_DISABLED_EN = "Account is disabled"
ERR_INVALID_REFRESH_TOKEN = "Ungültiger Refresh-Token"
ERR_INVALID_REFRESH_TOKEN_EN = "Invalid refresh token"
ERR_CURRENT_PASSWORD_WRONG = "Aktuelles Passwort ist falsch"
ERR_CURRENT_PASSWORD_WRONG_EN = "Current password is incorrect"

# ── Auth / Two-Factor Authentication ────────────────────────────────
ERR_2FA_ALREADY_ENABLED = "Zwei-Faktor-Authentifizierung ist bereits aktiviert"
ERR_2FA_ALREADY_ENABLED_EN = "Two-factor authentication is already enabled"
ERR_2FA_NOT_ENABLED = "Zwei-Faktor-Authentifizierung ist nicht aktiviert"
ERR_2FA_NOT_ENABLED_EN = "Two-factor authentication is not enabled"
ERR_2FA_SETUP_NOT_STARTED = "2FA-Einrichtung nicht gestartet. Bitte zuerst /2fa/setup aufrufen."
ERR_2FA_SETUP_NOT_STARTED_EN = "2FA setup not started. Please call /2fa/setup first."
ERR_2FA_INVALID_CODE = "Ungültiger 2FA-Code"
ERR_2FA_INVALID_CODE_EN = "Invalid 2FA code"
ERR_2FA_REQUIRED = "Zwei-Faktor-Authentifizierung erforderlich"
ERR_2FA_REQUIRED_EN = "Two-factor authentication required"
ERR_2FA_TEMP_TOKEN_INVALID = "Ungültiger oder abgelaufener temporärer Token"
ERR_2FA_TEMP_TOKEN_INVALID_EN = "Invalid or expired temporary token"
ERR_2FA_RATE_LIMIT = "Zu viele 2FA-Versuche. Bitte warte eine Minute."
ERR_2FA_RATE_LIMIT_EN = "Too many 2FA attempts. Please wait a minute."

# ── Auth / Sessions ─────────────────────────────────────────────────
ERR_SESSION_NOT_FOUND = "Sitzung nicht gefunden"
ERR_SESSION_NOT_FOUND_EN = "Session not found"

# ── Bots / Lifecycle ─────────────────────────────────────────────────
ERR_BOT_NOT_FOUND = "Bot nicht gefunden"
ERR_BOT_NOT_FOUND_EN = "Bot not found"
ERR_BOT_NOT_RUNNING = "Bot läuft nicht"
ERR_BOT_NOT_RUNNING_EN = "Bot is not running"
ERR_SYMBOL_CONFLICT = "Symbol-Konflikt: {symbols} wird bereits von einem aktiven Bot auf dieser Exchange gehandelt"
ERR_SYMBOL_CONFLICT_EN = "Symbol conflict: {symbols} is already traded by an active bot on this exchange"
ERR_NO_OPEN_TRADE = "Kein offener Trade für {symbol} gefunden"
ERR_NO_OPEN_TRADE_EN = "No open trade found for {symbol}"
ERR_NO_EXCHANGE_CONNECTION = "Keine Exchange-Verbindung konfiguriert"
ERR_NO_EXCHANGE_CONNECTION_EN = "No exchange connection configured"
ERR_EXCHANGE_CREDENTIALS_MISSING = "Exchange-Zugangsdaten nicht konfiguriert"
ERR_EXCHANGE_CREDENTIALS_MISSING_EN = "Exchange credentials not configured"
ERR_POSITION_CLOSE_FAILED = "Position {symbol} konnte auf der Exchange nicht geschlossen werden. Bitte manuell auf der Exchange schliessen."
ERR_POSITION_CLOSE_FAILED_EN = "Position {symbol} could not be closed on the exchange. Please close manually."
ERR_POSITION_VERIFY_FAILED = "Position {symbol}: Status konnte nach dem Schliessen nicht verifiziert werden. Bitte auf der Exchange pruefen."
ERR_POSITION_VERIFY_FAILED_EN = "Position {symbol}: Status could not be verified after closing. Please check on the exchange."
ERR_TELEGRAM_NOT_CONFIGURED = "Telegram nicht konfiguriert"
ERR_TELEGRAM_NOT_CONFIGURED_EN = "Telegram not configured"
ERR_TELEGRAM_SEND_FAILED = "Telegram-Nachricht konnte nicht gesendet werden"
ERR_TELEGRAM_SEND_FAILED_EN = "Failed to send Telegram message"
ERR_STOP_BOT_BEFORE_EDIT = "Stoppe den Bot bevor du die Konfiguration bearbeitest"
ERR_STOP_BOT_BEFORE_EDIT_EN = "Stop the bot before editing its configuration"
ERR_MAX_BOTS_REACHED = "Maximal {max_bots} Bots pro Benutzer erlaubt"
ERR_MAX_BOTS_REACHED_EN = "Maximum {max_bots} bots per user allowed"
ERR_ORCHESTRATOR_NOT_INITIALIZED = "Bot-Orchestrator nicht initialisiert"
ERR_ORCHESTRATOR_NOT_INITIALIZED_EN = "Bot orchestrator not initialized"
ERR_WHATSAPP_NOT_CONFIGURED = "WhatsApp nicht konfiguriert"
ERR_WHATSAPP_NOT_CONFIGURED_EN = "WhatsApp not configured"
ERR_WHATSAPP_SEND_FAILED = "WhatsApp-Nachricht konnte nicht gesendet werden"
ERR_WHATSAPP_SEND_FAILED_EN = "Failed to send WhatsApp message"
ERR_PENDING_TRADE_NOT_FOUND = "Ausstehender Trade nicht gefunden"
ERR_PENDING_TRADE_NOT_FOUND_EN = "Pending trade not found"
ERR_TRADE_ALREADY_RESOLVED = "Trade ist bereits abgeschlossen"
ERR_TRADE_ALREADY_RESOLVED_EN = "Trade is already resolved"

# ── Bots / Affiliate Gate ────────────────────────────────────────────
ERR_AFFILIATE_REQUIRED = "Registriere dich zuerst über unseren Affiliate-Link, trage dann deine UID unter Einstellungen → API Keys ein."
ERR_AFFILIATE_REQUIRED_EN = "Please register via our affiliate link first, then enter your UID under Settings → API Keys."
ERR_AFFILIATE_PENDING = "Deine UID wurde eingereicht, ist aber noch nicht freigegeben. Bitte warte auf die Freigabe durch einen Admin."
ERR_AFFILIATE_PENDING_EN = "Your UID has been submitted but is not yet approved. Please wait for admin approval."

# ── Bots / Hyperliquid Gate ──────────────────────────────────────────
ERR_NO_HL_CONNECTION = "Keine Hyperliquid-Verbindung konfiguriert."
ERR_NO_HL_CONNECTION_EN = "No Hyperliquid connection configured."
ERR_HL_REFERRAL_REQUIRED = "Referral erforderlich. Bitte registriere dich über https://app.hyperliquid.xyz/join/{referral_code} bevor du Hyperliquid Bots nutzen kannst."
ERR_HL_REFERRAL_REQUIRED_EN = "Referral required. Please register via https://app.hyperliquid.xyz/join/{referral_code} before using Hyperliquid bots."
ERR_HL_BUILDER_FEE_NOT_APPROVED = "Builder Fee nicht genehmigt. Bitte genehmige die Builder Fee auf der Website."
ERR_HL_BUILDER_FEE_NOT_APPROVED_EN = "Builder fee not approved. Please approve the builder fee on the website."

# ── Config / Exchange Keys ───────────────────────────────────────────
ERR_NO_API_KEYS_FOR = "Keine API-Keys für {exchange_type} konfiguriert"
ERR_NO_API_KEYS_FOR_EN = "No API keys configured for {exchange_type}"
ERR_NO_LIVE_API_KEYS = "Keine Live-API-Keys konfiguriert"
ERR_NO_LIVE_API_KEYS_EN = "No live API keys configured"
ERR_NO_DEMO_API_KEYS = "Keine Demo-API-Keys konfiguriert"
ERR_NO_DEMO_API_KEYS_EN = "No demo API keys configured"
ERR_NO_API_KEYS = "Keine API-Keys konfiguriert"
ERR_NO_API_KEYS_EN = "No API keys configured"
ERR_CONNECTION_FAILED = "Verbindung fehlgeschlagen. Prüfe deine Zugangsdaten und versuche es erneut."
ERR_CONNECTION_FAILED_EN = "Connection failed. Check your credentials and try again."
ERR_CONNECTION_TEST_FAILED = "Verbindungstest fehlgeschlagen"
ERR_CONNECTION_TEST_FAILED_EN = "Connection test failed"
ERR_LLM_CONNECTION_FAILED = "Verbindung fehlgeschlagen. Prüfe deinen API-Key und versuche es erneut."
ERR_LLM_CONNECTION_FAILED_EN = "Connection failed. Check your API key and try again."

# ── Config / Hyperliquid Admin ───────────────────────────────────────
ERR_INVALID_BUILDER_ADDRESS = "Builder-Adresse muss eine gültige Ethereum-Adresse sein (0x + 40 Hex-Zeichen)"
ERR_INVALID_BUILDER_ADDRESS_EN = "Builder address must be a valid Ethereum address (0x + 40 hex characters)"
ERR_INVALID_REFERRAL_CODE = "Referral-Code muss alphanumerisch sein (max. 50 Zeichen)"
ERR_INVALID_REFERRAL_CODE_EN = "Referral code must be alphanumeric (max 50 characters)"
ERR_NO_DEMO_API_KEYS_HL = "Keine Demo-API-Keys für Hyperliquid"
ERR_NO_DEMO_API_KEYS_HL_EN = "No demo API keys for Hyperliquid"
ERR_NO_LIVE_API_KEYS_HL = "Keine Live-API-Keys für Hyperliquid"
ERR_NO_LIVE_API_KEYS_HL_EN = "No live API keys for Hyperliquid"
ERR_NO_HL_CONNECTION_PLAIN = "Keine Hyperliquid-Verbindung konfiguriert"
ERR_NO_HL_CONNECTION_PLAIN_EN = "No Hyperliquid connection configured"
ERR_BUILDER_FEE_NOT_FOUND = "Builder-Fee-Genehmigung nicht auf Hyperliquid gefunden. Bitte erneut signieren."
ERR_BUILDER_FEE_NOT_FOUND_EN = "Builder fee approval not found on Hyperliquid. Please sign again."
ERR_REFERRAL_NOT_FOUND = "Referral nicht gefunden. Bitte registriere dich zuerst über https://app.hyperliquid.xyz/join/{referral_code}"
ERR_REFERRAL_NOT_FOUND_EN = "Referral not found. Please register first via https://app.hyperliquid.xyz/join/{referral_code}"
ERR_REFERRAL_CHECK_FAILED = "Referral-Prüfung fehlgeschlagen. Siehe Server-Logs."
ERR_REFERRAL_CHECK_FAILED_EN = "Referral check failed. See server logs."
ERR_REVENUE_SUMMARY_FAILED = "Umsatzübersicht konnte nicht geladen werden. Siehe Server-Logs."
ERR_REVENUE_SUMMARY_FAILED_EN = "Revenue summary could not be loaded. See server logs."

# ── Config / Affiliate UID ───────────────────────────────────────────
ERR_AFFILIATE_UID_NOT_FOUND = "Affiliate-UID nicht gefunden"
ERR_AFFILIATE_UID_NOT_FOUND_EN = "Affiliate UID not found"
ERR_AFFILIATE_LINK_NOT_FOUND = "Affiliate-Link nicht gefunden"
ERR_AFFILIATE_LINK_NOT_FOUND_EN = "Affiliate link not found"
ERR_UID_EMPTY = "UID darf nicht leer sein"
ERR_UID_EMPTY_EN = "UID must not be empty"
ERR_BITGET_UID_NUMERIC = "Bitget UID muss rein numerisch sein"
ERR_BITGET_UID_NUMERIC_EN = "Bitget UID must be numeric"
ERR_WEEX_UID_ALPHANUMERIC = "Weex UID muss alphanumerisch sein"
ERR_WEEX_UID_ALPHANUMERIC_EN = "Weex UID must be alphanumeric"
ERR_BITUNIX_UID_NUMERIC = "Bitunix UID muss rein numerisch sein"
ERR_BITUNIX_UID_NUMERIC_EN = "Bitunix UID must be numeric"
ERR_BINGX_UID_NUMERIC = "BingX UID muss rein numerisch sein"
ERR_BINGX_UID_NUMERIC_EN = "BingX UID must be numeric"

# ── Exchanges ────────────────────────────────────────────────────────
ERR_INVALID_EXCHANGE = "Ungültiger Exchange-Name"
ERR_INVALID_EXCHANGE_EN = "Invalid exchange name"
ERR_EXCHANGE_NOT_FOUND = "Exchange '{name}' nicht gefunden"
ERR_EXCHANGE_NOT_FOUND_EN = "Exchange '{name}' not found"
ERR_NO_CONNECTION_FOR = "Keine Verbindung für {name} konfiguriert"
ERR_NO_CONNECTION_FOR_EN = "No connection configured for {name}"
ERR_NO_API_KEY_FOR = "Kein API-Key für {name} konfiguriert"
ERR_NO_API_KEY_FOR_EN = "No API key configured for {name}"

# ── Validation ──────────────────────────────────────────────────────
ERR_INVALID_ETH_ADDRESS = "{label} muss eine gültige Ethereum-Adresse sein (0x + 40 Hex-Zeichen)"
ERR_INVALID_ETH_ADDRESS_EN = "{label} must be a valid Ethereum address (0x + 40 hex characters)"
ERR_INVALID_HEX_KEY = "{label} muss 64 Hex-Zeichen sein (mit oder ohne 0x-Prefix)"
ERR_INVALID_HEX_KEY_EN = "{label} must be 64 hex characters (with or without 0x prefix)"

# ── Strategy ────────────────────────────────────────────────────────
ERR_STRATEGY_NOT_FOUND = "Strategie nicht gefunden: {name}"
ERR_STRATEGY_NOT_FOUND_EN = "Strategy not found: {name}"

# ── Users ────────────────────────────────────────────────────────────
ERR_USERNAME_EXISTS = "Benutzername existiert bereits"
ERR_USERNAME_EXISTS_EN = "Username already exists"
ERR_USER_NOT_FOUND = "Benutzer nicht gefunden"
ERR_USER_NOT_FOUND_EN = "User not found"
ERR_CANNOT_DELETE_SELF = "Du kannst dich nicht selbst löschen"
ERR_CANNOT_DELETE_SELF_EN = "You cannot delete yourself"

# ── Trades ─────────────────────────────────────────────────────────
ERR_TRADE_NOT_FOUND = "Trade nicht gefunden"
ERR_TRADE_NOT_FOUND_EN = "Trade not found"
