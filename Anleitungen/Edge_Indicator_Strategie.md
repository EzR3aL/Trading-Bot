# Edge Indicator Strategie - Vollstandige Anleitung

---

# DEUTSCH

## 1. Ubersicht

Die **Edge Indicator Strategie** basiert auf dem TradingView "Trading Edge" Indikator. Sie kombiniert drei Analyse-Ebenen, um Handelssignale zu generieren:

1. **EMA-Ribbon (8/21)** - Erkennt die Trendrichtung
2. **ADX Chop-Filter** - Filtert Seitwartsphasen heraus
3. **Predator Momentum Score** - Bestatigt den Trend und bestimmt das Timing

**Datenquelle:** Ausschliesslich Binance OHLCV-Kerzen (Klines). Unabhangig davon, auf welcher Exchange gehandelt wird, kommen die Analysedaten immer von Binance - das garantiert konsistente Daten.

---

## 2. Risikoprofile

Die Strategie bietet zwei vorkonfigurierte Risikoprofile:

### Standard-Profil (1h-Kerzen)
- Haufigere Signale, schnellere Reaktion
- ADX-Schwelle: 18 (lockerer Filter)
- Momentum-Schwelle: +/-0.35
- Trailing-Stop-Abstand: 2.5x ATR
- Breakeven-Schwelle: 1.5x ATR
- **Geeignet fur:** Aktive Trader, die mehr Handelsmoglichkeiten wollen

### Konservatives Profil (4h-Kerzen)
- Weniger, aber starkere Signale
- ADX-Schwelle: 22 (strengerer Filter)
- Momentum-Schwelle: +/-0.40 (hohere Hurde)
- Trailing-Stop-Abstand: 3.0x ATR (breiterer Schutz)
- Breakeven-Schwelle: 2.0x ATR
- Momentum-Glattung: 7 statt 5 (weniger Rauschen)
- **Geeignet fur:** Risikoaverse Trader, die Qualitat uber Quantitat stellen

---

## 3. Wie ein Signal entsteht

### Schritt 1: EMA-Ribbon (Trendrichtung)

Zwei exponentielle gleitende Durchschnitte (EMA 8 und EMA 21) bilden ein "Band":

| Situation | Bedeutung |
|-----------|-----------|
| Preis uber beiden EMAs | **Bullischer Trend** (Aufwartstrend) |
| Preis unter beiden EMAs | **Barischer Trend** (Abwartstrend) |
| Preis zwischen den EMAs | **Neutral** (kein klares Signal) |

### Schritt 2: ADX Chop-Filter (Marktqualitat)

Der ADX (Average Directional Index) misst die **Starke** eines Trends - nicht die Richtung:

- **ADX uber Schwelle** (Standard: 18, Konservativ: 22) = Der Markt **trendet** - Handel erlaubt
- **ADX unter Schwelle** = Der Markt ist **seitwarts/choppig** - kein Handel

Dieser Filter verhindert, dass der Bot in richtungslosen Markten handelt und dort Verluste ansammelt.

### Schritt 3: Predator Momentum Score (Bestatigung)

Der Momentum-Score kombiniert drei Komponenten zu einer Zahl zwischen -1 und +1:

1. **MACD-Normalisierung:** MACD-Histogramm wird per tanh-Funktion normalisiert
2. **RSI-Drift:** Veranderungsrate des geglatten RSI
3. **Trend-Bonus:** +0.6 wenn EMA8 > EMA21 (bullisch), -0.6 wenn EMA8 < EMA21 (barisch)

**Formel:** `Score = tanh(MACD/stdev) + tanh(RSI_drift/2) + Trend_Bonus` (begrenzt auf -1 bis +1)

Der Score wird zusatzlich mit einem EMA geglattet, um kurzfristige Schwankungen zu dampfen.

**Regime-Erkennung:**
- Score > Schwelle = **Bullisches Regime** (Long-Signale bevorzugt)
- Score < -Schwelle = **Barisches Regime** (Short-Signale bevorzugt)
- Dazwischen = **Neutrales Regime** (kein Signal)

### Schritt 4: Signalbestimmung

Ein Handelssignal wird nur generiert, wenn mehrere Bedingungen gleichzeitig erfullt sind:

**LONG-Signal:**
- Bullischer Trend (Preis uber beiden EMAs) UND Markt trendet UND Momentum neutral oder bullisch
- ODER: Markt trendet UND bullisches Regime UND kein barischer Trend

**SHORT-Signal:**
- Barischer Trend (Preis unter beiden EMAs) UND Markt trendet UND Momentum neutral oder barisch
- ODER: Markt trendet UND barisches Regime UND kein bullischer Trend

