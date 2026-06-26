"""Token bucket rate limiter — OL MCP variant.

Hardening item H5 (2026-06-20). Thread-safe token bucket.
Configured via environment variables:

- OMNI_RATE_LIMIT_RPM: requests per minute (default: 60, 0 = disabled)
- OMNI_RATE_LIMIT_BURST: max burst size (default: 10)
"""

from __future__ import annotations

import os
import threading
import time

__all__ = ["TokenBucket", "check_rate_limit", "rate_limit_failure_response"]


class TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rpm: int = 60, burst: int = 10) -> None:
        if rpm < 0:
            rpm = 0
        if burst < 1:
            burst = 1
        self.rate: float = rpm / 60.0
        self.burst: int = burst
        self.tokens: float = float(burst)
        self.last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(float(self.burst), self.tokens + elapsed * self.rate)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        if self.rate <= 0:
            return True
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    @property
    def wait_seconds(self) -> float:
        if self.rate <= 0:
            return 0.0
        with self._lock:
            self._refill()
            if self.tokens >= 1.0:
                return 0.0
            return (1.0 - self.tokens) / self.rate


_bucket: TokenBucket | None = None


def check_rate_limit() -> tuple[bool, str | None]:
    """Check rate limit using env-var-configured defaults.

    Returns (True, None) if allowed, (False, error_message) if limited.
    """
    global _bucket
    if _bucket is None:
        rpm = int(os.environ.get("OMNI_RATE_LIMIT_RPM", "60"))
        burst = int(os.environ.get("OMNI_RATE_LIMIT_BURST", "10"))
        _bucket = TokenBucket(rpm=rpm, burst=burst)
    if not _bucket.consume():
        return False, "RATE_LIMITED: too many requests."
    return True, None


def rate_limit_failure_response() -> dict:
    return {
        "success": False,
        "error": {"code": "RATE_LIMITED", "message": "Rate limit exceeded."},
        "error_code": "RATE_LIMITED",
        "message": "Rate limit exceeded.",
    }
