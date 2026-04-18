"""Live integration tests against real exchange demo APIs.

These tests talk to real exchange demo endpoints and are intentionally
gated by the ``bitget_live`` pytest marker plus the ``BITGET_LIVE_TEST_USER_ID``
env var. They never run in default CI.
"""
