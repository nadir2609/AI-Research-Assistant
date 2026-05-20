from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping, TypeVar

from ai.providers.base import ProviderError

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    rate_per_second: float
    burst: int = 1


class TokenBucket:
    """Simple async token bucket limiter."""

    def __init__(self, rate_per_second: float, burst: int = 1) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive.")
        if burst < 1:
            raise ValueError("burst must be >= 1.")
        self._rate = rate_per_second
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        if tokens <= 0:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                if elapsed > 0:
                    self._tokens = min(
                        self._capacity,
                        self._tokens + elapsed * self._rate,
                    )
                    self._last_refill = now

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                wait_for = (tokens - self._tokens) / self._rate

            await asyncio.sleep(wait_for)


class ExternalCallPolicy:
    """Retry + rate-limit + concurrency guard for external calls."""

    def __init__(
        self,
        *,
        max_parallel: int,
        rate_limits: Mapping[str, RateLimitConfig],
        default_rate: RateLimitConfig,
        max_retries: int,
        base_delay_seconds: float,
        max_delay_seconds: float,
        rate_limit_backoff_seconds: float,
        jitter_fraction: float = 0.1,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1.")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1.")
        if base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be positive.")
        if max_delay_seconds < base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds.")
        if rate_limit_backoff_seconds <= 0:
            raise ValueError("rate_limit_backoff_seconds must be positive.")
        if jitter_fraction < 0:
            raise ValueError("jitter_fraction must be >= 0.")

        self._semaphore = asyncio.Semaphore(max_parallel)
        self._max_retries = max_retries
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._rate_limit_backoff = rate_limit_backoff_seconds
        self._jitter_fraction = jitter_fraction

        self._default_limiter = TokenBucket(
            rate_per_second=default_rate.rate_per_second,
            burst=default_rate.burst,
        )
        self._limiters = {
            label: TokenBucket(
                rate_per_second=config.rate_per_second,
                burst=config.burst,
            )
            for label, config in rate_limits.items()
        }

    @classmethod
    def defaults(cls) -> ExternalCallPolicy:
        return cls(
            max_parallel=3,
            rate_limits={
                "wikipedia": RateLimitConfig(rate_per_second=2.0, burst=2),
                "arxiv": RateLimitConfig(rate_per_second=1.0, burst=1),
                "web": RateLimitConfig(rate_per_second=1.0, burst=1),
                "llm": RateLimitConfig(rate_per_second=1.0, burst=1),
            },
            default_rate=RateLimitConfig(rate_per_second=1.0, burst=1),
            max_retries=3,
            base_delay_seconds=0.5,
            max_delay_seconds=8.0,
            rate_limit_backoff_seconds=2.0,
        )

    @classmethod
    def from_settings(
        cls,
        settings: "Settings",
        *,
        max_retries: int | None = None,
    ) -> ExternalCallPolicy:
        from src.config import Settings

        if not isinstance(settings, Settings):
            raise TypeError("settings must be a Settings instance.")
        retries = max_retries if max_retries is not None else settings.external_max_retries
        return cls(
            max_parallel=settings.max_parallel_external_calls,
            rate_limits={
                "wikipedia": RateLimitConfig(
                    rate_per_second=settings.wikipedia_rps,
                    burst=settings.rate_limit_burst,
                ),
                "arxiv": RateLimitConfig(
                    rate_per_second=settings.arxiv_rps,
                    burst=settings.rate_limit_burst,
                ),
                "web": RateLimitConfig(
                    rate_per_second=settings.web_rps,
                    burst=settings.rate_limit_burst,
                ),
                "llm": RateLimitConfig(
                    rate_per_second=settings.llm_rps,
                    burst=settings.rate_limit_burst,
                ),
            },
            default_rate=RateLimitConfig(
                rate_per_second=min(
                    settings.wikipedia_rps,
                    settings.arxiv_rps,
                    settings.web_rps,
                    settings.llm_rps,
                ),
                burst=settings.rate_limit_burst,
            ),
            max_retries=retries,
            base_delay_seconds=settings.retry_base_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
            rate_limit_backoff_seconds=settings.rate_limit_backoff_seconds,
        )

    async def call_async(
        self,
        label: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        limiter = self._limiters.get(label, self._default_limiter)
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            await limiter.acquire()
            try:
                async with self._semaphore:
                    return await operation()
            except (TimeoutError, asyncio.TimeoutError, ProviderError, OSError) as exc:
                last_error = exc
                if attempt == self._max_retries:
                    break
                delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
                delay = self._apply_rate_limit_delay(delay, exc)
                delay = self._apply_jitter(delay)
                await asyncio.sleep(delay)

        if last_error is not None:
            raise last_error

        raise RuntimeError(f"Retry failed without an exception for {label}")

    async def call_sync(
        self,
        label: str,
        operation: Callable[[], T],
    ) -> T:
        return await self.call_async(label, lambda: asyncio.to_thread(operation))

    def _apply_jitter(self, delay: float) -> float:
        if delay <= 0 or self._jitter_fraction <= 0:
            return delay
        jitter = delay * self._jitter_fraction
        return delay + random.uniform(0.0, jitter)

    def _apply_rate_limit_delay(self, delay: float, exc: Exception) -> float:
        retry_after = _get_retry_after_seconds(exc)
        if retry_after is not None:
            return max(delay, retry_after)
        if _looks_rate_limited(exc):
            return max(delay, self._rate_limit_backoff)
        return delay


_RETRY_AFTER_RE = re.compile(r"retry-?after[:\s]+(\d+)", re.IGNORECASE)


def _get_retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers:
            value = headers.get("Retry-After") or headers.get("retry-after")
            if value:
                try:
                    return float(value)
                except ValueError:
                    pass

    text = str(exc)
    match = _RETRY_AFTER_RE.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _looks_rate_limited(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg
