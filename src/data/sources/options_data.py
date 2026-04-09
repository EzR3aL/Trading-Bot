"""Options/derivatives data from Deribit."""

import time
from datetime import datetime
from typing import Dict, Any

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

logger = get_logger(__name__)

DERIBIT_URL = "https://www.deribit.com/api/v2"


async def fetch_options_oi_deribit(fetcher, currency: str = "BTC") -> Dict[str, Any]:
    """Fetch total options open interest from Deribit (public, no auth).

    Returns:
        Dict with total_oi, num_instruments, currency
    """
    try:
        url = f"{DERIBIT_URL}/public/get_book_summary_by_currency"
        params = {"currency": currency, "kind": "option"}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.deribit_breaker.call(_fetch)

        if data and "result" in data:
            instruments = data["result"]
            total_oi = sum(float(i.get("open_interest", 0)) for i in instruments)
            logger.info(f"Deribit Options OI ({currency}): {total_oi:.2f} across {len(instruments)} instruments")
            return {
                "total_oi": total_oi,
                "num_instruments": len(instruments),
                "currency": currency,
            }

    except CircuitBreakerError as e:
        logger.warning(f"Deribit API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching Deribit options OI: {e}")

    return {"total_oi": 0.0, "num_instruments": 0, "currency": currency}


async def fetch_max_pain(fetcher, currency: str = "BTC") -> Dict[str, Any]:
    """Calculate the max pain price from Deribit options data.

    Max pain = strike price where the most options expire worthless.

    Returns:
        Dict with max_pain_price, nearest_expiry
    """
    try:
        url = f"{DERIBIT_URL}/public/get_instruments"
        params = {"currency": currency, "kind": "option", "expired": "false"}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.deribit_breaker.call(_fetch)

        if not data or "result" not in data:
            return {"max_pain_price": 0.0, "nearest_expiry": ""}

        instruments = data["result"]
        if not instruments:
            return {"max_pain_price": 0.0, "nearest_expiry": ""}

        now_ms = datetime.now().timestamp() * 1000
        expiries = sorted(set(
            i["expiration_timestamp"] for i in instruments
            if i["expiration_timestamp"] > now_ms
        ))
        if not expiries:
            return {"max_pain_price": 0.0, "nearest_expiry": ""}

        nearest_exp = expiries[0]
        nearest_instruments = [
            i for i in instruments
            if i["expiration_timestamp"] == nearest_exp
        ]

        strikes: Dict[float, Dict[str, float]] = {}
        for inst in nearest_instruments:
            strike = float(inst["strike"])
            if strike not in strikes:
                strikes[strike] = {"call_oi": 0.0, "put_oi": 0.0}
            oi = float(inst.get("open_interest", 0) or 0)
            if inst["option_type"] == "call":
                strikes[strike]["call_oi"] += oi
            else:
                strikes[strike]["put_oi"] += oi

        if not strikes:
            return {"max_pain_price": 0.0, "nearest_expiry": ""}

        strike_list = sorted(strikes.keys())
        min_pain = float("inf")
        max_pain_strike = 0.0

        for test_price in strike_list:
            total_pain = 0.0
            for strike, oi_data in strikes.items():
                if test_price > strike:
                    total_pain += (test_price - strike) * oi_data["call_oi"]
                if test_price < strike:
                    total_pain += (strike - test_price) * oi_data["put_oi"]
            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = test_price

        expiry_dt = datetime.fromtimestamp(nearest_exp / 1000)
        logger.info(f"Max Pain ({currency}): ${max_pain_strike:,.0f} (expiry {expiry_dt.date()})")
        return {
            "max_pain_price": max_pain_strike,
            "nearest_expiry": expiry_dt.isoformat(),
        }

    except CircuitBreakerError as e:
        logger.warning(f"Deribit API circuit open for max pain: {e}")
    except Exception as e:
        logger.error(f"Error calculating max pain: {e}")

    return {"max_pain_price": 0.0, "nearest_expiry": ""}


async def fetch_put_call_ratio(fetcher, currency: str = "BTC") -> Dict[str, Any]:
    """Calculate put/call ratio from Deribit options open interest.

    Ratio > 1 = more puts (bearish), < 1 = more calls (bullish).

    Returns:
        Dict with ratio, total_puts, total_calls
    """
    try:
        url = f"{DERIBIT_URL}/public/get_book_summary_by_currency"
        params = {"currency": currency, "kind": "option"}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.deribit_breaker.call(_fetch)

        if data and "result" in data:
            instruments = data["result"]
            total_puts = 0.0
            total_calls = 0.0
            for inst in instruments:
                name = inst.get("instrument_name", "")
                oi = float(inst.get("open_interest", 0) or 0)
                if "-P" in name:
                    total_puts += oi
                elif "-C" in name:
                    total_calls += oi

            ratio = total_puts / total_calls if total_calls > 0 else 0.0
            logger.info(f"Put/Call Ratio ({currency}): {ratio:.3f} (puts={total_puts:.0f}, calls={total_calls:.0f})")
            return {
                "ratio": ratio,
                "total_puts": total_puts,
                "total_calls": total_calls,
            }

    except CircuitBreakerError as e:
        logger.warning(f"Deribit API circuit open for P/C ratio: {e}")
    except Exception as e:
        logger.error(f"Error fetching put/call ratio: {e}")

    return {"ratio": 0.0, "total_puts": 0.0, "total_calls": 0.0}


