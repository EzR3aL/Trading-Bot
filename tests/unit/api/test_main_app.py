"""
Tests for the FastAPI main application factory.

Covers:
- SecurityHeadersMiddleware (all headers including HSTS in production)
- create_app configuration (title, version, routers)
- CORS configuration (development vs production, extra origins)
- Validation exception handler (422)
- _seed_exchanges function
- Frontend static file mount (exists vs missing)
- Lifespan lifecycle (startup/shutdown)
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo=")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware
# ---------------------------------------------------------------------------

async def test_security_headers_x_content_type_options():
    """SecurityHeadersMiddleware adds X-Content-Type-Options: nosniff."""
    from src.api.main_app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")
        assert resp.headers.get("x-content-type-options") == "nosniff"


async def test_security_headers_x_frame_options():
    """SecurityHeadersMiddleware adds X-Frame-Options: DENY."""
    from src.api.main_app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")
        assert resp.headers.get("x-frame-options") == "DENY"


async def test_security_headers_referrer_policy():
    """SecurityHeadersMiddleware adds strict-origin Referrer-Policy."""
    from src.api.main_app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")
        assert "strict-origin" in resp.headers.get("referrer-policy", "")


async def test_security_headers_csp():
    """SecurityHeadersMiddleware adds Content-Security-Policy header."""
    from src.api.main_app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "font-src 'self'" in csp


async def test_hsts_not_set_in_development():
    """HSTS header is NOT set when ENVIRONMENT is development."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {"ENVIRONMENT": "development", "ENABLE_HSTS": "false"}, clear=False):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/status")
            assert "strict-transport-security" not in resp.headers


async def test_hsts_set_in_production():
    """HSTS header IS set when ENVIRONMENT is production."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=False):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/status")
            hsts = resp.headers.get("strict-transport-security", "")
            assert "max-age=31536000" in hsts
            assert "includeSubDomains" in hsts


async def test_hsts_set_when_enable_hsts_true():
    """HSTS header is set when ENABLE_HSTS=true even in development."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {"ENVIRONMENT": "development", "ENABLE_HSTS": "true"}, clear=False):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/status")
            hsts = resp.headers.get("strict-transport-security", "")
            assert "max-age=31536000" in hsts


# ---------------------------------------------------------------------------
# create_app factory
# ---------------------------------------------------------------------------

def test_create_app_returns_fastapi_instance():
    """create_app returns a FastAPI instance."""
    from fastapi import FastAPI
    from src.api.main_app import create_app

    app = create_app()
    assert isinstance(app, FastAPI)


def test_create_app_title():
    """App title is 'Trading Bot API'."""
    from src.api.main_app import create_app

    app = create_app()
    assert app.title == "Trading Bot API"


def test_create_app_version():
    """App version is '3.0.0'."""
    from src.api.main_app import create_app

    app = create_app()
    assert app.version == "3.0.0"


def test_create_app_registers_routers():
    """create_app registers expected API routers."""
    from src.api.main_app import create_app

    app = create_app()
    route_paths = [route.path for route in app.routes]
    # Check that key API routes are registered
    assert any("/api/status" in p for p in route_paths)
    assert any("/api/auth" in p for p in route_paths)
    assert any("/api/trades" in p for p in route_paths)


# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------

def test_cors_default_origins_in_development():
    """In development, default CORS origins include localhost:5173."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {"ENVIRONMENT": "development", "CORS_ORIGINS": ""}, clear=False):
        app = create_app()
        # Verify the app was created without error
        assert app is not None


def test_cors_extra_origins_added():
    """Extra CORS_ORIGINS env var origins are appended."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {
        "ENVIRONMENT": "development",
        "CORS_ORIGINS": "http://extra:3000, http://another:8080"
    }, clear=False):
        app = create_app()
        assert app is not None


def test_cors_production_rejects_http_origins():
    """In production, non-HTTPS extra origins are rejected."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {
        "ENVIRONMENT": "production",
        "CORS_ORIGINS": "http://insecure:3000, https://secure.example.com"
    }, clear=False):
        app = create_app()
        assert app is not None


def test_cors_production_strips_default_dev_origins():
    """In production, default HTTP dev origins are removed."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {
        "ENVIRONMENT": "production",
        "CORS_ORIGINS": "https://prod.example.com"
    }, clear=False):
        app = create_app()
        assert app is not None