---

## 4. Konfidenz-Bewertung

Jedes Signal bekommt einen Konfidenz-Wert (0-95%), der bestimmt, **wie sicher** sich die Strategie ist:

| Komponente | Punkte | Bedingung |
|------------|--------|-----------|
| Basis | 50 | Immer |
| ADX-Starke | 0-25 | Je hoher der ADX uber der Schwelle, desto mehr Punkte |
| Momentum-Starke | 0-20 | Score > 0.5: +20, > 0.3: +12, > 0.15: +5 |
| Volle Ubereinstimmung | +10 | Trend + Momentum + ADX zeigen alle in dieselbe Richtung |
| Regime-Wechsel | +10 | Momentum hat gerade die Seite gewechselt (frisches Signal) |

**Mindest-Konfidenz:** Standardmassig muss ein Signal mindestens **65% Konfidenz** erreichen, um einen Trade auszulosen. Dieser Wert ist konfigurierbar (10-90%).

**Auswirkung auf die Positionsgrosse:**

| Konfidenz | Multiplikator |
|-----------|--------------|
| ab 85% | 1.5x der Basisgrosse |
| ab 75% | 1.25x |
| ab 65% | 1.0x (Standard) |
| ab 55% | 0.75x |
| unter 55% | 0.5x |

---

## 5. Positionsgrosse und Risiko

### Berechnung der Positionsgrosse

1. **Basis:** Konfigurierter Prozentsatz des Kontostands (z.B. 10%)
2. **Skalierung:** Multipliziert mit dem Konfidenz-Faktor (siehe oben)
3. **Maximum:** Maximal 25% des Kontostands pro Trade
4. **Minimum:** Mindestens 5 USDT Ordervolumen
5. **Hebel:** Wird auf die Position angewendet (z.B. 5x Hebel = 5-facher Positionswert)

**Beispiel:**
- Kontostand: 10.000 USDT
- Basisgrosse: 10% = 1.000 USDT
- Konfidenz 80% -> Multiplikator 1.25x -> 1.250 USDT
- Hebel 5x -> Positionswert am Markt: 6.250 USDT

### Tagliches Verlustlimit

Wenn konfiguriert (z.B. 5%), stoppt der Bot den Handel fur den restlichen Tag, sobald die taglichen Verluste diese Schwelle erreichen.

**Gewinn-Absicherung (Profit Lock-In):**
Wenn aktiviert und der Tag im Plus ist, wird das Verlustlimit dynamisch angepasst, um einen Teil der Gewinne zu sichern. Beispiel: Bei 3% Tagesgewinn und 75% Lock-In wird nur noch 0.75% Ruckgang toleriert.

### Pro-Symbol-Konfiguration

Jedes Handelspaar kann individuell konfiguriert werden:
- Eigener Hebel
- Eigene Positionsgrosse (% oder absolut in USDT)
- Eigenes Verlustlimit
- Maximale Trades pro Tag

---

## 6. Trailing Stop - Zweistufiger Schutzmechanismus

Der Trailing Stop ist das wichtigste Werkzeug zur Gewinnabsicherung. Die Strategie nutzt ein **zweistufiges System**:

### Stufe 1: Nativer Exchange-Trailing-Stop

- Wird beim Ordereingang direkt an die Exchange ubermittelt
- Die Exchange uberwacht und fuhrt den Stop eigenstandig aus
- Kein Eingriff des Bots notig - funktioniert auch wenn der Bot offline ist

**Parameter:**
- **Aktivierungspreis (Trigger):** Der Preis muss zuerst um `ATR x Breakeven-Faktor` in die Gewinnzone laufen, bevor der Trailing Stop aktiv wird
  - Standard: 1.5x ATR uber Einstieg
  - Konservativ: 2.0x ATR uber Einstieg
- **Nachlauf-Abstand (Callback):** Der maximale Ruckgang vom Hochstpunkt, bei dem geschlossen wird
  - Standard: 2.5x ATR
  - Konservativ: 3.0x ATR

**Beispiel (BTCUSDT, ATR = 800 USDT):**
- Einstieg: 50.000 USDT (Long)
- Aktivierung: 50.000 + (800 x 1.5) = **51.200 USDT** - erst ab hier greift der Trailing Stop
- Nachlauf-Abstand: 800 x 2.5 = **2.000 USDT** - wird vom Hochstpunkt abgezogen
- Preis steigt auf 53.000 -> Trailing Stop bei 53.000 - 2.000 = **51.000 USDT**
- Preis fallt auf 51.000 -> **Position wird geschlossen mit +1.000 USDT Gewinn**

### Stufe 2: Software-Trailing-Stop (Backup)

