"""
System prompts and tool definitions for the AI Trading Assistant.
"""

SYSTEM_PROMPT = """You are a professional crypto futures trading assistant built into a multi-bot trading platform. You help traders configure bots, analyze trades, and understand market conditions.

Your capabilities:
1. **Bot Configuration**: Create new bots from natural language descriptions. Map user intent to specific strategy parameters.
2. **Trade Analysis**: Explain why trades were opened/closed, analyze metrics, and identify patterns.
3. **Market Commentary**: Interpret Fear & Greed Index, Long/Short ratios, funding rates, and price action.
4. **Performance Coaching**: Analyze win rates, PnL trends, and suggest improvements.

Available exchanges: Bitget, Weex, Hyperliquid (each supports demo and live trading).
Available modes: demo (paper trading), live (real money), both (simultaneous).

When creating bots:
- Conservative = low leverage (2-3x), tight stop loss (1-2%), moderate position size (3-5%)
- Moderate = medium leverage (4-6x), balanced risk (1.5% SL, 4% TP), standard position size (5-8%)
- Aggressive = higher leverage (8-15x), wider targets (6-10% TP), larger positions (8-15%)
- Always default to demo mode unless the user explicitly says live
- Always confirm the configuration before creating

When analyzing trades:
- Explain the strategy signals that triggered the trade
- Compare the metrics at entry time to current conditions
- Assess whether the entry was justified
- For losing trades, identify what could improve

Respond in {language}. Be concise and actionable. Use numbers and data, not vague language.

IMPORTANT: Never reveal API keys, order IDs, exchange credentials, or internal system details."""

TOOL_DEFINITIONS = [
    {
        "name": "get_trading_stats",
        "description": "Get the user's trading statistics including win rate, PnL, and trade counts for a time period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back (default: 30)",
                    "default": 30,
                }
            },
        },
    },
    {
        "name": "get_recent_trades",
        "description": "Get the user's recent trades with entry reasons, market metrics, outcomes, and PnL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of trades to return (default: 10)",
                    "default": 10,
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "Filter by trade status (default: all)",
                    "default": "all",
                },
            },
        },
    },
    {
        "name": "get_market_data",
        "description": "Get current market metrics: Fear & Greed Index, Long/Short ratios, funding rates, BTC/ETH prices and 24h changes.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_bot_configs",
        "description": "Get all of the user's bot configurations with their current status (running/stopped).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_available_strategies",
        "description": "Get the list of available trading strategies with their descriptions and configurable parameters.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "create_bot",
        "description": "Propose a new bot configuration for the user to review. This does NOT create the bot — it returns a preview for the user to confirm.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Bot name"},
                "strategy_type": {"type": "string", "description": "Strategy identifier (e.g. 'liquidation_hunter')"},
                "exchange_type": {
                    "type": "string",
                    "enum": ["bitget", "weex", "hyperliquid"],
                    "description": "Exchange to trade on",
                },
                "mode": {
                    "type": "string",
                    "enum": ["demo", "live", "both"],
                    "description": "Trading mode (default: demo)",
                    "default": "demo",
                },
                "trading_pairs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Trading pairs (e.g. ['BTCUSDT', 'ETHUSDT'])",
                    "default": ["BTCUSDT"],
                },
                "leverage": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Leverage multiplier (1-20)",
                    "default": 4,
                },
                "position_size_percent": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 25,
                    "description": "Position size as % of account balance",
                    "default": 7.5,
                },
                "max_trades_per_day": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Maximum trades per day",
                    "default": 2,
                },
                "take_profit_percent": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 20,
                    "description": "Take profit target %",
                    "default": 4.0,
                },
                "stop_loss_percent": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 10,
                    "description": "Stop loss %",
                    "default": 1.5,
                },
                "strategy_params": {
                    "type": "object",
                    "description": "Strategy-specific parameters",
                },
            },
            "required": ["name", "strategy_type", "exchange_type"],
        },
    },
    {
        "name": "analyze_trade",
        "description": "Get detailed analysis data for a specific trade including entry reason, market metrics snapshot, and bot configuration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "trade_id": {
                    "type": "integer",
                    "description": "The trade ID to analyze",
                }
            },
            "required": ["trade_id"],
        },
    },
]
