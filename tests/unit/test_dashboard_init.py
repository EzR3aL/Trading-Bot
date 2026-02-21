"""Tests for dashboard __init__.py module."""

from unittest.mock import patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestRunDashboard:
    """Tests for the run_dashboard function."""

    def test_calls_uvicorn_with_defaults(self):
        with patch("uvicorn.run") as mock_run, \
             patch("src.api.main_app.app", new=MagicMock()) as mock_app:
            from src.dashboard import run_dashboard
            run_dashboard()
            mock_run.assert_called_once_with(mock_app, host="0.0.0.0", port=8080)

    def test_calls_uvicorn_with_custom_host_port(self):
        with patch("uvicorn.run") as mock_run, \
             patch("src.api.main_app.app", new=MagicMock()) as mock_app:
            from src.dashboard import run_dashboard
            run_dashboard(host="127.0.0.1", port=3000)
            mock_run.assert_called_once_with(mock_app, host="127.0.0.1", port=3000)
