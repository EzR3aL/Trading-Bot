"""Macro economic indicators (FRED, CoinGecko, DefiLlama, Blockchain.info)."""

from typing import Dict, Any

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

logger = get_logger(__name__)

FRED_URL = "https://api.stlouisfed.org/fred"
COINGECKO_URL = "https://api.coingecko.com/api/v3"
DEFILLAMA_URL = "https://stablecoins.llama.fi"
BLOCKCHAIN_URL = "https://api.blockchain.info"


async def fetch_fred_series(fetcher, series_id: str) -> Dict[str, Any]:
    """Fetch latest value of a FRED economic data series.

    Used for DXY (US Dollar Index) and Fed Funds Rate.

    Args:
        series_id: FRED series ID (e.g. 'DTWEXBGS' for DXY, 'DFF' for Fed Funds)

    Returns:
        Dict with value, date, series_id
    """
    import os

    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        return {"value": 0.0, "date": "", "series_id": series_id}

    try:
        url = f"{FRED_URL}/series/observations"
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": "1",
        }

        async def _fetch():
            return await fetcher._get_with_retry(url, params)

        data = await _breakers.fred_breaker.call(_fetch)

        if data and "observations" in data and data["observations"]:
            obs = data["observations"][0]
            value_str = obs.get("value", ".")
            value = float(value_str) if value_str != "." else 0.0
            date = obs.get("date", "")
            logger.info(f"FRED {series_id}: {value} ({date})")
            return {"value": value, "date": date, "series_id": series_id}

    except CircuitBreakerError as e:
        logger.warning(f"FRED API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching FRED {series_id}: {e}")

    return {"value": 0.0, "date": "", "series_id": series_id}


async def fetch_coingecko_market(fetcher) -> Dict[str, Any]:
    """Fetch global crypto market data from CoinGecko (free tier).

    Returns:
        Dict with total_market_cap_usd, btc_dominance_pct, active_cryptocurrencies
    """
    try:
        url = f"{COINGECKO_URL}/global"

        async def _fetch():
            return await fetcher._get_with_retry(url)

        data = await _breakers.coingecko_breaker.call(_fetch)

        if data and "data" in data:
            d = data["data"]
            market_cap = d.get("total_market_cap", {}).get("usd", 0)
            btc_dom = d.get("market_cap_percentage", {}).get("btc", 0)
            active = d.get("active_cryptocurrencies", 0)
            logger.info(f"CoinGecko Global: MCap=${market_cap/1e9:.1f}B, BTC Dom={btc_dom:.1f}%")
            return {
                "total_market_cap_usd": market_cap,
                "btc_dominance_pct": btc_dom,
                "active_cryptocurrencies": active,
                "market_cap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd", 0),
            }

    except CircuitBreakerError as e:
        logger.warning(f"CoinGecko API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching CoinGecko market data: {e}")

    return {
        "total_market_cap_usd": 0,
        "btc_dominance_pct": 0,
        "active_cryptocurrencies": 0,
        "market_cap_change_24h_pct": 0,
    }


async def fetch_stablecoin_flows(fetcher) -> Dict[str, Any]:
    """Fetch stablecoin market cap data from DefiLlama.

    Rising USDT market cap = new capital entering crypto (bullish).

    Returns:
        Dict with usdt_market_cap, symbol
    """
    try:
        url = f"{DEFILLAMA_URL}/stablecoins?includePrices=false"

        async def _fetch():
            return await fetcher._get_with_retry(url)

        data = await _breakers.defillama_breaker.call(_fetch)

        if data and "peggedAssets" in data:
            for asset in data["peggedAssets"]:
                if asset.get("symbol", "").upper() == "USDT":
                    chains = asset.get("chainCirculating", {})
                    total_mcap = sum(
                        c.get("current", {}).get("peggedUSD", 0)
                        for c in chains.values()
                    )
                    if total_mcap == 0:
                        total_mcap = asset.get("circulating", {}).get("peggedUSD", 0)

                    logger.info(f"Stablecoin USDT MCap: ${total_mcap / 1e9:.1f}B")
                    return {
                        "usdt_market_cap": total_mcap,
                        "symbol": "USDT",
                    }

    except CircuitBreakerError as e:
        logger.warning(f"DefiLlama API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching stablecoin flows: {e}")

    return {"usdt_market_cap": 0, "symbol": "USDT"}


async def fetch_btc_hashrate(fetcher) -> Dict[str, Any]:
    """Fetch Bitcoin network hashrate from Blockchain.info.

    Rising hashrate = miner confidence, network security.

    Returns:
        Dict with hashrate_ths, difficulty
    """
    try:
        url = f"{BLOCKCHAIN_URL}/stats"

        async def _fetch():
            return await fetcher._get_with_retry(url)

        data = await _breakers.blockchain_breaker.call(_fetch)

        if data:
            hashrate = data.get("hash_rate", 0)
            difficulty = data.get("difficulty", 0)
            logger.info(f"BTC Hashrate: {hashrate / 1e6:.1f} EH/s")
            return {
                "hashrate_ths": hashrate,
                "difficulty": difficulty,
            }

    except CircuitBreakerError as e:
        logger.warning(f"Blockchain.info API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching BTC hashrate: {e}")

    return {"hashrate_ths": 0, "difficulty": 0}
