"""Candlestick/OHLCV data and technical indicator calculations (Binance klines)."""

from datetime import datetime
from typing import Dict, Any, List

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

from .base import to_binance_symbol

logger = get_logger(__name__)

BINANCE_FUTURES_URL = "https://fapi.binance.com"


async def fetch_binance_klines(
    fetcher, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 24
) -> List[List]:
    """Fetch kline/candlestick data from Binance Futures.

    Each kline: [open_time, open, high, low, close, volume, close_time,
                 quote_volume, num_trades, taker_buy_base_vol,
                 taker_buy_quote_vol, ignore]

    Returns:
        List of kline arrays, or empty list on failure.
    """
    try:
        binance_sym = to_binance_symbol(symbol)
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/klines"
        params = {"symbol": binance_sym, "interval": interval, "limit": limit}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.binance_breaker.call(_fetch)
        if data and isinstance(data, list):
            logger.info(f"Klines ({symbol}, {interval}): fetched {len(data)} candles")
            return data

    except CircuitBreakerError as e:
        logger.warning(f"Binance API circuit open for klines: {e}")
    except Exception as e:
        logger.error(f"Error fetching klines: {e}")

    return []


async def fetch_price_volatility(fetcher, symbol: str = "BTCUSDT", period: int = 24) -> float:
    """Calculate price volatility based on recent candles.

    Returns:
        Volatility as percentage
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/klines"
        params = {
            "symbol": to_binance_symbol(symbol),
            "interval": "1h",
            "limit": period,
        }

        data = await fetcher._get(url, params)

        if data:
            highs = [float(candle[2]) for candle in data]
            lows = [float(candle[3]) for candle in data]

            ranges = [(h - lo) / lo * 100 for h, lo in zip(highs, lows)]
            avg_volatility = sum(ranges) / len(ranges)

            logger.info(f"24h Volatility ({symbol}): {avg_volatility:.2f}%")
            return avg_volatility

    except Exception as e:
        logger.error(f"Error calculating volatility: {e}")

    return 3.0  # Default 3% volatility


async def fetch_trend_direction(fetcher, symbol: str = "BTCUSDT") -> str:
    """Determine short-term trend direction using simple moving averages.

    Returns:
        'bullish', 'bearish', or 'neutral'
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/klines"
        params = {
            "symbol": to_binance_symbol(symbol),
            "interval": "1h",
            "limit": 24,
        }

        data = await fetcher._get(url, params)

        if data and len(data) >= 24:
            closes = [float(candle[4]) for candle in data]

            sma_8 = sum(closes[-8:]) / 8
            sma_21 = sum(closes[-21:]) / 21

            current_price = closes[-1]

            if current_price > sma_8 > sma_21:
                trend = "bullish"
            elif current_price < sma_8 < sma_21:
                trend = "bearish"
            else:
                trend = "neutral"

            logger.info(f"Trend ({symbol}): {trend} (Price: {current_price:.2f}, SMA8: {sma_8:.2f}, SMA21: {sma_21:.2f})")
            return trend

    except Exception as e:
        logger.error(f"Error determining trend: {e}")

    return "neutral"


