"""Circuit breaker instances for all external API data sources.

Centralized so they can be imported by both source modules and the facade,
keeping test patch targets stable at src.data.market_data._X_breaker.
"""

from src.utils.circuit_breaker import circuit_registry

# Binance (Futures + Spot)
binance_breaker = circuit_registry.get("binance_api", fail_threshold=5, reset_timeout=60)

# Alternative.me (Fear & Greed)
alternative_me_breaker = circuit_registry.get("alternative_me_api", fail_threshold=3, reset_timeout=120)

# GDELT (News Sentiment)
gdelt_breaker = circuit_registry.get("gdelt_api", fail_threshold=5, reset_timeout=120)

# Deribit (Options)
deribit_breaker = circuit_registry.get("deribit_api", fail_threshold=3, reset_timeout=120)

# CoinGecko
coingecko_breaker = circuit_registry.get("coingecko_api", fail_threshold=3, reset_timeout=120)

# DefiLlama
defillama_breaker = circuit_registry.get("defillama_api", fail_threshold=3, reset_timeout=120)

# Blockchain.info
blockchain_breaker = circuit_registry.get("blockchain_api", fail_threshold=3, reset_timeout=120)

# Bitget
bitget_breaker = circuit_registry.get("bitget_api", fail_threshold=3, reset_timeout=120)

# FRED (Federal Reserve Economic Data)
fred_breaker = circuit_registry.get("fred_api", fail_threshold=3, reset_timeout=300)

# Coinbase
coinbase_breaker = circuit_registry.get("coinbase_api", fail_threshold=3, reset_timeout=120)

# Bybit
bybit_breaker = circuit_registry.get("bybit_api", fail_threshold=3, reset_timeout=120)