async def fetch_deribit_options_extended(fetcher, currency: str = "BTC") -> Dict[str, Any]:
    """Full options data from Deribit: IV per tenor, Skew, Put/Call Ratio.

    Returns:
        Dict with avg_iv, put_call_ratio, skew_25delta, total_call_oi, total_put_oi, total_oi
    """
    try:
        url = f"{DERIBIT_URL}/public/get_book_summary_by_currency"
        params = {"currency": currency, "kind": "option"}

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.deribit_breaker.call(_fetch)

        if not data or "result" not in data:
            return _empty_options_extended(currency)

        instruments = data["result"]
        if not instruments:
            return _empty_options_extended(currency)

        total_call_oi = 0.0
        total_put_oi = 0.0
        iv_values = []
        call_ivs = []
        put_ivs = []

        for inst in instruments:
            name = inst.get("instrument_name", "")
            oi = float(inst.get("open_interest", 0))
            iv = float(inst.get("mark_iv", 0))

            if iv > 0:
                iv_values.append(iv)

            if "-C" in name:
                total_call_oi += oi
                if iv > 0:
                    call_ivs.append(iv)
            elif "-P" in name:
                total_put_oi += oi
                if iv > 0:
                    put_ivs.append(iv)

        total_oi = total_call_oi + total_put_oi
        pc_ratio = total_put_oi / total_call_oi if total_call_oi > 0 else 0.0
        avg_iv = sum(iv_values) / len(iv_values) if iv_values else 0.0

        avg_call_iv = sum(call_ivs) / len(call_ivs) if call_ivs else 0.0
        avg_put_iv = sum(put_ivs) / len(put_ivs) if put_ivs else 0.0
        skew = avg_put_iv - avg_call_iv

        logger.info(
            f"Deribit Options Extended ({currency}): P/C={pc_ratio:.2f}, "
            f"IV={avg_iv:.1f}%, Skew={skew:.1f}%"
        )
        return {
            "avg_iv": round(avg_iv, 2),
            "put_call_ratio": round(pc_ratio, 3),
            "skew_25delta": round(skew, 2),
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "total_oi": total_oi,
            "currency": currency,
        }

    except CircuitBreakerError as e:
        logger.warning(f"Deribit API circuit open (extended): {e}")
    except Exception as e:
        logger.error(f"Error fetching Deribit extended options: {e}")

    return _empty_options_extended(currency)


async def fetch_deribit_dvol(fetcher, currency: str = "BTC") -> Dict[str, Any]:
    """Fetch Deribit Volatility Index (DVOL) -- the crypto VIX equivalent.

    Returns:
        Dict with dvol_current, dvol_24h_ago, dvol_change_pct, signal
    """
    try:
        now_ms = int(time.time() * 1000)
        day_ago_ms = now_ms - 86_400_000

        url = f"{DERIBIT_URL}/public/get_volatility_index_data"
        params = {
            "currency": currency,
            "resolution": "3600",
            "start_timestamp": str(day_ago_ms),
            "end_timestamp": str(now_ms),
        }

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.deribit_breaker.call(_fetch)

        if not data or "result" not in data:
            return {"dvol_current": 0.0, "dvol_24h_ago": 0.0, "dvol_change_pct": 0.0, "signal": "neutral"}

        candles = data["result"].get("data", [])
        if not candles:
            return {"dvol_current": 0.0, "dvol_24h_ago": 0.0, "dvol_change_pct": 0.0, "signal": "neutral"}

        dvol_current = float(candles[-1][4])
        dvol_24h_ago = float(candles[0][1])

        change_pct = ((dvol_current - dvol_24h_ago) / dvol_24h_ago * 100) if dvol_24h_ago > 0 else 0.0

        if change_pct > 5:
            signal = "fear_rising"
        elif change_pct < -5:
            signal = "complacency"
        else:
            signal = "stable"

        logger.info(f"Deribit DVOL ({currency}): {dvol_current:.1f} ({change_pct:+.1f}% 24h)")
        return {
            "dvol_current": round(dvol_current, 2),
            "dvol_24h_ago": round(dvol_24h_ago, 2),
            "dvol_change_pct": round(change_pct, 2),
            "signal": signal,
        }

    except CircuitBreakerError as e:
        logger.warning(f"Deribit API circuit open (DVOL): {e}")
    except Exception as e:
        logger.error(f"Error fetching Deribit DVOL: {e}")

    return {"dvol_current": 0.0, "dvol_24h_ago": 0.0, "dvol_change_pct": 0.0, "signal": "neutral"}


def _empty_options_extended(currency: str) -> Dict[str, Any]:
    """Return empty options extended data structure."""
    return {
        "avg_iv": 0.0, "put_call_ratio": 0.0, "skew_25delta": 0.0,
        "total_call_oi": 0.0, "total_put_oi": 0.0, "total_oi": 0.0,
        "currency": currency,
    }
