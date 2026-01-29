# API-Referenz

Technische Dokumentation aller Module und Klassen des Trading Bots.

---

## Modul-Übersicht

```
src/
├── api/
│   └── bitget_client.py      # Exchange API Wrapper
├── data/
│   └── market_data.py        # Marktdaten-Fetcher
├── strategy/
│   └── liquidation_hunter.py # Trading-Strategie
├── risk/
│   └── risk_manager.py       # Risiko-Management
├── notifications/
│   └── discord_notifier.py   # Discord-Integration
├── models/
│   └── trade_database.py     # Datenbank-Layer
├── bot/
│   └── trading_bot.py        # Haupt-Orchestrierung
└── utils/
    └── logger.py             # Logging-Utilities
```

---

## BitgetClient

`src/api/bitget_client.py`

Async-Client für die Bitget Futures API.

### Initialisierung

```python
from src.api import BitgetClient

async with BitgetClient() as client:
    # Verwendet Credentials aus .env
    balance = await client.get_account_balance()
```

### Methoden

#### Account

| Methode | Beschreibung | Returns |
|---------|--------------|---------|
| `get_account_balance(margin_coin="USDT")` | Kontoguthaben abrufen | `Dict[str, Any]` |
| `get_all_positions(product_type="USDT-FUTURES")` | Alle offenen Positionen | `List[Dict]` |
| `get_position(symbol, product_type)` | Position für Symbol | `Dict[str, Any]` |

#### Market Data

| Methode | Beschreibung | Returns |
|---------|--------------|---------|
| `get_ticker(symbol)` | Aktueller Ticker | `Dict[str, Any]` |
| `get_funding_rate(symbol)` | Aktuelle Funding Rate | `Dict[str, Any]` |
| `get_candlesticks(symbol, granularity, limit)` | Kerzendaten | `List[Dict]` |
| `get_open_interest(symbol)` | Open Interest | `Dict[str, Any]` |

#### Trading

| Methode | Beschreibung | Returns |
|---------|--------------|---------|
| `set_leverage(symbol, leverage, hold_side)` | Leverage setzen | `Dict[str, Any]` |
| `place_order(...)` | Order platzieren | `Dict[str, Any]` |
| `place_market_order(symbol, side, size, tp, sl)` | Market Order | `Dict[str, Any]` |
| `close_position(symbol, hold_side, size)` | Position schließen | `Dict[str, Any]` |
| `cancel_order(symbol, order_id)` | Order stornieren | `Dict[str, Any]` |

### Beispiel

```python
async def execute_trade():
    async with BitgetClient() as client:
        # Leverage setzen
        await client.set_leverage("BTCUSDT", 3, "long")

        # Market Order platzieren
        result = await client.place_market_order(
            symbol="BTCUSDT",
            side="long",
            size="0.001",
            take_profit="98000",
            stop_loss="94000"
        )

        print(f"Order ID: {result['orderId']}")
```

---

## MarketDataFetcher

`src/data/market_data.py`

Sammelt Marktdaten von verschiedenen Quellen.

### Datenquellen

| Quelle | Daten |
|--------|-------|
| Alternative.me | Fear & Greed Index |
| Binance Futures | L/S Ratio, Funding, OI, Ticker |

### MarketMetrics Dataclass

```python
@dataclass
class MarketMetrics:
    fear_greed_index: int           # 0-100
    fear_greed_classification: str  # "Extreme Fear", "Fear", etc.
    long_short_ratio: float         # >1 = mehr Longs
    funding_rate_btc: float         # Decimal (0.0001 = 0.01%)
    funding_rate_eth: float
    btc_24h_change_percent: float
    eth_24h_change_percent: float
    btc_price: float
    eth_price: float
    btc_open_interest: float
    eth_open_interest: float
    timestamp: datetime
```

### Methoden

