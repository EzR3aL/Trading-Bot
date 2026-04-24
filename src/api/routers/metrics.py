"""Prometheus metrics endpoint (#327 PR-1).

The endpoint is flag-gated by ``PROMETHEUS_ENABLED`` (via
``config.feature_flags``). When the flag is off the endpoint returns
**404** — not 403 — so that its mere existence is not leaked to the
public internet.

When the flag is on the endpoint requires HTTP Basic-Auth with
credentials from the environment:

* ``METRICS_BASIC_AUTH_USER``
* ``METRICS_BASIC_AUTH_PASSWORD``

Credential comparison uses ``secrets.compare_digest`` so timing cannot
leak whether the user or password was the field that mismatched. A
missing or malformed ``Authorization`` header returns 401 with a
``WWW-Authenticate: Basic`` challenge; wrong credentials also return
401 for the same reason.

The rendered body is the Prometheus text exposition format of the
observability ``REGISTRY`` defined in
``src/observability/metrics.py``.

Operators who need additional network-level hardening (e.g. IP allow-
list, mTLS) should still run Prometheus on the internal Docker network
and front the endpoint with Nginx / Traefik — the Basic-Auth gate is
the last line of defence, not the only one. (#327 security notes.)
"""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

router = APIRouter(tags=["monitoring"])

_basic_auth = HTTPBasic(auto_error=False)


def _is_prometheus_enabled() -> bool:
    """Read ``PROMETHEUS_ENABLED`` through the feature-flag registry.

    Imported lazily so test code can monkey-patch
    ``config.settings.settings.monitoring.prometheus_enabled`` at runtime
    without having to reimport this module.
    """
    from config.feature_flags import feature_flags

    return feature_flags.get("prometheus_enabled")


def _load_expected_credentials() -> tuple[str, str] | None:
    """Return the configured Basic-Auth credentials or ``None``.

    The values are read from the environment on every request so that
    ``monkeypatch.setenv`` works in tests without juggling module-level
    caches. When either env var is missing or empty we return ``None``,
    which the endpoint treats as "Basic-Auth is mandatory but no
    credentials are configured" → 401.
    """
    user = os.getenv("METRICS_BASIC_AUTH_USER", "")
    password = os.getenv("METRICS_BASIC_AUTH_PASSWORD", "")
    if not user or not password:
        return None
    return user, password


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": 'Basic realm="metrics"'},
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_basic_auth),
) -> Response:
    """Serve Prometheus-formatted metrics.

    * Flag OFF → 404 (existence not leaked).
    * Flag ON, missing/malformed Authorization header → 401.
    * Flag ON, wrong credentials → 401.
    * Flag ON, correct credentials → 200 + text/plain exposition body.
    """
    if not _is_prometheus_enabled():
        raise _not_found()

    expected = _load_expected_credentials()
    if expected is None or credentials is None:
        raise _unauthorized()

    expected_user, expected_password = expected
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), expected_user.encode("utf-8")
    )
    pw_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), expected_password.encode("utf-8")
    )
    # Always evaluate both comparisons to keep the branch timing symmetric.
    if not (user_ok and pw_ok):
        raise _unauthorized()

    # Import lazily so the module can be imported without prometheus_client
    # being available in every tooling context.
    from src.observability.metrics import CONTENT_TYPE_LATEST, render_latest

    return Response(content=render_latest(), media_type=CONTENT_TYPE_LATEST)