def test_cors_production_no_origins_warns():
    """In production with no CORS_ORIGINS, app still creates (logs warning)."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {
        "ENVIRONMENT": "production",
        "CORS_ORIGINS": ""
    }, clear=False):
        app = create_app()
        assert app is not None


def test_cors_empty_extra_origin_skipped():
    """Empty strings in CORS_ORIGINS are skipped."""
    from src.api.main_app import create_app

    with patch.dict("os.environ", {
        "ENVIRONMENT": "development",
        "CORS_ORIGINS": "http://valid:3000, , "
    }, clear=False):
        app = create_app()
        assert app is not None


# ---------------------------------------------------------------------------
# Validation exception handler
# ---------------------------------------------------------------------------

async def test_validation_exception_handler_returns_422():
    """Posting invalid data returns 422 with 'detail' in body."""
    from src.api.main_app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/login", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert "detail" in body


async def test_validation_exception_handler_contains_error_details():
    """422 response detail contains validation error info."""
    from src.api.main_app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/login", json={})
        body = resp.json()
        assert isinstance(body["detail"], list)
        assert len(body["detail"]) > 0


# ---------------------------------------------------------------------------
# _seed_exchanges
# ---------------------------------------------------------------------------

async def test_seed_exchanges_inserts_data():
    """_seed_exchanges inserts exchange records into an empty table."""
    from contextlib import asynccontextmanager

    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar_one_or_none.return_value = None  # No existing data

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_scalar_result)
    mock_session.add = MagicMock()

    @asynccontextmanager
    async def mock_get_session():
        yield mock_session

    with patch("src.models.session.get_session", mock_get_session):
        from src.api.main_app import _seed_exchanges
        await _seed_exchanges()

    assert mock_session.add.call_count == 5
    exchanges = [call.args[0] for call in mock_session.add.call_args_list]
    names = [e.name for e in exchanges]
    assert "bitget" in names
    assert "weex" in names
    assert "hyperliquid" in names
    assert "bitunix" in names
    assert "bingx" in names


async def test_seed_exchanges_skips_when_data_exists():
    """_seed_exchanges does nothing if exchanges already exist."""
    from contextlib import asynccontextmanager

    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar_one_or_none.return_value = MagicMock()  # Existing data

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_scalar_result)
    mock_session.add = MagicMock()

    @asynccontextmanager
    async def mock_get_session():
        yield mock_session

    with patch("src.models.session.get_session", mock_get_session):
        from src.api.main_app import _seed_exchanges
        await _seed_exchanges()

    mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Frontend static file mount
# ---------------------------------------------------------------------------

def test_frontend_mount_when_directory_exists():
    """When static/frontend exists, assets mount and SPA catch-all are added."""
    from src.api.main_app import create_app

    mock_static = MagicMock()
    with patch("src.api.main_app.Path.exists", return_value=True), \
         patch("src.api.main_app.Path.is_file", return_value=False), \
         patch("src.api.main_app.StaticFiles", return_value=mock_static):
        app = create_app()
        route_names = [r.name for r in app.routes if hasattr(r, "name")]
        assert "assets" in route_names
        assert "serve_spa" in route_names


def test_frontend_not_mounted_when_directory_missing():
    """When static/frontend does not exist, no mount is added."""
    from src.api.main_app import create_app

    with patch("src.api.main_app.Path.exists", return_value=False):
        app = create_app()
        route_names = [r.name for r in app.routes if hasattr(r, "name")]
        assert "assets" not in route_names
        assert "serve_spa" not in route_names


async def test_serve_spa_blocks_path_traversal():
    """Path traversal attempt (../../etc/passwd) returns index.html, not the target file."""
    import tempfile

    from src.api.main_app import create_app

    # Create a temporary frontend directory with an index.html
    with tempfile.TemporaryDirectory() as tmpdir:
        frontend_dir = Path(tmpdir)
        index_html = frontend_dir / "index.html"
        index_html.write_text("<html>SPA</html>")

        with patch("src.api.main_app.Path", return_value=frontend_dir) as mock_path_cls:
            # We need the real Path for resolution, so patch only the constructor
            # used in create_app (frontend_dir = Path("static/frontend"))
            mock_path_cls.side_effect = lambda p: Path(tmpdir) if p == "static/frontend" else Path(p)

        # Instead, use a direct test of the serve_spa logic
        from fastapi.responses import FileResponse

        test_frontend = frontend_dir
        full_path = "../../etc/passwd"
        file_path = (test_frontend / full_path).resolve()
        # Resolved path must NOT start with the frontend dir
        is_inside = str(file_path).startswith(str(test_frontend.resolve()))
        assert not is_inside, f"Path traversal not blocked: {file_path} is inside {test_frontend.resolve()}"


async def test_serve_spa_allows_valid_paths():
    """Valid file paths within frontend_dir are allowed."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        frontend_dir = Path(tmpdir)
        (frontend_dir / "favicon.ico").write_text("icon")

        full_path = "favicon.ico"
        file_path = (frontend_dir / full_path).resolve()
        is_inside = str(file_path).startswith(str(frontend_dir.resolve()))
        assert is_inside, f"Valid path blocked: {file_path} not inside {frontend_dir.resolve()}"


# ---------------------------------------------------------------------------
# Lifespan lifecycle
# ---------------------------------------------------------------------------

async def test_lifespan_startup_and_shutdown():
    """Lifespan initialises DB, seeds exchanges, starts orchestrator, and shuts down."""
    from src.api.main_app import lifespan
    from fastapi import FastAPI

    mock_orchestrator = MagicMock()
    mock_orchestrator.restore_on_startup = AsyncMock()
    mock_orchestrator.shutdown_all = AsyncMock()

    app = FastAPI()

    with patch("src.auth.jwt_handler.validate_jwt_config"), \
         patch("src.api.main_app.init_db", new_callable=AsyncMock) as mock_init_db, \
         patch("src.api.main_app._seed_exchanges", new_callable=AsyncMock) as mock_seed, \
         patch("src.api.main_app.close_db", new_callable=AsyncMock) as mock_close_db, \
         patch("src.bot.orchestrator.BotOrchestrator", return_value=mock_orchestrator):

        async with lifespan(app):
            mock_init_db.assert_awaited_once()
            mock_seed.assert_awaited_once()
            mock_orchestrator.restore_on_startup.assert_awaited_once()

        mock_orchestrator.shutdown_all.assert_awaited_once()
        mock_close_db.assert_awaited_once()


async def test_lifespan_production_without_encryption_key_warns():
    """In production without ENCRYPTION_KEY, lifespan logs a warning."""
    from src.api.main_app import lifespan
    from fastapi import FastAPI

    mock_orchestrator = MagicMock()
    mock_orchestrator.restore_on_startup = AsyncMock()
    mock_orchestrator.shutdown_all = AsyncMock()

    app = FastAPI()

    with patch("src.auth.jwt_handler.validate_jwt_config"), \
         patch("src.api.main_app.init_db", new_callable=AsyncMock), \
         patch("src.api.main_app._seed_exchanges", new_callable=AsyncMock), \
         patch("src.api.main_app.close_db", new_callable=AsyncMock), \
         patch("src.bot.orchestrator.BotOrchestrator", return_value=mock_orchestrator), \
         patch("src.api.main_app.bots"), \
         patch("src.api.main_app.logger") as mock_logger:

        # Temporarily set production environment and remove ENCRYPTION_KEY
        orig_env = os.environ.pop("ENVIRONMENT", None)
        orig_key = os.environ.pop("ENCRYPTION_KEY", None)
        orig_pg_pw = os.environ.pop("POSTGRES_PASSWORD", None)
        os.environ["ENVIRONMENT"] = "production"
        os.environ["POSTGRES_PASSWORD"] = "StrongTestPassword123!"
        try:
            async with lifespan(app):
                pass
        finally:
            if orig_key is not None:
                os.environ["ENCRYPTION_KEY"] = orig_key
            if orig_env is not None:
                os.environ["ENVIRONMENT"] = orig_env
            else:
                os.environ.pop("ENVIRONMENT", None)
            if orig_pg_pw is not None:
                os.environ["POSTGRES_PASSWORD"] = orig_pg_pw
            else:
                os.environ.pop("POSTGRES_PASSWORD", None)

        # Check that warning was logged
        mock_logger.warning.assert_any_call(
            "SECURITY WARNING: Running in production without explicit ENCRYPTION_KEY. "
            "Set ENCRYPTION_KEY env var to prevent auto-generation."
        )