Falls der native Trailing Stop nicht gesetzt werden konnte oder die Exchange ihn nicht unterstutzt:

- Der Bot pruft **jede Minute** den aktuellen Preis
- Verfolgt den Hochstpreis seit Einstieg
- Berechnet den Stop-Level identisch zum nativen Trailing Stop
- Zusatzlich: **Breakeven-Boden** - der Trailing Stop fallt nie unter den Einstiegspreis

### Wann wird der Trailing Stop NICHT aktiv?

- Wenn `trailing_stop_enabled = false` in der Konfiguration
- Wenn der Preis noch nicht den Aktivierungspreis (Breakeven-Schwelle) erreicht hat
- In diesem Fall greifen nur die konfigurierten Take-Profit/Stop-Loss-Level

---

## 7. Strategie-Exit (Indikator-basiert)

Unabhangig vom Trailing Stop kann die Strategie einen Exit signalisieren, wenn sich die Marktbedingungen andern. Die Strategie pruft **jede Minute** folgende Bedingungen:

### Exit fur LONG-Positionen

| Bedingung | Beschreibung |
|-----------|-------------|
| **Trend-Umkehr** | Preis fallt unter beide EMAs (barischer Trend) |
| **Trend-Abschwachung** | Preis fallt in das EMA-Ribbon UND Momentum wird barisch |
| **Regime-Wechsel** | Momentum wechselt von bullisch zu barisch |

### Exit fur SHORT-Positionen

| Bedingung | Beschreibung |
|-----------|-------------|
| **Trend-Umkehr** | Preis steigt uber beide EMAs (bullischer Trend) |
| **Trend-Abschwachung** | Preis steigt in das EMA-Ribbon UND Momentum wird bullisch |
| **Regime-Wechsel** | Momentum wechselt von barisch zu bullisch |

### Wichtig: Wann wird der Strategie-Exit NICHT gepruft?

Wenn Take-Profit ODER Stop-Loss auf der Exchange gesetzt sind UND der Trailing Stop deaktiviert ist, uberspringt der Bot den Strategie-Exit. Die Exchange-Orders haben Vorrang, da sie schneller reagieren.

---

## 8. Bot-Ablauf im Detail

### Initialisierung (beim Start)

1. Konfiguration aus der Datenbank laden
2. Exchange-Verbindung herstellen (API-Schlüssel)
3. Separate Clients fur Demo/Live erstellen
4. Strategie mit Parametern initialisieren
5. Risikomanager aufsetzen
6. Bei Hyperliquid: Builder-Fee und Referral-Genehmigung prufen
7. Handelspaare auf der Exchange validieren
8. Kontostand abfragen, tagliche Session starten

### Hauptschleife

Der Bot fuhrt drei periodische Aufgaben aus:

| Aufgabe | Frequenz | Zweck |
|---------|----------|-------|
| **Analyse & Trade** | Konfigurierbar (z.B. alle 60 Min.) | Signal generieren, Trades ausfuhren |
| **Position uberwachen** | Jede Minute | Trailing Stop, Exit-Prufung, Glitch-Erkennung |
| **Tageszusammenfassung** | 23:55 UTC | Performance-Bericht senden |

### Sicherheitsmechanismen

- **Per-Symbol-Lock:** Verhindert doppelte Positionen fur dasselbe Paar
- **Per-User-Lock:** Nur ein Bot pro Benutzer kann gleichzeitig einen Trade ausfuhren
- **Cooldown:** Nach Schliessen eines Trades wird 4 Stunden gewartet (konfigurierbar)
- **Signal-Deduplizierung:** Identische Signale innerhalb von 60 Sekunden werden ignoriert
- **Fehlertoleranz:** Nach 5 aufeinanderfolgenden Fehlern pausiert der Bot 60 Sekunden

---

## 9. Exchange-Besonderheiten

### Exchange-Support-Matrix

| Feature | Bitget | BingX | Weex | Hyperliquid | Bitunix |
|---------|--------|-------|------|-------------|---------|
| **TP/SL setzen** | Nativ (Position-Level) | Nativ (Conditional Orders) | Nativ (Trigger Orders) | Nativ (positionTpsl) | Nativ (Position-Level) |
| **TP/SL andern** | Ersetzt automatisch | Place + Cancel alte | Place + Cancel alte | Ersetzt automatisch | Ersetzt automatisch |
| **TP/SL entfernen** | Cancel Plan-Orders | Cancel Conditional | Cancel Trigger | Empty positionTpsl | Cancel Pending |
| **Trailing Stop** | **Nativ** (moving_plan) | **Nativ** (TRAILING_STOP_MARKET) | Software (Bot-uberwacht) | Software (Bot-uberwacht) | Software (Bot-uberwacht) |
| **Demo-Modus** | Testnet-API | VST-API | Paper-Trading Header | Testnet | Testnet |
| **Margin-Modi** | Cross + Isolated | Cross + Isolated | Cross + Isolated | Cross + Isolated | Cross + Isolated |

