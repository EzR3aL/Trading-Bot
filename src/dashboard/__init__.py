"""
Web Dashboard for the Bitget Trading Bot.

Provides a real-time web interface for:
- Monitoring open positions
- Viewing trade history
- Analyzing performance metrics
- Configuring bot settings
"""

from src.dashboard.app import create_app, run_dashboard

__all__ = ["create_app", "run_dashboard"]
