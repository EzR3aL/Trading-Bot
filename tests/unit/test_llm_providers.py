"""Tests for LLM provider base: parse_llm_response, sanitize_text, sanitize_error, _extract_response_text."""

import pytest

from src.ai.providers.base import (
    _extract_response_text,
    parse_llm_response,
    sanitize_error,
    sanitize_text,
    RateLimiter,
)


# ── parse_llm_response ──────────────────────────────────────────────


class TestParseLlmResponse:
    """Tests for the LLM response parser — the function that decides trade direction."""

    def test_perfect_format(self):
        text = "DIRECTION: LONG\nCONFIDENCE: 85\nREASONING: BTC is bullish."
        d, c, r = parse_llm_response(text)
        assert d == "LONG"
        assert c == 85
        assert "bullish" in r

    def test_perfect_format_short(self):
        text = "DIRECTION: SHORT\nCONFIDENCE: 72\nREASONING: Market is overheated."
        d, c, r = parse_llm_response(text)
        assert d == "SHORT"
        assert c == 72

    def test_case_insensitive(self):
        text = "direction: long\nconfidence: 60\nreasoning: looks good"
        d, c, r = parse_llm_response(text)
        assert d == "LONG"
        assert c == 60

    def test_no_structured_format_defaults_to_zero_confidence(self):
        text = "I think the market will go up."
        d, c, r = parse_llm_response(text)
        assert c == 0  # Default = 0, won't trade

    def test_direction_fallback_count_occurrences(self):
        text = "I recommend SHORT because the SHORT side looks strong. LONG is risky."
        d, c, r = parse_llm_response(text)
        assert d == "SHORT"  # 2 SHORT vs 1 LONG

    def test_direction_fallback_long_wins(self):
        text = "Go LONG LONG LONG. Don't SHORT."
        d, c, r = parse_llm_response(text)
        assert d == "LONG"

    def test_confidence_out_of_range_ignored(self):
        text = "DIRECTION: LONG\nCONFIDENCE: 150\nREASONING: Very sure"
        d, c, r = parse_llm_response(text)
        assert c == 0  # 150 > 100, structured match fails, no fallback match

    def test_confidence_zero_valid(self):
        text = "DIRECTION: LONG\nCONFIDENCE: 0\nREASONING: Not sure at all"
        d, c, r = parse_llm_response(text)
        assert c == 0

    def test_confidence_boundary_100(self):
        text = "DIRECTION: SHORT\nCONFIDENCE: 100\nREASONING: Very confident"
        d, c, r = parse_llm_response(text)
        assert c == 100

    def test_multiline_reasoning(self):
        text = "DIRECTION: LONG\nCONFIDENCE: 65\nREASONING: First reason.\nSecond reason.\nThird."
        d, c, r = parse_llm_response(text)
        assert "First reason" in r
        assert "Second reason" in r

    def test_reasoning_truncated_at_500(self):
        text = "DIRECTION: LONG\nCONFIDENCE: 70\nREASONING: " + "x" * 1000
        d, c, r = parse_llm_response(text)
        assert len(r) <= 500

    def test_empty_string(self):
        d, c, r = parse_llm_response("")
        assert d == "LONG"  # default
        assert c == 0  # default

    def test_extra_whitespace(self):
        text = "  DIRECTION :  LONG  \n  CONFIDENCE :  80  \n  REASONING :  looks ok  "
        d, c, r = parse_llm_response(text)
        assert d == "LONG"
        assert c == 80

    def test_confidence_contextual_fallback(self):
        """When no CONFIDENCE: field, find numbers near confidence-related words."""
        text = "I'm 75% confident this is a LONG trade."
        d, c, r = parse_llm_response(text)
        assert d == "LONG"
        assert c == 75

    def test_price_numbers_not_grabbed_as_confidence(self):
        """Numbers like 98500 (prices) should NOT be grabbed as confidence."""
        text = "BTC is at 98500. I think LONG is the play."
        d, c, r = parse_llm_response(text)
        assert c == 0  # Should not grab 98 or 985
        assert d == "LONG"

    def test_html_in_response_sanitized(self):
        text = "DIRECTION: LONG\nCONFIDENCE: 70\nREASONING: <script>alert('xss')</script> Market bullish"
        d, c, r = parse_llm_response(text)
        assert "<script>" not in r
        assert "alert" in r  # Text content preserved, tags stripped

    def test_markdown_preserved(self):
        text = "DIRECTION: SHORT\nCONFIDENCE: 60\nREASONING: **Strong** bearish signal."
        d, c, r = parse_llm_response(text)
        # Markdown is text, not HTML tags — should be preserved
        assert "Strong" in r