**Legende:**
- **Nativ** = Exchange fuhrt den Stop eigenstandig aus (auch bei Bot-Ausfall)
- **Software** = Bot uberwacht den Preis und schliesst die Position (erfordert laufenden Bot)

### Bitget

- **Trailing Stop:** Nativ unterstutzt via `place-tpsl-order` (planType: moving_plan)
- **TP/SL:** Position-Level-Endpoint (`place-pos-tpsl`) — jeder Aufruf ersetzt den vorherigen Stand
- **Funding Fees:** Werden beim Schliessen abgefragt und gespeichert
- **Ordertyp:** Market Orders

### BingX

- **Trailing Stop:** Nativ unterstutzt via TRAILING_STOP_MARKET
- **TP/SL:** Separate Conditional Orders (TAKE_PROFIT_MARKET, STOP_MARKET)
- **Besonderheit:** TP/SL sind eigenstandige Orders — beim Andern werden erst neue platziert, dann alte gecancelt (Position immer geschutzt)
- **Demo-Modus:** VST (Virtual Simulated Trading)

### Weex

- **Trailing Stop:** Software-basiert (Bot-uberwacht)
- **TP/SL:** Separate Trigger-Orders uber V3 API (`placeTpSlOrder`)
- **Besonderheit:** V3 API seit 2026-03-09, einige Endpoints noch auf V2
- **Demo-Modus:** Paper-Trading uber Header-Flag

### Hyperliquid (DEX)

- **Trailing Stop:** Software-basiert (Bot-uberwacht)
- **TP/SL:** Position-Level via `positionTpsl` Grouping (size=0, auto-adjusting)
- **Builder Fee:** Hyperliquid-spezifische Umsatzbeteiligung
  - Wird vom Admin konfiguriert (Wallet-Adresse + Fee-Rate)
  - Benutzer mussen die Teilnahme genehmigen (4-Schritt-Wizard)
  - Fee wird pro Trade berechnet und separat gespeichert
- **Referral-Programm:** Wird beim Bot-Start gepruft
- **Funding Fees:** Werden uber die API abgefragt

### Bitunix

- **Trailing Stop:** Software-basiert (Bot-uberwacht)
- **TP/SL:** Position-Level mit Fallback auf regulare Orders
- **Besonderheit:** Hat `modify_position_tpsl` Endpoint fur Updates
- **Demo-Modus:** Testnet-API

### Demo-Modus Einschrankungen

- **Funding Fees:** Die meisten Demo-APIs liefern keine Funding-Daten. Daher ist `funding_paid` bei Demo-Trades in der Regel 0. Die Trading-Fees (Handelsgebuhren) werden aber korrekt berechnet.
- **Builder Fees:** Werden im Demo-Modus nicht berechnet (kein echtes Geld)
- **Orderausfuhrung:** Kann von Live-Bedingungen abweichen (kein Slippage, sofortige Fulls)

---

## 10. Alle konfigurierbaren Parameter

### Strategie-Parameter

| Parameter | Standard | Konservativ | Bereich | Beschreibung |
|-----------|----------|-------------|---------|-------------|
| `risk_profile` | standard | conservative | - | Risikoprofil |
| `ema_fast_period` | 8 | 8 | 2-200 | Schneller EMA |
| `ema_slow_period` | 21 | 21 | 5-400 | Langsamer EMA |
| `adx_period` | 14 | 14 | 2-100 | ADX-Berechnungsperiode |
| `adx_chop_threshold` | 18.0 | 22.0 | 5-50 | ADX-Schwelle (Chop-Filter) |
| `use_adx_filter` | Ein | Ein | - | ADX-Filter aktivieren |
| `momentum_bull_threshold` | 0.35 | 0.40 | 0-1 | Bullische Momentum-Schwelle |
| `momentum_bear_threshold` | -0.35 | -0.40 | -1 bis 0 | Barische Momentum-Schwelle |
| `momentum_smooth_period` | 5 | 7 | 2-20 | Momentum-Glattung |
| `min_confidence` | 65 | 65 | 10-90 | Mindest-Konfidenz fur Trade |
| `trailing_stop_enabled` | Ein | Ein | - | Trailing Stop aktivieren |
| `trailing_breakeven_atr` | 1.5 | 2.0 | - | Breakeven-Schwelle (ATR-Faktor) |
| `trailing_trail_atr` | 2.5 | 3.0 | - | Nachlauf-Abstand (ATR-Faktor) |
| `default_sl_atr` | 0 | 0 | - | Standard-SL (0 = aus, 2 = 2x ATR) |
| `kline_interval` | 1h | 4h | 15m/30m/1h/4h | Kerzen-Zeitrahmen |
| `use_macd_floor` | Ein | Ein | - | MACD-Boden (verhindert Division durch 0) |

