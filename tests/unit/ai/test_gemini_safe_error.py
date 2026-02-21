"""
Targeted tests for gemini.py _safe_error (lines 27-29).

Covers:
- API key redaction from error messages
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class TestGeminiSafeError:
    def test_redacts_api_key_from_error(self):
        """_safe_error strips API key and returns sanitized Gemini message."""
        from src.ai.providers.gemini import GeminiProvider

        provider = GeminiProvider(api_key="test-key")
        error = Exception(
            "Connection error: https://api.google.com?key=AIzaSyD1234567890abcdef"
        )
        result = provider._safe_error(error)
        assert "AIzaSyD1234567890abcdef" not in result
        assert "Gemini" in result

    def test_handles_error_without_key(self):
        """_safe_error works with errors that don't contain API keys."""
        from src.ai.providers.gemini import GeminiProvider

        provider = GeminiProvider(api_key="test-key")
        error = Exception("Simple timeout error")
        result = provider._safe_error(error)
        assert "Gemini" in result

    def test_error_with_status_code(self):
        """_safe_error extracts status code from error message."""
        from src.ai.providers.gemini import GeminiProvider

        provider = GeminiProvider(api_key="test-key")
        error = Exception("HTTP 403 Forbidden: key=AIzaSyD1234567890abcdef invalid")
        result = provider._safe_error(error)
        assert "AIzaSyD1234567890abcdef" not in result
        assert "403" in result