# ── sanitize_text ────────────────────────────────────────────────────


class TestSanitizeText:
    def test_strips_html_tags(self):
        assert sanitize_text("<b>bold</b>") == "bold"

    def test_strips_script_tags(self):
        result = sanitize_text("<script>alert('xss')</script>hello")
        assert "<script>" not in result
        assert "hello" in result

    def test_strips_control_characters(self):
        result = sanitize_text("hello\x00world\x07end")
        assert result == "helloworld\x07end" or "\x00" not in result

    def test_truncates_to_max_length(self):
        result = sanitize_text("a" * 1000, max_length=100)
        assert len(result) <= 100
        assert result.endswith("...")

    def test_preserves_newlines(self):
        result = sanitize_text("line1\nline2")
        assert "\n" in result

    def test_empty_string(self):
        assert sanitize_text("") == ""


# ── sanitize_error ───────────────────────────────────────────────────


class TestSanitizeError:
    def test_strips_bearer_token(self):
        err = Exception("Bearer sk_1234567890abcdef failed")
        result = sanitize_error(err, "Groq")
        assert "sk_1234567890" not in result
        assert "Groq" in result

    def test_strips_key_query_param(self):
        err = Exception("Error at url?key=AIzaSyAbcdefghijklmnopqrstuvwxyz123")
        result = sanitize_error(err, "Gemini")
        assert "AIzaSy" not in result
        assert "Gemini" in result

    def test_extracts_status_code(self):
        err = Exception("API error 401: Invalid API Key")
        result = sanitize_error(err, "Groq")
        assert "401" in result

    def test_no_status_code(self):
        err = Exception("Connection refused")
        result = sanitize_error(err, "OpenAI")
        assert "unknown" in result
        assert "OpenAI" in result


# ── _extract_response_text ───────────────────────────────────────────


class TestExtractResponseText:
    def test_openai_format_valid(self):
        result = {
            "choices": [{"message": {"content": "DIRECTION: LONG"}}],
            "usage": {"total_tokens": 100},
        }
        text, tokens = _extract_response_text(result, "groq")
        assert text == "DIRECTION: LONG"
        assert tokens == 100

    def test_openai_format_empty_choices(self):
        with pytest.raises(ValueError, match="empty choices"):
            _extract_response_text({"choices": []}, "openai")

    def test_openai_format_no_choices_key(self):
        with pytest.raises(ValueError, match="empty choices"):
            _extract_response_text({}, "mistral")

    def test_openai_format_empty_content(self):
        result = {"choices": [{"message": {"content": ""}}]}
        with pytest.raises(ValueError, match="empty text"):
            _extract_response_text(result, "groq")

    def test_gemini_format_valid(self):
        result = {
            "candidates": [{"content": {"parts": [{"text": "DIRECTION: SHORT"}]}}],
            "usageMetadata": {"totalTokenCount": 50},
        }
        text, tokens = _extract_response_text(result, "gemini")
        assert text == "DIRECTION: SHORT"
        assert tokens == 50

    def test_gemini_format_empty_candidates(self):
        with pytest.raises(ValueError, match="empty candidates"):
            _extract_response_text({"candidates": []}, "gemini")

    def test_gemini_format_empty_parts(self):
        result = {"candidates": [{"content": {"parts": []}}]}
        with pytest.raises(ValueError, match="empty content parts"):
            _extract_response_text(result, "gemini")

    def test_anthropic_format_valid(self):
        result = {
            "content": [{"text": "DIRECTION: LONG\nCONFIDENCE: 90"}],
            "usage": {"input_tokens": 30, "output_tokens": 20},
        }
        text, tokens = _extract_response_text(result, "anthropic")
        assert "DIRECTION: LONG" in text
        assert tokens == 50

    def test_anthropic_format_empty_content(self):
        with pytest.raises(ValueError, match="empty content"):
            _extract_response_text({"content": []}, "anthropic")


# ── RateLimiter ──────────────────────────────────────────────────────


class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter(max_calls_per_hour=5)
        for _ in range(5):
            assert rl.check("test") is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_calls_per_hour=3)
        assert rl.check("test") is True
        assert rl.check("test") is True
        assert rl.check("test") is True
        assert rl.check("test") is False