| Methode | Beschreibung | Returns |
|---------|--------------|---------|
| `get_fear_greed_index()` | Fear & Greed abrufen | `Tuple[int, str]` |
| `get_long_short_ratio(symbol)` | L/S Ratio | `float` |
| `get_funding_rate_binance(symbol)` | Funding Rate | `float` |
| `get_24h_ticker(symbol)` | 24h Ticker | `Dict[str, Any]` |
| `get_open_interest(symbol)` | Open Interest | `float` |
| `fetch_all_metrics()` | Alle Metriken parallel | `MarketMetrics` |

### Beispiel

```python
async def analyze_market():
    async with MarketDataFetcher() as fetcher:
        metrics = await fetcher.fetch_all_metrics()

        print(f"Fear & Greed: {metrics.fear_greed_index}")
        print(f"L/S Ratio: {metrics.long_short_ratio:.2f}")
        print(f"BTC Funding: {metrics.funding_rate_btc * 100:.4f}%")
```

---

## LiquidationHunterStrategy

`src/strategy/liquidation_hunter.py`

Implementiert die Contrarian Liquidation Hunter Strategie.

### TradeSignal Dataclass

```python
@dataclass
class TradeSignal:
    direction: SignalDirection      # LONG oder SHORT
    confidence: int                 # 0-100
    symbol: str
    entry_price: float
    target_price: float             # Take Profit
    stop_loss: float
    reason: str                     # Begründung
    metrics_snapshot: dict          # Marktdaten zum Zeitpunkt
    timestamp: datetime
```

### Methoden

| Methode | Beschreibung | Returns |
|---------|--------------|---------|
| `generate_signal(symbol)` | Signal generieren | `TradeSignal` |
| `should_trade(signal)` | Trade-Entscheidung | `Tuple[bool, str]` |
| `get_position_size_recommendation(signal, balance)` | Position Size | `float` |

### Signal-Generierung

```python
async def get_signal():
    strategy = LiquidationHunterStrategy()

    signal = await strategy.generate_signal("BTCUSDT")

    print(f"Direction: {signal.direction.value}")
    print(f"Confidence: {signal.confidence}%")
    print(f"Reason: {signal.reason}")

    should_trade, reason = await strategy.should_trade(signal)
    if should_trade:
        print("Signal approved for trading")
```

---

## RiskManager

`src/risk/risk_manager.py`

Verwaltet Risiko-Limits und Trade-Tracking.

### DailyStats Dataclass

```python
@dataclass
class DailyStats:
    date: str
    starting_balance: float
    current_balance: float
    trades_executed: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    total_fees: float
    total_funding: float
    max_drawdown: float
    is_trading_halted: bool
    halt_reason: str
```

### Methoden

| Methode | Beschreibung | Returns |
|---------|--------------|---------|
| `initialize_day(balance)` | Tag initialisieren | `DailyStats` |
| `can_trade()` | Darf getradet werden? | `Tuple[bool, str]` |
| `calculate_position_size(balance, price, confidence, leverage)` | Position berechnen | `Tuple[float, float]` |
| `record_trade_entry(...)` | Trade-Einstieg loggen | `bool` |
| `record_trade_exit(...)` | Trade-Ausstieg loggen | `bool` |
| `get_remaining_trades()` | Verbleibende Trades | `int` |
| `get_remaining_risk_budget()` | Verbleibendes Risiko | `float` |

### Beispiel

```python
risk_manager = RiskManager()

# Tag starten
risk_manager.initialize_day(starting_balance=10000.0)

# Prüfen ob Trading erlaubt
can_trade, reason = risk_manager.can_trade()
if not can_trade:
    print(f"Trading blocked: {reason}")

# Position Size berechnen
usdt_size, base_size = risk_manager.calculate_position_size(
    balance=10000,
    entry_price=95000,
    confidence=85,
    leverage=3
)
```

---

## DiscordNotifier

`src/notifications/discord_notifier.py`

Sendet formatierte Benachrichtigungen an Discord.

### Methoden