### Bot-Parameter

| Parameter | Beschreibung |
|-----------|-------------|
| `leverage` | Hebel (global oder pro Paar) |
| `position_size_percent` | Basispositionsgrosse in % des Kontostands |
| `take_profit_percent` | Take Profit in % uber Einstieg |
| `stop_loss_percent` | Stop Loss in % unter Einstieg |
| `daily_loss_limit_percent` | Maximaler Tagesverlust in % |
| `max_trades_per_day` | Maximale Trades pro Tag |
| `cooldown_hours` | Wartezeit nach Trade-Schluss (Standard: 4h) |
| `margin_mode` | Cross oder Isolated |
| `schedule_type` | Intervall oder feste Uhrzeiten |

---

## 11. Haufig gestellte Fragen (FAQ)

### Warum offnet der Bot keinen Trade, obwohl der Markt steigt?

Mogliche Grunde:
1. **ADX zu niedrig:** Der Markt steigt zwar, aber der ADX zeigt keine starke Trendformation
2. **Momentum nicht bestatigt:** Der Predator Score ist noch im neutralen Bereich
3. **Konfidenz zu niedrig:** Das Signal erreicht nicht die Mindest-Konfidenz von 65%
4. **Cooldown aktiv:** Der Bot wartet noch nach dem letzten Trade
5. **Tagliches Verlustlimit erreicht:** Der Bot hat fur heute pausiert

### Was passiert wenn der Bot absturzt?

- Offene Positionen bleiben auf der Exchange bestehen
- Take-Profit und Stop-Loss (wenn gesetzt) schutzen die Position
- Der native Trailing Stop (wenn gesetzt) funktioniert unabhangig vom Bot
- Beim Neustart erkennt der Bot offene Positionen und ubernimmt die Uberwachung

### Was ist der Unterschied zwischen Take-Profit/Stop-Loss und Trailing Stop?

- **TP/SL:** Feste Preislevel, die bei Erreichung sofort auslosen
- **Trailing Stop:** Folgt dem Preis nach oben (Long) und sichert Gewinne dynamisch ab
- Beide konnen gleichzeitig aktiv sein - was zuerst ausgelost wird, schliesst die Position

### Warum sind die Funding-Fees bei Demo-Trades 0?

Die meisten Exchange-Demo-APIs liefern keine Funding-Fee-Daten. Im Live-Modus werden Funding Fees (alle 8 Stunden bei Perpetual Contracts) korrekt erfasst und in die PNL-Berechnung einbezogen.

---

---

# ENGLISH

## 1. Overview

The **Edge Indicator Strategy** is based on the TradingView "Trading Edge" indicator. It combines three analysis layers to generate trading signals:

1. **EMA Ribbon (8/21)** - Detects trend direction
2. **ADX Chop Filter** - Filters out sideways markets
3. **Predator Momentum Score** - Confirms trend and determines timing

**Data Source:** Exclusively Binance OHLCV candles (klines). Regardless of which exchange you trade on, analysis data always comes from Binance - ensuring consistent data.

---

## 2. Risk Profiles

The strategy offers two preconfigured risk profiles:

### Standard Profile (1h candles)
- More frequent signals, faster reaction
- ADX threshold: 18 (looser filter)
- Momentum threshold: +/-0.35
- Trailing stop distance: 2.5x ATR
- Breakeven threshold: 1.5x ATR
- **Suited for:** Active traders who want more trading opportunities

### Conservative Profile (4h candles)
- Fewer but stronger signals
- ADX threshold: 22 (stricter filter)
- Momentum threshold: +/-0.40 (higher bar)
- Trailing stop distance: 3.0x ATR (wider protection)
- Breakeven threshold: 2.0x ATR
- Momentum smoothing: 7 instead of 5 (less noise)
- **Suited for:** Risk-averse traders who prioritize quality over quantity

---

## 3. How a Signal is Generated

### Step 1: EMA Ribbon (Trend Direction)

Two exponential moving averages (EMA 8 and EMA 21) form a "ribbon":

| Situation | Meaning |
|-----------|---------|
| Price above both EMAs | **Bullish trend** (uptrend) |
| Price below both EMAs | **Bearish trend** (downtrend) |
| Price between EMAs | **Neutral** (no clear signal) |

