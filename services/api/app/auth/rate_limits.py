"""Rate limits for sign-up and sign-in.

Every account starts with virtual cash, so unlimited sign-ups would let one person run many
accounts to push a player's price around. Sign-in is limited to slow down password guessing:
per client address for every attempt, and per email address for failed attempts only, so a
person's own successful logins never lock them out.

Counts live in Redis in fixed windows. If Redis cannot be reached the limiter lets requests
through rather than locking everyone out of their accounts.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import redis
from fastapi import Request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimit:
    name: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class AuthRateLimits:
    register_per_address: RateLimit
    login_per_address: RateLimit
    failed_logins_per_email: RateLimit

    @classmethod
    def from_env(cls) -> "AuthRateLimits":
        return cls(
            register_per_address=RateLimit(
                "register-address", _int_env("STOCKBALL_AUTH_REGISTER_LIMIT_PER_HOUR", 5), 3600
            ),
            login_per_address=RateLimit(
                "login-address", _int_env("STOCKBALL_AUTH_LOGIN_LIMIT_PER_15_MINUTES", 30), 900
            ),
            failed_logins_per_email=RateLimit(
                "login-email-failures",
                _int_env("STOCKBALL_AUTH_FAILED_LOGIN_LIMIT_PER_15_MINUTES", 10),
                900,
            ),
        )


class RateLimitExceededError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too many attempts")
        self.retry_after_seconds = retry_after_seconds


class RateLimiter(Protocol):
    def check(self, rule: RateLimit, key: str) -> None:
        """Raises RateLimitExceededError if `key` has used up `rule`, without counting."""

    def hit(self, rule: RateLimit, key: str) -> None:
        """Counts one attempt, raising RateLimitExceededError if it goes over `rule`."""


class RedisRateLimiter:
    def __init__(self, redis_url: str, clock: Callable[[], float] = time.time) -> None:
        # redis-py's sync and async overloads are indistinguishable to static checkers.
        self._client: Any = redis.Redis.from_url(
            redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        self._clock = clock

    def check(self, rule: RateLimit, key: str) -> None:
        if rule.limit <= 0:
            return
        window_key, retry_after = self._window(rule, key)
        try:
            count = int(self._client.get(window_key) or 0)
        except redis.RedisError:
            logger.warning("rate limit store unavailable; allowing request", exc_info=True)
            return
        if count >= rule.limit:
            raise RateLimitExceededError(retry_after)

    def hit(self, rule: RateLimit, key: str) -> None:
        if rule.limit <= 0:
            return
        window_key, retry_after = self._window(rule, key)
        try:
            pipeline = self._client.pipeline()
            pipeline.incr(window_key)
            pipeline.expire(window_key, rule.window_seconds)
            count = int(pipeline.execute()[0])
        except redis.RedisError:
            logger.warning("rate limit store unavailable; allowing request", exc_info=True)
            return
        if count > rule.limit:
            raise RateLimitExceededError(retry_after)

    def _window(self, rule: RateLimit, key: str) -> tuple[str, int]:
        now = self._clock()
        window = int(now // rule.window_seconds)
        retry_after = max(1, math.ceil((window + 1) * rule.window_seconds - now))
        digest = hashlib.sha256(key.encode()).hexdigest()[:32]
        return f"stockball:ratelimit:{rule.name}:{window}:{digest}", retry_after


class InMemoryRateLimiter:
    """A single-process limiter for tests and local runs without Redis."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._counts: dict[tuple[str, int, str], int] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def check(self, rule: RateLimit, key: str) -> None:
        if rule.limit <= 0:
            return
        bucket, retry_after = self._bucket(rule, key)
        with self._lock:
            if self._counts.get(bucket, 0) >= rule.limit:
                raise RateLimitExceededError(retry_after)

    def hit(self, rule: RateLimit, key: str) -> None:
        if rule.limit <= 0:
            return
        bucket, retry_after = self._bucket(rule, key)
        with self._lock:
            self._counts[bucket] = self._counts.get(bucket, 0) + 1
            if self._counts[bucket] > rule.limit:
                raise RateLimitExceededError(retry_after)

    def _bucket(self, rule: RateLimit, key: str) -> tuple[tuple[str, int, str], int]:
        now = self._clock()
        window = int(now // rule.window_seconds)
        retry_after = max(1, math.ceil((window + 1) * rule.window_seconds - now))
        return (rule.name, window, key), retry_after


def client_address(request: Request) -> str:
    """The address a request came from.

    The API is reached through the web server, which passes the visitor's address in
    X-Forwarded-For. That header is only trusted from a private or loopback peer, so a client
    talking to the API directly cannot pick its own address.
    """
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and _is_internal(peer):
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return peer or "unknown"


def _is_internal(address: str) -> bool:
    if address in {"testclient", "localhost"}:
        return True
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_private or parsed.is_loopback


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default
