"""Tests for broadcast message rendering — XSS safety and URL scheme whitelist.

Covers the ``render_messages`` + ``_markdown_to_telegram_html`` helpers in
``src/services/broadcast_service.py``. The regression guarded here is SEC-C1:
admin-supplied markdown used to reach the Telegram HTML without being escaped,
which allowed any downstream HTML renderer (e.g. the admin preview) to execute
injected scripts.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.services.broadcast_service import (
    _markdown_to_telegram_html,
    render_messages,
)


class TestMarkdownToTelegramHtmlEscaping:
    """SEC-C1: body-level HTML escaping."""

    def test_script_tag_is_escaped(self):
        out = _markdown_to_telegram_html("<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
        assert "&lt;/script&gt;" in out

    def test_angle_brackets_in_body_are_escaped(self):
        out = _markdown_to_telegram_html("value < 10 and > 5")
        assert "<" not in out.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "").replace("<a ", "")
        assert "&lt;" in out
        assert "&gt;" in out

    def test_ampersand_is_escaped(self):
        out = _markdown_to_telegram_html("Tom & Jerry")
        assert "&amp;" in out
        # No raw & remaining (except inside entities)
        assert "Tom &amp; Jerry" in out

    def test_double_quote_in_body_is_escaped(self):
        out = _markdown_to_telegram_html('He said "hi"')
        assert "&quot;" in out

    def test_bold_tag_is_preserved_after_escaping(self):
        out = _markdown_to_telegram_html("**important**")
        assert "<b>important</b>" in out

    def test_italic_tag_is_preserved_after_escaping(self):
        out = _markdown_to_telegram_html("*stress*")
        assert "<i>stress</i>" in out


class TestMarkdownLinkUrlWhitelist:
    """SEC-C1: only http(s)/tg schemes allowed; everything else is stripped."""

    def test_javascript_url_is_dropped(self):
        out = _markdown_to_telegram_html("[click me](javascript:alert(1))")
        # No <a> tag, no href, just the visible text
        assert "<a" not in out
        assert "href=" not in out
        assert "javascript" not in out.lower()
        assert "click me" in out

    def test_data_url_is_dropped(self):
        out = _markdown_to_telegram_html("[x](data:text/html,<script>1</script>)")
        assert "<a" not in out
        assert "data:" not in out.lower()

    def test_vbscript_url_is_dropped(self):
        out = _markdown_to_telegram_html("[x](vbscript:msgbox)")
        assert "<a" not in out

    def test_http_url_is_kept(self):
        out = _markdown_to_telegram_html("[site](http://example.com)")
        assert '<a href="http://example.com">site</a>' in out

    def test_https_url_is_kept(self):
        out = _markdown_to_telegram_html("[site](https://example.com)")
        assert '<a href="https://example.com">site</a>' in out

    def test_tg_scheme_is_kept(self):
        out = _markdown_to_telegram_html("[chat](tg://resolve?domain=foo)")
        assert '<a href="tg://resolve?domain=foo">chat</a>' in out

    def test_attribute_breakout_in_url_is_neutralised(self):
        # Attempted breakout with a double-quote inside a (valid-scheme) URL.
        out = _markdown_to_telegram_html('[x](https://a.com" onclick="x)')
        # The injected double-quote must be entity-encoded inside href
        # (no raw `"` may appear between `href=` and the closing tag).
        href_start = out.find('href="')
        assert href_start != -1
        href_end = out.find('"', href_start + 6)  # closing quote of href attr
        href_inner = out[href_start + 6 : href_end]
        # Inside the attribute value there must be NO raw double-quote and
        # NO onclick outside of an entity-encoded form.
        assert '"' not in href_inner
        # The original `"` in the URL must have become &quot; (or &amp;quot;
        # after the double-escape pass); either way it is no longer a
        # structural attribute delimiter.
        assert "&quot;" in out or "&amp;quot;" in out


class TestRenderMessagesSafeTelegramOutput:
    """End-to-end: render_messages() returns an escaped Telegram body."""

    def test_body_with_script_and_js_link_is_safe(self):
        result = render_messages(
            title="Admin Update",
            message_markdown=(
                "<script>alert(1)</script>\n"
                "[evil](javascript:alert(1))\n"
                "[ok](https://example.com)"
            ),
        )
        telegram = result["telegram"]
        # Title survived, but inside <b> after escaping
        assert "<b>Admin Update</b>" in telegram
        # Script tag was neutralised
        assert "<script>" not in telegram
        assert "&lt;script&gt;" in telegram
        # javascript: link was dropped (no <a> for it)
        assert "javascript:" not in telegram.lower()
        # The visible text of the rejected link remained
        assert "evil" in telegram
        # The safe link was kept
        assert '<a href="https://example.com">ok</a>' in telegram