### Step 2: ADX Chop Filter (Market Quality)

The ADX (Average Directional Index) measures trend **strength** - not direction:

- **ADX above threshold** (Standard: 18, Conservative: 22) = Market is **trending** - trading allowed
- **ADX below threshold** = Market is **sideways/choppy** - no trading

This filter prevents the bot from trading in directionless markets where losses accumulate.

### Step 3: Predator Momentum Score (Confirmation)

The momentum score combines three components into a number between -1 and +1:

1. **MACD Normalization:** MACD histogram normalized via tanh function
2. **RSI Drift:** Rate of change of smoothed RSI
3. **Trend Bonus:** +0.6 if EMA8 > EMA21 (bullish), -0.6 if EMA8 < EMA21 (bearish)

**Formula:** `Score = tanh(MACD/stdev) + tanh(RSI_drift/2) + Trend_Bonus` (clamped to -1 to +1)

The score is additionally smoothed with an EMA to dampen short-term fluctuations.

**Regime Detection:**
- Score > threshold = **Bullish regime** (long signals preferred)
- Score < -threshold = **Bearish regime** (short signals preferred)
- In between = **Neutral regime** (no signal)

### Step 4: Signal Determination

A trading signal is only generated when multiple conditions are met simultaneously:

**LONG Signal:**
- Bullish trend (price above both EMAs) AND market trending AND momentum neutral or bullish
- OR: Market trending AND bullish regime AND no bearish trend

**SHORT Signal:**
- Bearish trend (price below both EMAs) AND market trending AND momentum neutral or bearish
- OR: Market trending AND bearish regime AND no bullish trend

---

## 4. Confidence Scoring

Each signal receives a confidence score (0-95%) that determines **how certain** the strategy is:

| Component | Points | Condition |
|-----------|--------|-----------|
| Base | 50 | Always |
| ADX Strength | 0-25 | The higher the ADX above threshold, the more points |
| Momentum Magnitude | 0-20 | Score > 0.5: +20, > 0.3: +12, > 0.15: +5 |
| Full Alignment | +10 | Trend + Momentum + ADX all point the same direction |
| Regime Flip | +10 | Momentum just flipped sides (fresh signal) |

**Minimum Confidence:** By default, a signal must reach at least **65% confidence** to trigger a trade. This value is configurable (10-90%).

**Effect on Position Size:**

| Confidence | Multiplier |
|-----------|-----------|
| 85%+ | 1.5x of base size |
| 75%+ | 1.25x |
| 65%+ | 1.0x (standard) |
| 55%+ | 0.75x |
| below 55% | 0.5x |

---

## 5. Position Sizing and Risk

### Position Size Calculation

1. **Base:** Configured percentage of account balance (e.g., 10%)
2. **Scaling:** Multiplied by confidence factor (see above)
3. **Maximum:** Capped at 25% of account balance per trade
4. **Minimum:** At least 5 USDT order volume
5. **Leverage:** Applied to the position (e.g., 5x leverage = 5x position value)

**Example:**
- Account balance: 10,000 USDT
- Base size: 10% = 1,000 USDT
- Confidence 80% -> multiplier 1.25x -> 1,250 USDT
- Leverage 5x -> market position value: 6,250 USDT

### Daily Loss Limit

When configured (e.g., 5%), the bot stops trading for the rest of the day once daily losses reach this threshold.

**Profit Lock-In:**
When enabled and the day is in profit, the loss limit is dynamically adjusted to secure part of the gains. Example: At 3% daily profit and 75% lock-in, only 0.75% drawdown is tolerated.

### Per-Symbol Configuration

Each trading pair can be individually configured with its own leverage, position size, loss limit, and maximum daily trades.

---

## 6. Trailing Stop - Two-Layer Protection

The trailing stop is the most important tool for securing profits. The strategy uses a **two-layer system**:

### Layer 1: Native Exchange Trailing Stop

- Submitted directly to the exchange when the order is placed
- The exchange monitors and executes the stop independently
- No bot intervention needed - works even if the bot goes offline

**Parameters:**
- **Activation Price (Trigger):** Price must first move into profit by `ATR x Breakeven Factor` before the trailing stop activates
  - Standard: 1.5x ATR above entry
  - Conservative: 2.0x ATR above entry
- **Trail Distance (Callback):** Maximum drawdown from the highest point before closing
  - Standard: 2.5x ATR
  - Conservative: 3.0x ATR

