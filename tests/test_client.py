import asyncio

import httpx


def test_client_retries_retry_after_and_5xx() -> None:
    from claimready.client import PCCClient

    attempts = []
    sleep_calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append((request.method, str(request.url)))
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"detail": "rate limited"})
        if len(attempts) == 2:
            return httpx.Response(500, json={"detail": "server error"})
        return httpx.Response(200, json=[{"id": 1, "patient_id": "FA-001"}])

    async def sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    client = PCCClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
        sleep_fn=sleep,
        jitter_fn=lambda *_: 0.0,
        max_retries=3,
    )

    result = asyncio.run(client.get_json("/pcc/patients", params={"facility_id": 101}))

    assert result == [{"id": 1, "patient_id": "FA-001"}]
    assert len(attempts) == 3
    assert sleep_calls == [1.0, 1.0]
    assert client.stats.request_count == 3
    assert client.stats.retry_count == 2
    assert client.stats.rate_limited_count == 1
    assert client.stats.failure_count == 0


def test_client_surfaces_final_failure_after_retries() -> None:
    from claimready.client import PCCClient, RequestFailure

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "still broken"})

    async def sleep(seconds: float) -> None:
        return None

    client = PCCClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
        sleep_fn=sleep,
        jitter_fn=lambda *_: 0.0,
        max_retries=2,
    )

    try:
        asyncio.run(client.get_json("/pcc/patients", params={"facility_id": 101}))
    except RequestFailure as exc:
        assert exc.status_code == 500
    else:
        raise AssertionError("expected RequestFailure")

    assert client.stats.request_count == 2
    assert client.stats.retry_count == 1
    assert client.stats.failure_count == 1
