import asyncio
import time

from runner import runner


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeClient:
    def __init__(self, status_code):
        self.status_code = status_code

    async def get(self, _url):
        return FakeResponse(self.status_code)

    async def request(self, _method, _url, **_kwargs):
        return FakeResponse(self.status_code)


def test_runner_counts_client_errors_as_errors():
    result = []

    asyncio.run(runner.fire(FakeClient(404), "/missing", time.perf_counter(), result))

    assert len(result) == 1
    assert result[0][1] is False


def test_runner_accepts_success_status_codes():
    result = []

    asyncio.run(runner.fire(FakeClient(200), "/ok", time.perf_counter(), result))

    assert result[0][1] is True


def test_runner_uses_configured_health_path(monkeypatch):
    urls = []

    class HealthyClient:
        async def get(self, url):
            urls.append(url)
            return FakeResponse(200)

    monkeypatch.setattr(runner, "BASE", "http://localhost:9000")
    monkeypatch.setattr(runner, "HEALTH_PATH", "/ready")

    asyncio.run(runner.wait_healthy(HealthyClient()))

    assert urls == ["http://localhost:9000/ready"]


def test_runner_sends_configured_method_and_json_body(monkeypatch):
    calls = []

    class RequestClient:
        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return FakeResponse(201)

    monkeypatch.setattr(runner, "BASE", "http://localhost:8000")
    result = []

    asyncio.run(
        runner.fire(
            RequestClient(),
            {"method": "POST", "path": "/orders", "body": {"items": [1, 2]}},
            time.perf_counter(),
            result,
        )
    )

    assert calls == [
        ("POST", "http://localhost:8000/orders", {"json": {"items": [1, 2]}})
    ]
    assert result[0][1] is True
    assert result[0][2] == "POST /orders"