**Example (BTCUSDT, ATR = $800):**
- Entry: $50,000 (Long)
- Activation: $50,000 + ($800 x 1.5) = **$51,200** - trailing stop starts here
- Trail distance: $800 x 2.5 = **$2,000** - subtracted from highest price
- Price rises to $53,000 -> trailing stop at $53,000 - $2,000 = **$51,000**
- Price drops to $51,000 -> **Position closed with +$1,000 profit**

### Layer 2: Software Trailing Stop (Backup)

If the native trailing stop couldn't be placed or the exchange doesn't support it:

- Bot checks current price **every minute**
- Tracks highest price since entry
- Calculates stop level identically to native trailing stop
- Additionally: **Breakeven floor** - trailing stop never falls below entry price

---

## 7. Strategy Exit (Indicator-based)

Independent of the trailing stop, the strategy can signal an exit when market conditions change. Checked **every minute**:

### Exit for LONG Positions

| Condition | Description |
|-----------|-------------|
| **Trend Reversal** | Price drops below both EMAs (bearish trend) |
| **Trend Weakening** | Price enters EMA ribbon AND momentum turns bearish |
| **Regime Flip** | Momentum switches from bullish to bearish |

### Exit for SHORT Positions

| Condition | Description |
|-----------|-------------|
| **Trend Reversal** | Price rises above both EMAs (bullish trend) |
| **Trend Weakening** | Price enters EMA ribbon AND momentum turns bullish |
| **Regime Flip** | Momentum switches from bearish to bullish |

### Important: When is Strategy Exit NOT checked?

When Take-Profit OR Stop-Loss is set on the exchange AND trailing stop is disabled, the bot skips strategy exit checks. Exchange orders take priority as they react faster.

---

## 8. Bot Workflow in Detail

### Initialization (on startup)

1. Load configuration from database
2. Establish exchange connection (API keys)
3. Create separate clients for demo/live
4. Initialize strategy with parameters
5. Set up risk manager
6. For Hyperliquid: verify builder fee and referral approval
7. Validate trading pairs on exchange
8. Query account balance, start daily session

### Main Loop

The bot executes three periodic tasks:

| Task | Frequency | Purpose |
|------|-----------|---------|
| **Analyze & Trade** | Configurable (e.g., every 60 min) | Generate signals, execute trades |
| **Monitor Positions** | Every minute | Trailing stop, exit checks, glitch detection |
| **Daily Summary** | 23:55 UTC | Send performance report |

### Safety Mechanisms

- **Per-Symbol Lock:** Prevents duplicate positions for the same pair
- **Per-User Lock:** Only one bot per user can execute a trade at any time
- **Cooldown:** Waits 4 hours after closing a trade (configurable)
- **Signal Deduplication:** Identical signals within 60 seconds are ignored
- **Error Tolerance:** After 5 consecutive errors, bot pauses for 60 seconds

---

## 9. Exchange Specifics

### Exchange Support Matrix

| Feature | Bitget | BingX | Weex | Hyperliquid | Bitunix |
|---------|--------|-------|------|-------------|---------|
| **Set TP/SL** | Native (Position-Level) | Native (Conditional Orders) | Native (Trigger Orders) | Native (positionTpsl) | Native (Position-Level) |
| **Modify TP/SL** | Replaces automatically | Place + Cancel old | Place + Cancel old | Replaces automatically | Replaces automatically |
| **Remove TP/SL** | Cancel Plan Orders | Cancel Conditionals | Cancel Triggers | Empty positionTpsl | Cancel Pending |
| **Trailing Stop** | **Native** (moving_plan) | **Native** (TRAILING_STOP_MARKET) | Software (bot-monitored) | Software (bot-monitored) | Software (bot-monitored) |
| **Demo Mode** | Testnet API | VST API | Paper Trading Header | Testnet | Testnet |
| **Margin Modes** | Cross + Isolated | Cross + Isolated | Cross + Isolated | Cross + Isolated | Cross + Isolated |

**Legend:**
- **Native** = Exchange executes the stop independently (works even if bot is offline)
- **Software** = Bot monitors price and closes position (requires running bot)

### Bitget

- **Trailing Stop:** Natively supported via `place-tpsl-order` (planType: moving_plan)
- **TP/SL:** Position-level endpoint — each call replaces the previous state
- **Funding Fees:** Queried on close and stored
- **Order Type:** Market orders

### BingX

- **Trailing Stop:** Natively supported via TRAILING_STOP_MARKET
- **TP/SL:** Separate conditional orders (TAKE_PROFIT_MARKET, STOP_MARKET)
- **Note:** When modifying, new orders are placed first, then old ones cancelled (position always protected)
- **Demo Mode:** VST (Virtual Simulated Trading)

### Weex