async def fetch_cme_gap(fetcher, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """Detect CME gap by comparing Friday 21:00 UTC close with current price.

    CME BTC futures trade Mon-Fri. Weekend gaps often get filled.

    Returns:
        Dict with gap_pct, friday_close, current_price, gap_direction
    """
    try:
        # Use fetcher method to allow test mocking
        klines = await fetcher.get_binance_klines(symbol, "4h", 42)
        if not klines:
            return {"gap_pct": 0.0, "friday_close": 0.0, "current_price": 0.0, "gap_direction": "none"}

        friday_close = 0.0
        for k in reversed(klines):
            ts = datetime.fromtimestamp(int(k[0]) / 1000)
            if ts.weekday() == 4 and ts.hour >= 20:
                friday_close = float(k[4])
                break

        if friday_close == 0:
            return {"gap_pct": 0.0, "friday_close": 0.0, "current_price": 0.0, "gap_direction": "none"}

        current_price = float(klines[-1][4])
        gap_pct = ((current_price - friday_close) / friday_close) * 100
        direction = "up" if gap_pct > 0.5 else "down" if gap_pct < -0.5 else "none"

        logger.info(f"CME Gap ({symbol}): {gap_pct:.2f}% (Fri close=${friday_close:,.0f}, now=${current_price:,.0f})")
        return {
            "gap_pct": gap_pct,
            "friday_close": friday_close,
            "current_price": current_price,
            "gap_direction": direction,
        }

    except Exception as e:
        logger.error(f"Error detecting CME gap: {e}")

    return {"gap_pct": 0.0, "friday_close": 0.0, "current_price": 0.0, "gap_direction": "none"}


async def fetch_cvd(fetcher, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 24) -> Dict[str, Any]:
    """Calculate Cumulative Volume Delta from Binance klines.

    CVD = sum(taker_buy_volume - taker_sell_volume) over the period.
    Positive CVD = aggressive buying dominance, negative = selling dominance.

    Returns:
        Dict with cvd_total, cvd_trend, taker_buy_ratio, data_points
    """
    try:
        url = f"{BINANCE_FUTURES_URL}/fapi/v1/klines"
        params = {"symbol": to_binance_symbol(symbol), "interval": interval, "limit": limit}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.binance_breaker.call(_fetch)

        if not data or not isinstance(data, list):
            return {"cvd_total": 0.0, "cvd_trend": "neutral", "taker_buy_ratio": 0.5, "data_points": 0}

        cvd_values = []
        cumulative = 0.0
        total_volume = 0.0
        total_taker_buy = 0.0

        for k in data:
            taker_buy_base = float(k[9])
            taker_sell_base = float(k[7]) - float(k[9])
            delta = taker_buy_base - taker_sell_base
            cumulative += delta
            cvd_values.append(cumulative)
            total_volume += float(k[7])
            total_taker_buy += taker_buy_base

        buy_ratio = total_taker_buy / total_volume if total_volume > 0 else 0.5

        mid = len(cvd_values) // 2
        first_half_avg = sum(cvd_values[:mid]) / mid if mid > 0 else 0
        second_half_avg = sum(cvd_values[mid:]) / len(cvd_values[mid:]) if cvd_values[mid:] else 0
        trend = "bullish" if second_half_avg > first_half_avg else "bearish" if second_half_avg < first_half_avg else "neutral"

        logger.info(f"CVD ({symbol}): total={cumulative:.2f}, trend={trend}, buy_ratio={buy_ratio:.2%}")
        return {
            "cvd_total": cumulative,
            "cvd_trend": trend,
            "taker_buy_ratio": round(buy_ratio, 4),
            "data_points": len(data),
        }

    except CircuitBreakerError as e:
        logger.warning(f"Binance API circuit open (CVD): {e}")
    except Exception as e:
        logger.error(f"Error fetching CVD: {e}")

    return {"cvd_total": 0.0, "cvd_trend": "neutral", "taker_buy_ratio": 0.5, "data_points": 0}


# ==================== Static Indicator Calculations ====================


def calculate_vwap(klines: List[List]) -> float:
    """Calculate Volume-Weighted Average Price from kline data.

    VWAP = sum(typical_price * volume) / sum(volume)
    typical_price = (high + low + close) / 3

    Returns:
        VWAP price, or 0.0 if no data.
    """
    if not klines:
        return 0.0

    total_tp_vol = 0.0
    total_vol = 0.0

    for k in klines:
        try:
            high = float(k[2])
            low = float(k[3])
            close = float(k[4])
            volume = float(k[5])
            typical_price = (high + low + close) / 3
            total_tp_vol += typical_price * volume
            total_vol += volume
        except (IndexError, ValueError, TypeError):
            continue

    if total_vol == 0:
        return 0.0

    return total_tp_vol / total_vol


def calculate_atr(klines: List[List], period: int = 14) -> List[float]:
    """Calculate Average True Range using Wilder's smoothing.

    TR = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR[period-1] = SMA(TR, period)
    ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period

    Returns:
        List of ATR values (same length as klines, 0.0 for warmup).
    """
    if not klines or len(klines) < period + 1:
        return [0.0] * len(klines) if klines else []

    highs = []
    lows = []
    closes = []
    for k in klines:
        try:
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            closes.append(float(k[4]))
        except (IndexError, ValueError, TypeError):
            continue

    if len(closes) < period + 1:
        return [0.0] * len(closes)

    # Calculate True Range
    true_ranges = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    # Wilder's smoothing
    atr_values = [0.0] * len(true_ranges)
    for i in range(len(true_ranges)):
        if i < period - 1:
            atr_values[i] = 0.0
        elif i == period - 1:
            atr_values[i] = sum(true_ranges[:period]) / period
        else:
            atr_values[i] = (atr_values[i - 1] * (period - 1) + true_ranges[i]) / period

    return atr_values


def calculate_supertrend(
    klines: List[List], atr_period: int = 10, multiplier: float = 3.0
) -> Dict[str, Any]:
    """Calculate Supertrend indicator from kline data.

    Uses ATR (Average True Range) for dynamic support/resistance.
    Green = uptrend (price above lower band), Red = downtrend.

    Returns:
        {"direction": "bullish"|"bearish", "value": float, "atr": float}
    """
    if not klines or len(klines) < atr_period + 1:
        return {"direction": "neutral", "value": 0.0, "atr": 0.0}

    highs = []
    lows = []
    closes = []
    for k in klines:
        try:
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            closes.append(float(k[4]))
        except (IndexError, ValueError, TypeError):
            continue

    if len(closes) < atr_period + 1:
        return {"direction": "neutral", "value": 0.0, "atr": 0.0}

    atr_values = calculate_atr(klines, atr_period)

    supertrend = [0.0] * len(closes)
    direction = [1] * len(closes)  # 1 = bullish, -1 = bearish

    for i in range(atr_period, len(closes)):
        hl2 = (highs[i] + lows[i]) / 2
        upper_band = hl2 + multiplier * atr_values[i]
        lower_band = hl2 - multiplier * atr_values[i]

        if i == atr_period:
            supertrend[i] = upper_band if closes[i] <= upper_band else lower_band
            direction[i] = -1 if closes[i] <= upper_band else 1
        else:
            prev_st = supertrend[i - 1]
            prev_dir = direction[i - 1]

            if prev_dir == 1:  # was bullish
                lower_band = max(lower_band, prev_st)
                if closes[i] >= lower_band:
                    supertrend[i] = lower_band
                    direction[i] = 1
                else:
                    supertrend[i] = upper_band
                    direction[i] = -1
            else:  # was bearish
                upper_band = min(upper_band, prev_st)
                if closes[i] <= upper_band:
                    supertrend[i] = upper_band
                    direction[i] = -1
                else:
                    supertrend[i] = lower_band
                    direction[i] = 1

    current_dir = "bullish" if direction[-1] == 1 else "bearish"
    return {
        "direction": current_dir,
        "value": supertrend[-1],
        "atr": atr_values[-1],
    }


def calculate_ema(values: List[float], period: int) -> List[float]:
    """Calculate Exponential Moving Average.

    EMA[0] = SMA of first `period` values
    EMA[i] = value[i] * k + EMA[i-1] * (1 - k), where k = 2 / (period + 1)

    Returns:
        List of EMA values (same length as input, 0.0 for warmup).
    """
    if not values or period < 1 or len(values) < period:
        return [0.0] * len(values) if values else []

    k = 2.0 / (period + 1)
    ema = [0.0] * len(values)

    ema[period - 1] = sum(values[:period]) / period

    for i in range(period, len(values)):
        ema[i] = values[i] * k + ema[i - 1] * (1 - k)

    return ema


def calculate_adx(klines: List[List], period: int = 14) -> Dict[str, Any]:
    """Calculate Average Directional Index (ADX) using Wilder's method.

    ADX measures trend strength (not direction).
    ADX > 25 = strong trend, ADX < 20 = weak/choppy market.

    Returns:
        {"adx": float, "plus_di": float, "minus_di": float, "is_trending": bool}
    """
    if not klines or len(klines) < period + 1:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0, "is_trending": False}

    highs, lows, closes = [], [], []
    for k in klines:
        try:
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            closes.append(float(k[4]))
        except (IndexError, ValueError, TypeError):
            continue

    if len(closes) < period + 1:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0, "is_trending": False}

    plus_dm_list = []
    minus_dm_list = []
    tr_list = []

    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        tr_list.append(tr)

    def wilder_smooth(data: List[float], p: int) -> List[float]:
        if len(data) < p:
            return []
        smoothed = [sum(data[:p])]
        for i in range(p, len(data)):
            smoothed.append((smoothed[-1] * (p - 1) + data[i]) / p)
        return smoothed

    atr_smooth = wilder_smooth(tr_list, period)
    plus_dm_smooth = wilder_smooth(plus_dm_list, period)
    minus_dm_smooth = wilder_smooth(minus_dm_list, period)

    if not atr_smooth or not plus_dm_smooth or not minus_dm_smooth:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0, "is_trending": False}

    dx_list = []
    last_plus_di = 0.0
    last_minus_di = 0.0

    for i in range(len(atr_smooth)):
        atr_val = atr_smooth[i]
        if atr_val == 0:
            dx_list.append(0.0)
            continue

        plus_di = 100 * plus_dm_smooth[i] / atr_val
        minus_di = 100 * minus_dm_smooth[i] / atr_val

        di_sum = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0

        dx_list.append(dx)
        last_plus_di = plus_di
        last_minus_di = minus_di

    adx_smooth = wilder_smooth(dx_list, period)
    adx_value = adx_smooth[-1] if adx_smooth else 0.0

    return {
        "adx": round(adx_value, 2),
        "plus_di": round(last_plus_di, 2),
        "minus_di": round(last_minus_di, 2),
        "is_trending": adx_value >= 20.0,
    }


def calculate_macd(
    klines: List[List], fast: int = 12, slow: int = 26, signal_period: int = 9
) -> Dict[str, Any]:
    """Calculate MACD (Moving Average Convergence Divergence).

    MACD Line = EMA(fast) - EMA(slow)
    Signal Line = EMA(MACD Line, signal_period)
    Histogram = MACD Line - Signal Line

    Returns:
        {"macd_line": float, "signal_line": float, "histogram": float,
         "histogram_series": List[float]}
    """
    if not klines or len(klines) < slow + signal_period:
        return {
            "macd_line": 0.0, "signal_line": 0.0,
            "histogram": 0.0, "histogram_series": [],
        }

    closes = []
    for k in klines:
        try:
            closes.append(float(k[4]))
        except (IndexError, ValueError, TypeError):
            continue

    if len(closes) < slow + signal_period:
        return {
            "macd_line": 0.0, "signal_line": 0.0,
            "histogram": 0.0, "histogram_series": [],
        }

    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)

    macd_line_series = []
    for i in range(len(closes)):
        if i >= slow - 1 and ema_fast[i] != 0 and ema_slow[i] != 0:
            macd_line_series.append(ema_fast[i] - ema_slow[i])
        else:
            macd_line_series.append(0.0)

    valid_macd = [v for v in macd_line_series if v != 0.0 or macd_line_series.index(v) >= slow - 1]
    if len(valid_macd) < signal_period:
        valid_macd = macd_line_series[slow - 1:]

    signal_line_series = calculate_ema(valid_macd, signal_period)

    histogram_series = []
    for i in range(len(valid_macd)):
        if i >= signal_period - 1 and signal_line_series[i] != 0:
            histogram_series.append(valid_macd[i] - signal_line_series[i])
        else:
            histogram_series.append(0.0)

    macd_line = valid_macd[-1] if valid_macd else 0.0
    signal_line = signal_line_series[-1] if signal_line_series else 0.0
    histogram = macd_line - signal_line

    return {
        "macd_line": round(macd_line, 6),
        "signal_line": round(signal_line, 6),
        "histogram": round(histogram, 6),
        "histogram_series": histogram_series,
    }


def calculate_rsi(klines: List[List], period: int = 14) -> List[float]:
    """Calculate Relative Strength Index (RSI) using Wilder's smoothing.

    RSI = 100 - (100 / (1 + RS)), where RS = avg_gain / avg_loss.

    Returns:
        List of RSI values (0-100). Warmup values are 50.0.
    """
    if not klines or len(klines) < period + 1:
        return [50.0] * len(klines) if klines else []

    closes = []
    for k in klines:
        try:
            closes.append(float(k[4]))
        except (IndexError, ValueError, TypeError):
            continue

    if len(closes) < period + 1:
        return [50.0] * len(closes)

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [max(c, 0) for c in changes]
    losses = [abs(min(c, 0)) for c in changes]

    rsi_values = [50.0] * len(closes)

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_gain == 0 and avg_loss == 0:
        rsi_values[period] = 50.0
    elif avg_loss == 0:
        rsi_values[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_values[period] = 100 - (100 / (1 + rs))

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_gain == 0 and avg_loss == 0:
            rsi_values[i + 1] = 50.0
        elif avg_loss == 0:
            rsi_values[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i + 1] = 100 - (100 / (1 + rs))

    return rsi_values


def detect_rsi_divergence(
    klines: List[List], rsi_period: int = 14, lookback: int = 20
) -> Dict[str, Any]:
    """Detect bullish and bearish RSI divergence.

    Bearish divergence: price makes higher high but RSI makes lower high.
    Bullish divergence: price makes lower low but RSI makes higher low.

    Returns:
        Dict with bullish_divergence, bearish_divergence, price/rsi highs and lows.
    """
    default = {
        "bullish_divergence": False, "bearish_divergence": False,
        "price_high_1": 0.0, "price_high_2": 0.0,
        "rsi_high_1": 0.0, "rsi_high_2": 0.0,
        "price_low_1": 0.0, "price_low_2": 0.0,
        "rsi_low_1": 0.0, "rsi_low_2": 0.0,
    }

    if not klines or len(klines) < rsi_period + lookback:
        return default

    closes = []
    highs = []
    lows = []
    for k in klines:
        try:
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            closes.append(float(k[4]))
        except (IndexError, ValueError, TypeError):
            continue

    if len(closes) < rsi_period + lookback:
        return default

    rsi_values = calculate_rsi(klines, rsi_period)
    if len(rsi_values) < lookback:
        return default

    start = len(closes) - lookback
    end = len(closes) - 1

    swing_highs = []
    swing_lows = []

    for i in range(max(start, 1), end):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swing_highs.append((i, highs[i], rsi_values[i]))
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swing_lows.append((i, lows[i], rsi_values[i]))

    result = dict(default)

    if len(swing_highs) >= 2:
        prev_h = swing_highs[-2]
        curr_h = swing_highs[-1]
        result["price_high_1"] = prev_h[1]
        result["price_high_2"] = curr_h[1]
        result["rsi_high_1"] = prev_h[2]
        result["rsi_high_2"] = curr_h[2]
        if curr_h[1] > prev_h[1] and curr_h[2] < prev_h[2]:
            result["bearish_divergence"] = True

    if len(swing_lows) >= 2:
        prev_l = swing_lows[-2]
        curr_l = swing_lows[-1]
        result["price_low_1"] = prev_l[1]
        result["price_low_2"] = curr_l[1]
        result["rsi_low_1"] = prev_l[2]
        result["rsi_low_2"] = curr_l[2]
        if curr_l[1] < prev_l[1] and curr_l[2] > prev_l[2]:
            result["bullish_divergence"] = True

    return result
