from __future__ import annotations

import asyncio
import inspect
import random
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import httpx

from .models import ClientStats, RequestEvent


class RequestFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        method: str,
        url: str,
        status_code: int | None,
        attempts: int,
        response_text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.url = url
        self.status_code = status_code
        self.attempts = attempts
        self.response_text = response_text


EventSink = Callable[[RequestEvent], Any | Awaitable[Any]]


class PCCClient:
    def __init__(
        self,
        *,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
        max_retries: int = 5,
        concurrency_limit: int = 5,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter_fn: Callable[[float], float] | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            timeout=timeout,
        )
        self.max_retries = max_retries
        self._semaphore = asyncio.Semaphore(concurrency_limit)
        self._sleep = sleep_fn
        self._jitter = jitter_fn or (lambda scale: random.uniform(0.0, scale))
        self._event_sink = event_sink
        self.stats = ClientStats()

    def set_event_sink(self, event_sink: EventSink | None) -> None:
        self._event_sink = event_sink

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PCCClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request_json("GET", path, params=params)

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        last_failure: RequestFailure | None = None
        request_url = self._format_url(path, params)

        for attempt in range(1, self.max_retries + 1):
            async with self._semaphore:
                started = time.perf_counter()
                try:
                    response = await self._client.request(
                        method,
                        path,
                        params=params,
                        json=json_body,
                    )
                except httpx.RequestError as exc:
                    self.stats.request_count += 1
                    duration_ms = (time.perf_counter() - started) * 1000.0
                    self.stats.total_latency_ms += duration_ms
                    wait_seconds = self._backoff_seconds(attempt)
                    last_failure = RequestFailure(
                        str(exc),
                        method=method,
                        url=request_url,
                        status_code=None,
                        attempts=attempt,
                    )
                    if attempt == self.max_retries:
                        self.stats.failure_count += 1
                        await self._emit_event(
                            RequestEvent(
                                method=method,
                                url=request_url,
                                attempt=attempt,
                                status_code=None,
                                duration_ms=duration_ms,
                                outcome="failure",
                                error=str(exc),
                            )
                        )
                        raise last_failure from exc
                    self.stats.retry_count += 1
                    await self._emit_event(
                        RequestEvent(
                            method=method,
                            url=request_url,
                            attempt=attempt,
                            status_code=None,
                            duration_ms=duration_ms,
                            outcome="retry",
                            wait_seconds=wait_seconds,
                            error=str(exc),
                        )
                    )
                    await self._sleep(wait_seconds)
                    continue

                self.stats.request_count += 1
                duration_ms = (time.perf_counter() - started) * 1000.0
                status_code = response.status_code

                if status_code == 429 or status_code >= 500:
                    body_text = response.text
                    retry_after = self._retry_after_seconds(response.headers.get("Retry-After"))
                    self.stats.total_latency_ms += duration_ms
                    wait_seconds = max(retry_after or 0.0, self._backoff_seconds(attempt))
                    event = RequestEvent(
                        method=method,
                        url=request_url,
                        attempt=attempt,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        outcome="retry" if attempt < self.max_retries else "failure",
                        retry_after=retry_after,
                        wait_seconds=wait_seconds if attempt < self.max_retries else 0.0,
                        response_text=body_text,
                    )

                    if status_code == 429:
                        self.stats.rate_limited_count += 1

                    if attempt == self.max_retries:
                        self.stats.failure_count += 1
                        await self._emit_event(event)
                        raise RequestFailure(
                            f"{method} {request_url} failed with HTTP {status_code}",
                            method=method,
                            url=request_url,
                            status_code=status_code,
                            attempts=attempt,
                            response_text=body_text,
                        )

                    self.stats.retry_count += 1
                    await self._emit_event(event)
                    await self._sleep(wait_seconds)
                    continue

                self.stats.total_latency_ms += duration_ms
                payload = response.json()
                await self._emit_event(
                    RequestEvent(
                        method=method,
                        url=request_url,
                        attempt=attempt,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        outcome="success",
                    )
                )
                return payload

        if last_failure is not None:
            raise last_failure
        raise RequestFailure(
            f"{method} {request_url} failed without a response",
            method=method,
            url=request_url,
            status_code=None,
            attempts=self.max_retries,
        )

    def _backoff_seconds(self, attempt: int) -> float:
        scale = 0.25
        return min(30.0, 0.5 * (2 ** (attempt - 1)) + self._jitter(scale))

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            return float(value)
        except ValueError:
            return 0.0

    @staticmethod
    def _format_url(path: str, params: dict[str, Any] | None) -> str:
        if not params:
            return path
        query = urlencode(sorted(params.items()))
        return f"{path}?{query}"

    async def _emit_event(self, event: RequestEvent) -> None:
        if self._event_sink is None:
            return
        result = self._event_sink(event)
        if inspect.isawaitable(result):
            await result
