"""Fear & Greed Index data source (Alternative.me API)."""

from typing import Tuple

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

logger = get_logger(__name__)

FEAR_GREED_URL = "https://api.alternative.me/fng/"


async def fetch_fear_greed(fetcher) -> Tuple[int, str]:
    """Fetch the current Fear & Greed Index from Alternative.me.

    Args:
        fetcher: Object with _get_with_retry method (HttpMixin)

    Returns:
        Tuple of (index value 0-100, classification string)
    """
    try:
        async def _fetch():
            return await fetcher._get_with_retry(FEAR_GREED_URL, {"limit": "1"})

        data = await _breakers.alternative_me_breaker.call(_fetch)

        if data and "data" in data and len(data["data"]) > 0:
            fng_data = data["data"][0]
            value = int(fng_data.get("value", 50))
            classification = fng_data.get("value_classification", "Neutral")

            logger.info(f"Fear & Greed Index: {value} ({classification})")
            return value, classification

    except CircuitBreakerError as e:
        logger.warning(f"Fear & Greed API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching Fear & Greed Index: {e}")

    # Return neutral on error
    return 50, "Neutral"