| Methode | Beschreibung |
|---------|--------------|
| `send_trade_entry(...)` | Trade-Einstieg melden |
| `send_trade_exit(...)` | Trade-Ausstieg mit PnL |
| `send_daily_summary(...)` | Tägliche Zusammenfassung |
| `send_risk_alert(...)` | Risiko-Warnung |
| `send_signal_alert(...)` | Signal-Benachrichtigung |
| `send_error(...)` | Fehlermeldung |
| `send_bot_status(...)` | Status-Update |

### Beispiel

```python
async def notify():
    async with DiscordNotifier() as discord:
        await discord.send_trade_entry(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000,
            leverage=3,
            take_profit=98325,
            stop_loss=93100,
            confidence=85,
            reason="Crowded Shorts + Extreme Fear",
            order_id="123456789"
        )
```

---

## TradeDatabase

`src/models/trade_database.py`

SQLite-basierte Persistenz für Trades.

### Trade Dataclass

```python
@dataclass
class Trade:
    id: Optional[int]
    symbol: str
    side: str                    # "long" oder "short"
    size: float
    entry_price: float
    exit_price: Optional[float]
    take_profit: float
    stop_loss: float
    leverage: int
    confidence: int
    reason: str
    order_id: str
    close_order_id: Optional[str]
    status: TradeStatus          # OPEN, CLOSED, CANCELLED
    pnl: Optional[float]
    pnl_percent: Optional[float]
    fees: float
    funding_paid: float
    entry_time: datetime
    exit_time: Optional[datetime]
    exit_reason: Optional[str]
```

### Methoden

| Methode | Beschreibung | Returns |
|---------|--------------|---------|
| `create_trade(...)` | Trade erstellen | `int` (Trade ID) |
| `close_trade(trade_id, ...)` | Trade schließen | `bool` |
| `get_trade(trade_id)` | Trade abrufen | `Optional[Trade]` |
| `get_open_trades(symbol=None)` | Offene Trades | `List[Trade]` |
| `get_recent_trades(limit)` | Letzte Trades | `List[Trade]` |
| `get_statistics(days)` | Statistiken | `Dict` |
| `count_trades_today()` | Trades heute | `int` |

---

## TradingBot

`src/bot/trading_bot.py`

Haupt-Orchestrierung aller Komponenten.

### Methoden

| Methode | Beschreibung |
|---------|--------------|
| `initialize()` | Alle Komponenten initialisieren |
| `start()` | Bot starten |
| `stop()` | Bot stoppen |
| `analyze_and_trade()` | Markt analysieren & traden |
| `monitor_positions()` | Offene Positionen überwachen |
| `send_daily_summary()` | Tägliche Zusammenfassung |
| `close_all_positions()` | Notfall: Alle Positionen schließen |
| `run_once()` | Einmalige Analyse (für Tests) |

### Beispiel

```python
import asyncio
from src.bot import TradingBot

async def main():
    bot = TradingBot()

    # Nur initialisieren und einmal analysieren
    await bot.initialize()
    signals = await bot.run_once()

    for signal in signals:
        print(signal.to_dict())

    await bot.stop()

asyncio.run(main())
```

---

## Konfiguration

`config/settings.py`

Alle Einstellungen werden aus Environment-Variablen geladen.

### Settings Klasse

```python
from config import settings

# Zugriff auf Einstellungen
print(settings.trading.leverage)
print(settings.strategy.fear_greed_extreme_fear)
print(settings.discord.webhook_url)
```

### Konfigurationsgruppen

| Gruppe | Attribute |
|--------|-----------|
| `settings.bitget` | api_key, api_secret, passphrase, testnet |
| `settings.discord` | bot_token, channel_id, webhook_url |
| `settings.trading` | max_trades_per_day, daily_loss_limit_percent, position_size_percent, leverage, take_profit_percent, stop_loss_percent, trading_pairs |
| `settings.strategy` | fear_greed_extreme_fear, fear_greed_extreme_greed, long_short_crowded_longs, long_short_crowded_shorts, funding_rate_high, funding_rate_low, high_confidence_min, low_confidence_min |
| `settings.logging` | level, file |
