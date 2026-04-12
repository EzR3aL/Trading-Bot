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
ERR_POSITION_CLOSE_FAILED = "Position {symbol} konnte auf der Exchange nicht geschlossen werden. Bitte manuell auf der Exchange schließen."
ERR_POSITION_CLOSE_FAILED_EN = "Position {symbol} could not be closed on the exchange. Please close manually."
ERR_POSITION_VERIFY_FAILED = "Position {symbol}: Status konnte nach dem Schließen nicht verifiziert werden. Bitte auf der Exchange prüfen."
ERR_POSITION_VERIFY_FAILED_EN = "Position {symbol}: Status could not be verified after closing. Please check on the exchange."
ERR_TELEGRAM_NOT_CONFIGURED = "Telegram nicht konfiguriert"
ERR_TELEGRAM_NOT_CONFIGURED_EN = "Telegram not configured"
ERR_TELEGRAM_SEND_FAILED = "Telegram-Nachricht konnte nicht gesendet werden"
ERR_TELEGRAM_SEND_FAILED_EN = "Failed to send Telegram message"
ERR_DISCORD_NOT_CONFIGURED = "Discord-Webhook ist nicht konfiguriert"
ERR_DISCORD_NOT_CONFIGURED_EN = "Discord webhook is not configured"
ERR_DISCORD_SEND_FAILED = "Discord-Nachricht konnte nicht gesendet werden"
ERR_DISCORD_SEND_FAILED_EN = "Failed to send Discord message"
ERR_STOP_BOT_BEFORE_EDIT = "Stoppe den Bot bevor du die Konfiguration bearbeitest"
ERR_STOP_BOT_BEFORE_EDIT_EN = "Stop the bot before editing its configuration"
ERR_MAX_BOTS_REACHED = "Maximal {max_bots} Bots pro Benutzer erlaubt"
ERR_MAX_BOTS_REACHED_EN = "Maximum {max_bots} bots per user allowed"
ERR_ORCHESTRATOR_NOT_INITIALIZED = "Bot-Orchestrator nicht initialisiert"
ERR_ORCHESTRATOR_NOT_INITIALIZED_EN = "Bot orchestrator not initialized"
ERR_PENDING_TRADE_NOT_FOUND = "Ausstehender Trade nicht gefunden"
ERR_PENDING_TRADE_NOT_FOUND_EN = "Pending trade not found"
ERR_TRADE_ALREADY_RESOLVED = "Trade ist bereits abgeschlossen"
ERR_TRADE_ALREADY_RESOLVED_EN = "Trade is already resolved"

# ── Bots / Affiliate Gate ────────────────────────────────────────────
ERR_AFFILIATE_REQUIRED = "Bot kann nicht gestartet werden: Du musst dich zuerst über unseren Affiliate-Link bei {exchange} registrieren und deine UID unter Einstellungen → API Keys hinterlegen."
ERR_AFFILIATE_REQUIRED_EN = "Cannot start bot: Please register via our affiliate link at {exchange} first and enter your UID under Settings → API Keys."
ERR_AFFILIATE_PENDING = "Bot kann nicht gestartet werden: Deine {exchange}-UID wurde eingereicht, ist aber noch nicht freigegeben. Bitte warte auf die Freigabe durch einen Admin."
ERR_AFFILIATE_PENDING_EN = "Cannot start bot: Your {exchange} UID has been submitted but is not yet approved. Please wait for admin approval."