- **Trailing Stop:** Software-based (bot-monitored)
- **TP/SL:** Separate trigger orders via V3 API
- **Note:** V3 API since 2026-03-09, some endpoints still on V2
- **Demo Mode:** Paper trading via header flag

### Hyperliquid (DEX)

- **Trailing Stop:** Software-based (bot-monitored)
- **TP/SL:** Position-level via positionTpsl grouping (size=0, auto-adjusting)
- **Builder Fee:** Hyperliquid-specific revenue sharing
  - Configured by admin (wallet address + fee rate)
  - Users must approve participation (4-step wizard)
  - Fee calculated per trade and stored separately
- **Referral Program:** Verified on bot startup
- **Funding Fees:** Queried via API

### Bitunix

- **Trailing Stop:** Software-based (bot-monitored)
- **TP/SL:** Position-level with fallback to regular orders
- **Note:** Has dedicated `modify_position_tpsl` endpoint for updates
- **Demo Mode:** Testnet API

### Demo Mode Limitations

- **Funding Fees:** Most demo APIs don't provide funding data. Therefore `funding_paid` is typically 0 for demo trades. Trading fees are calculated correctly.
- **Builder Fees:** Not calculated in demo mode (no real money)
- **Order Execution:** May differ from live conditions (no slippage, instant fills)

---

## 10. All Configurable Parameters

### Strategy Parameters

| Parameter | Standard | Conservative | Range | Description |
|-----------|----------|-------------|-------|-------------|
| `risk_profile` | standard | conservative | - | Risk profile |
| `ema_fast_period` | 8 | 8 | 2-200 | Fast EMA |
| `ema_slow_period` | 21 | 21 | 5-400 | Slow EMA |
| `adx_period` | 14 | 14 | 2-100 | ADX calculation period |
| `adx_chop_threshold` | 18.0 | 22.0 | 5-50 | ADX threshold (chop filter) |
| `use_adx_filter` | On | On | - | Enable ADX filter |
| `momentum_bull_threshold` | 0.35 | 0.40 | 0-1 | Bullish momentum threshold |
| `momentum_bear_threshold` | -0.35 | -0.40 | -1 to 0 | Bearish momentum threshold |
| `momentum_smooth_period` | 5 | 7 | 2-20 | Momentum smoothing |
| `min_confidence` | 65 | 65 | 10-90 | Minimum confidence for trade |
| `trailing_stop_enabled` | On | On | - | Enable trailing stop |
| `trailing_breakeven_atr` | 1.5 | 2.0 | - | Breakeven threshold (ATR factor) |
| `trailing_trail_atr` | 2.5 | 3.0 | - | Trail distance (ATR factor) |
| `default_sl_atr` | 0 | 0 | - | Default SL (0 = off, 2 = 2x ATR) |
| `kline_interval` | 1h | 4h | 15m/30m/1h/4h | Candle timeframe |
| `use_macd_floor` | On | On | - | MACD floor (prevents division by 0) |

### Bot Parameters

| Parameter | Description |
|-----------|-------------|
| `leverage` | Leverage (global or per pair) |
| `position_size_percent` | Base position size as % of account balance |
| `take_profit_percent` | Take profit as % above entry |
| `stop_loss_percent` | Stop loss as % below entry |
| `daily_loss_limit_percent` | Maximum daily loss in % |
| `max_trades_per_day` | Maximum trades per day |
| `cooldown_hours` | Wait time after trade close (default: 4h) |
| `margin_mode` | Cross or Isolated |
| `schedule_type` | Interval or fixed hours |

---

## 11. Frequently Asked Questions (FAQ)

### Why doesn't the bot open a trade even though the market is rising?

Possible reasons:
1. **ADX too low:** The market is rising but ADX doesn't show a strong trend formation
2. **Momentum not confirmed:** The Predator Score is still in the neutral range
3. **Confidence too low:** The signal doesn't reach the minimum confidence of 65%
4. **Cooldown active:** The bot is still waiting after the last trade
5. **Daily loss limit reached:** The bot has paused for today

### What happens if the bot crashes?

- Open positions remain on the exchange
- Take-profit and stop-loss (if set) protect the position
- Native trailing stop (if set) operates independently of the bot
- On restart, the bot detects open positions and resumes monitoring

### What's the difference between TP/SL and trailing stop?

- **TP/SL:** Fixed price levels that trigger immediately when reached
- **Trailing Stop:** Follows price upward (long) and dynamically secures profits
- Both can be active simultaneously - whichever triggers first closes the position

### Why are funding fees 0 on demo trades?

Most exchange demo APIs don't provide funding fee data. In live mode, funding fees (every 8 hours for perpetual contracts) are correctly captured and included in PNL calculations.
