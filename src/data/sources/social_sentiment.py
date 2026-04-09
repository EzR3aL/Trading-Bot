"""News and social sentiment data (GDELT Project)."""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from src.utils.logger import get_logger
from src.utils.circuit_breaker import CircuitBreakerError
from src.data.sources import breakers as _breakers

logger = get_logger(__name__)

GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


async def fetch_news_sentiment(
    fetcher, query: str = "bitcoin", lookback_hours: int = 12, max_records: int = 10
) -> Dict[str, Any]:
    """Fetch news sentiment from GDELT Project API.

    Focused query + low maxrecords for faster response times.
    GDELT scales response time linearly with record count.

    Returns:
        Dict with average_tone (-10 to +10), article_count
    """
    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=lookback_hours)

        params = {
            "query": query,
            "startdatetime": start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": now.strftime("%Y%m%d%H%M%S"),
            "format": "json",
            "mode": "tonechart",
            "maxrecords": str(max_records),
        }

        async def _fetch():
            return await fetcher._get_with_retry(GDELT_API_URL, params, timeout=10)

        data = await _breakers.gdelt_breaker.call(_fetch)

        if data and "tonechart" in data:
            tones = data["tonechart"]
            if tones:
                tone_values = [float(t.get("tone", 0)) for t in tones if "tone" in t]
                if tone_values:
                    avg_tone = sum(tone_values) / len(tone_values)
                    logger.info(f"News Sentiment ({query[:30]}): tone={avg_tone:.2f}, articles={len(tone_values)}")
                    return {"average_tone": avg_tone, "article_count": len(tone_values)}

    except CircuitBreakerError as e:
        logger.warning(f"GDELT API circuit open: {e}")
    except Exception as e:
        logger.error(f"Error fetching news sentiment: {e}")

    return {"average_tone": 0.0, "article_count": 0}