# ── Bots / Hyperliquid Gate ──────────────────────────────────────────
ERR_NO_HL_CONNECTION = "Bot kann nicht gestartet werden: Du hast noch keine Hyperliquid-Wallet verbunden. Gehe zu Einstellungen → API Keys → Hyperliquid und verbinde deine Wallet."
ERR_NO_HL_CONNECTION_EN = "Cannot start bot: No Hyperliquid wallet connected. Go to Settings → API Keys → Hyperliquid and connect your wallet."
ERR_HL_REFERRAL_REQUIRED = "Bot kann nicht gestartet werden: Registriere dich zuerst über unseren Referral-Link https://app.hyperliquid.xyz/join/{referral_code} und verbinde dann deine Wallet unter Einstellungen → API Keys."
ERR_HL_REFERRAL_REQUIRED_EN = "Cannot start bot: Please register via our referral link https://app.hyperliquid.xyz/join/{referral_code} first, then connect your wallet under Settings → API Keys."
ERR_HL_BUILDER_FEE_NOT_APPROVED = "Bot kann nicht gestartet werden: Die Builder Fee wurde noch nicht genehmigt. Gehe zu Einstellungen → API Keys → Hyperliquid und genehmige die Builder Fee."
ERR_HL_BUILDER_FEE_NOT_APPROVED_EN = "Cannot start bot: Builder fee not yet approved. Go to Settings → API Keys → Hyperliquid and approve the builder fee."

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

