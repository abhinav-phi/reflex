"""Connector errors — executor failure handling (F3, Rules §9.2)."""

from __future__ import annotations


class ConnectorError(Exception):
    """Base class; executors park the action on this."""


class ConfigError(ConnectorError):
    """Missing/invalid configuration (e.g., no test-mode keys). Fail-closed."""


class TestModeViolation(ConfigError):
    """A non-rzp_test_ key was supplied. Live keys are forbidden (Rules §1.7)."""


class RazorpayTimeout(ConnectorError):
    """RP-TM API timed out after retries → action parks (AppFlow §11)."""


class RazorpayHTTPError(ConnectorError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"razorpay http {status_code}: {body[:200]}")
        self.status_code = status_code