# ── Config / Hyperliquid Admin ───────────────────────────────────────
ERR_INVALID_BUILDER_ADDRESS = "Builder-Adresse muss eine gültige Ethereum-Adresse sein (0x + 40 Hex-Zeichen)"
ERR_INVALID_BUILDER_ADDRESS_EN = "Builder address must be a valid Ethereum address (0x + 40 hex characters)"
ERR_INVALID_REFERRAL_CODE = "Referral-Code muss alphanumerisch sein (max. 50 Zeichen)"
ERR_INVALID_REFERRAL_CODE_EN = "Referral code must be alphanumeric (max 50 characters)"
ERR_NO_DEMO_API_KEYS_HL = "Keine Demo-API-Keys für Hyperliquid"
ERR_NO_DEMO_API_KEYS_HL_EN = "No demo API keys for Hyperliquid"
ERR_NO_LIVE_API_KEYS_HL = "Keine Live-API-Keys für Hyperliquid"
ERR_NO_LIVE_API_KEYS_HL_EN = "No live API keys for Hyperliquid"
ERR_DUPLICATE_LIVE_DEMO_KEY = (
    "Dieser API-Key ist bereits als Demo-Key gespeichert. "
    "Wenn der Key nur für Demo-Trading gilt, lass das Live-Feld leer. "
    "Bei Bitget und BingX nutzen wir den Demo-Key automatisch über einen "
    "speziellen Header für das Live-Dashboard — du musst nichts ins Live-Feld eintragen."
)
ERR_DUPLICATE_LIVE_DEMO_KEY_EN = (
    "This API key is already stored as a demo key. "
    "If the key is for demo trading only, leave the live field empty. "
    "For Bitget and BingX we automatically use the demo key for the simulated "
    "environment via a header — no need to populate the live field."
)
ERR_DUPLICATE_DEMO_LIVE_KEY = (
    "Dieser API-Key ist bereits als Live-Key gespeichert. "
    "Wenn der Key sowohl für Live als auch für Demo gilt, lass das Demo-Feld leer "
    "(wir nutzen den Live-Key automatisch für beide Modi). "
    "Wenn es ein eigenständiger Demo-Key ist, lösche zuerst die Live-Keys."
)
ERR_DUPLICATE_DEMO_LIVE_KEY_EN = (
    "This API key is already stored as a live key. "
    "If the key works for both live and demo, leave the demo field empty "
    "(we automatically use the live key for both modes). "
    "If it's a separate demo key, please delete the live keys first."
)
ERR_WRONG_ENVIRONMENT = (
    "Falscher API-Key-Typ: Du hast vermutlich einen {other_mode}-Key im {mode}-Feld eingetragen. "
    "{exchange} unterscheidet zwischen Live- und Demo-Keys. "
    "Bitte trage den Key im richtigen Feld ein ({other_mode})."
)
ERR_WRONG_ENVIRONMENT_EN = (
    "These {mode} API keys do not authenticate against the {mode} environment "
    "of {exchange}. If this is a {other_mode} key, please save it in the "
    "{other_mode} field instead. Original error: {detail}"
)
ERR_NO_HL_CONNECTION_PLAIN = "Keine Hyperliquid-Verbindung konfiguriert"
ERR_NO_HL_CONNECTION_PLAIN_EN = "No Hyperliquid connection configured"
ERR_BUILDER_FEE_NOT_FOUND = "Builder-Fee-Genehmigung nicht auf Hyperliquid gefunden. Bitte erneut signieren."
ERR_BUILDER_FEE_NOT_FOUND_EN = "Builder fee approval not found on Hyperliquid. Please sign again."
ERR_REFERRAL_NOT_FOUND = "Referral nicht gefunden. Bitte registriere dich zuerst über https://app.hyperliquid.xyz/join/{referral_code}"
ERR_REFERRAL_NOT_FOUND_EN = "Referral not found. Please register first via https://app.hyperliquid.xyz/join/{referral_code}"
ERR_REFERRAL_CHECK_FAILED = "Referral-Prüfung fehlgeschlagen. Siehe Server-Logs."
ERR_REFERRAL_CHECK_FAILED_EN = "Referral check failed. See server logs."
ERR_REFERRAL_DEPOSIT_NEEDED = (
    "Dein Wallet {wallet_short} hat noch kein Guthaben auf Hyperliquid. "
    "Zahle mindestens 5 USDC via Arbitrum Bridge ein "
    "(https://app.hyperliquid.xyz/deposit), dann wird der Referrer {referral_code} "
    "automatisch gebunden. Wichtig: Weniger als 5 USDC gehen verloren."
)
ERR_REFERRAL_DEPOSIT_NEEDED_EN = (
    "Your wallet {wallet_short} has no balance on Hyperliquid yet. "
    "Deposit at least 5 USDC via the Arbitrum bridge "
    "(https://app.hyperliquid.xyz/deposit), the {referral_code} referrer will "
    "be bound automatically. Warning: Deposits below 5 USDC will be lost."
)
ERR_REFERRAL_ENTER_CODE_NEEDED = (
    "Dein Wallet {wallet_short} existiert auf Hyperliquid (Balance ${account_value:.2f}) "
    "aber ohne Referrer. Öffne https://app.hyperliquid.xyz/referrals, klicke 'Enter Code' "
    "und trage {referral_code} ein. Danach hier erneut prüfen."
)
ERR_REFERRAL_ENTER_CODE_NEEDED_EN = (
    "Your wallet {wallet_short} exists on Hyperliquid (balance ${account_value:.2f}) "
    "but has no referrer set. Open https://app.hyperliquid.xyz/referrals, click 'Enter Code' "
    "and enter {referral_code}. Then re-check here."
)
ERR_REFERRAL_WRONG_CODE = (
    "Dein Wallet {wallet_short} wurde über einen anderen Referrer registriert "
    "(gefunden: {found_code}, erwartet: {referral_code}). Referrer-Änderungen sind "
    "auf Hyperliquid nicht möglich — bitte neues Wallet mit unserem Link verwenden."
)
ERR_REFERRAL_WRONG_CODE_EN = (
    "Your wallet {wallet_short} was registered via a different referrer "
    "(found: {found_code}, expected: {referral_code}). Hyperliquid does not "
    "allow changing the referrer — please use a new wallet with our link."
)
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
ERR_TP_SL_CONFLICT_TP = "TP und Entfernen von TP kann nicht gleichzeitig gesetzt werden"
ERR_TP_SL_CONFLICT_TP_EN = "Cannot set take_profit and remove_tp simultaneously"
ERR_TP_SL_CONFLICT_SL = "SL und Entfernen von SL kann nicht gleichzeitig gesetzt werden"
ERR_TP_SL_CONFLICT_SL_EN = "Cannot set stop_loss and remove_sl simultaneously"
ERR_TP_POSITIVE = "TP muss ein positiver Wert sein"
ERR_TP_POSITIVE_EN = "TP must be a positive value"
ERR_TP_ABOVE_ENTRY_LONG = "TP muss über dem Einstiegspreis liegen (Long)"
ERR_TP_ABOVE_ENTRY_LONG_EN = "TP must be above entry price for long"
ERR_TP_BELOW_ENTRY_SHORT = "TP muss unter dem Einstiegspreis liegen (Short)"
ERR_TP_BELOW_ENTRY_SHORT_EN = "TP must be below entry price for short"
ERR_SL_POSITIVE = "SL muss ein positiver Wert sein"
ERR_SL_POSITIVE_EN = "SL must be a positive value"
ERR_SL_BELOW_ENTRY_LONG = "SL muss unter dem Einstiegspreis liegen (Long)"
ERR_SL_BELOW_ENTRY_LONG_EN = "SL must be below entry price for long"
ERR_SL_ABOVE_ENTRY_SHORT = "SL muss über dem Einstiegspreis liegen (Short)"
ERR_SL_ABOVE_ENTRY_SHORT_EN = "SL must be above entry price for short"
ERR_TPSL_EXCHANGE_NOT_SUPPORTED = "Exchange {exchange} unterstützt keine TP/SL-Änderung"
ERR_TPSL_EXCHANGE_NOT_SUPPORTED_EN = "Exchange {exchange} does not support TP/SL modification"
ERR_TPSL_UPDATE_FAILED = "TP/SL konnte auf der Exchange nicht aktualisiert werden. Bitte erneut versuchen."
ERR_TPSL_UPDATE_FAILED_EN = "Failed to update TP/SL on exchange. Please try again."

# ── Exchange API Error Translation ──────────────────────────────────
# Maps common English exchange API error substrings to German translations.
# Used by translate_exchange_error() to provide user-friendly German messages.
_EXCHANGE_ERROR_TRANSLATIONS: list[tuple[str, str]] = [
    # Bitget TP/SL errors
    ("the take profit price of the long position should be greater than the current price",
     "Der Take-Profit-Preis der Long-Position muss über dem aktuellen Preis liegen"),
    ("the stop loss price of the long position should be less than the current price",
     "Der Stop-Loss-Preis der Long-Position muss unter dem aktuellen Preis liegen"),
    ("the take profit price of the short position should be less than the current price",
     "Der Take-Profit-Preis der Short-Position muss unter dem aktuellen Preis liegen"),
    ("the stop loss price of the short position should be greater than the current price",
     "Der Stop-Loss-Preis der Short-Position muss über dem aktuellen Preis liegen"),
    ("the take profit price should be greater than the entry price",
     "Der Take-Profit-Preis muss über dem Einstiegspreis liegen"),
    ("the stop loss price should be less than the entry price",
     "Der Stop-Loss-Preis muss unter dem Einstiegspreis liegen"),
    ("the take profit price should be less than the entry price",
     "Der Take-Profit-Preis muss unter dem Einstiegspreis liegen"),
    ("the stop loss price should be greater than the entry price",
     "Der Stop-Loss-Preis muss über dem Einstiegspreis liegen"),
    # Balance / funds
    ("insufficient balance", "Unzureichendes Guthaben"),
    ("insufficient margin", "Unzureichende Margin"),
    ("insufficient available margin", "Unzureichende verfügbare Margin"),
    ("balance not enough", "Guthaben nicht ausreichend"),
    ("not enough balance", "Guthaben nicht ausreichend"),
    ("available balance is not enough", "Verfügbares Guthaben ist nicht ausreichend"),
    # Order errors
    ("order does not exist", "Order existiert nicht"),
    ("order not found", "Order nicht gefunden"),
    ("order has been filled", "Order wurde bereits ausgeführt"),
    ("order has been cancelled", "Order wurde bereits storniert"),
    ("order amount is too small", "Orderbetrag ist zu gering"),
    ("the order price is not within the price limit range",
     "Der Orderpreis liegt außerhalb des erlaubten Preisbereichs"),
    ("order price is not within the limit", "Orderpreis liegt außerhalb des Limits"),
    # Position errors
    ("position does not exist", "Position existiert nicht"),
    ("position not found", "Position nicht gefunden"),
    ("no position", "Keine Position vorhanden"),
    ("close amount exceeds the available amount", "Schließbetrag übersteigt den verfügbaren Betrag"),
    # Leverage
    ("leverage is too high", "Hebel ist zu hoch"),
    ("leverage exceeds maximum", "Hebel überschreitet das Maximum"),
    ("the leverage ratio is not in the allowable range", "Der Hebel liegt nicht im erlaubten Bereich"),
    # Market / trading
    ("market is closed", "Markt ist geschlossen"),
    ("trading is not allowed", "Handel ist nicht erlaubt"),
    ("symbol not found", "Handelspaar nicht gefunden"),
    ("symbol does not exist", "Handelspaar existiert nicht"),
    ("the symbol is not available for trading", "Das Handelspaar ist nicht für den Handel verfügbar"),
    ("minimum order amount", "Mindestorderbetrag nicht erreicht"),
    ("minimum order quantity", "Mindestordermenge nicht erreicht"),
    ("the quantity of the order is less than the minimum", "Die Ordermenge ist unter dem Minimum"),
    # Rate limiting
    ("too many requests", "Zu viele Anfragen — bitte kurz warten"),
    ("rate limit exceeded", "Anfragelimit überschritten — bitte kurz warten"),
    # API key / auth
    ("exchange environment is incorrect",
     "Falsche Umgebung — du hast vermutlich einen Live-Key im Demo-Feld (oder umgekehrt) eingetragen. "
     "Prüfe, ob der Key zur gewählten Umgebung passt."),
    ("invalid api key", "Ungültiger API-Key — prüfe ob der Key korrekt kopiert wurde"),
    ("api key expired", "API-Key abgelaufen — erstelle einen neuen Key in der Exchange"),
    ("signature error", "Signatur-Fehler — prüfe API-Secret"),
    ("invalid signature", "Ungültige Signatur — prüfe API-Secret und Passphrase"),
    ("ip not in whitelist",
     "IP-Adresse nicht in der Whitelist — füge die Server-IP in deinen Exchange-API-Einstellungen hinzu"),
    ("permission denied", "Berechtigung verweigert — prüfe API-Key-Berechtigungen"),
    ("api key does not have permission",
     "API-Key hat keine Berechtigung für diese Aktion — aktiviere Futures/Trading-Berechtigung"),
    # Network / timeout
    ("timeout", "Zeitüberschreitung — bitte erneut versuchen"),
    ("connection refused", "Verbindung abgelehnt"),
    ("service unavailable", "Exchange vorübergehend nicht verfügbar"),
    # Hyperliquid specific
    ("order rejected", "Order abgelehnt"),
    ("user or api wallet does not exist", "Wallet existiert nicht auf Hyperliquid"),
    ("not enough margin to place order", "Nicht genug Margin für diese Order"),
    # BingX specific
    ("the contract does not exist", "Der Kontrakt existiert nicht"),
    # Generic
    ("unknown error", "Unbekannter Fehler"),
]


def translate_exchange_error(error_msg: str) -> str:
    """Translate common English exchange API error messages to German.

    Performs case-insensitive substring matching against known error patterns.
    Returns the German translation if a match is found, otherwise returns the
    original message unchanged.
    """
    lower = error_msg.lower()
    for english_pattern, german_translation in _EXCHANGE_ERROR_TRANSLATIONS:
        if english_pattern in lower:
            return german_translation
    return error_msg
