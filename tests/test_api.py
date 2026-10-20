"""In-process API tests; no Redis or outgoing website requests are required."""

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from uuid import UUID

from app.main import app, get_redis
from app.queue import STREAM, job_key


@pytest.fixture
def client(redis_backend):
    app.dependency_overrides[get_redis] = lambda: redis_backend
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_redis, None)


def test_api_docs_load(client: TestClient):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "http://localhost",
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254",
        "http://[::1]",
        "http://[fc00::1]",
        "https://user:password@example.com",
        "https://user@example.com",
        "https://@example.com",
        "https://example.com.evil.test",
        "https://evil-example.com",
        "https://sub.example.com",
        "https://unapproved.test",
        "not a URL",
        "https://",
    ],
)
def test_invalid_or_blocked_url_returns_422(client: TestClient, url: str):
    response = client.post("/checks", json={"url": url})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://httpbin.org/status/503",
        "https://EXAMPLE.COM/path?probe=1",
    ],
)
def test_valid_url_stores_and_publishes_a_queued_job(client: TestClient, redis_backend, url: str):
    response = client.post("/checks", json={"url": url})
    assert response.status_code == 202
    body = response.json()
    job_id = UUID(body["job_id"])
    assert body["status"] == "queued"
    pipeline = redis_backend.pipeline.return_value
    pipeline.execute.assert_awaited_once()
    pipeline.xadd.assert_called_once_with(STREAM, {"job_id": str(job_id)})
    assert pipeline.hset.call_args.args == (job_key(job_id),)
    assert pipeline.hset.call_args.kwargs["mapping"]["status"] == "queued"


def test_missing_url_returns_422(client: TestClient):
    assert client.post("/checks", json={}).status_code == 422


def test_allowlist_matches_configured_hosts_case_insensitively(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALLOWED_HOSTS", "  HTTPBIN.ORG , ")
    assert client.post("/checks", json={"url": "https://httpbin.org"}).status_code == 202
    assert client.post("/checks", json={"url": "https://example.com"}).status_code == 422


@pytest.mark.parametrize(
    ("host", "url"),
    [
        ("localhost", "http://localhost"),
        ("app.localhost", "http://app.localhost"),
        ("127.0.0.1", "http://127.0.0.1"),
        ("10.0.0.1", "http://10.0.0.1"),
        ("[::1]", "http://[::1]"),
        ("224.0.0.1", "http://224.0.0.1"),
    ],
)
def test_local_or_nonpublic_host_is_rejected_even_if_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, host: str, url: str
):
    monkeypatch.setenv("ALLOWED_HOSTS", host)
    assert client.post("/checks", json={"url": url}).status_code == 422


def test_empty_allowlist_blocks_all_hosts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALLOWED_HOSTS", "")
    assert client.post("/checks", json={"url": "https://example.com"}).status_code == 422


def test_missing_job_returns_404(client: TestClient):
    response = client.get("/checks/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404


def test_known_queued_job_returns_unknown_fields_as_null(client: TestClient, stored_job):
    response = client.get(f"/checks/{stored_job.job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"] == str(stored_job.job_id)
    for field in ["http_status", "reachable", "healthy", "latency_ms", "attempts", "worker_id"]:
        assert body[field] is None


def test_enqueue_error_does_not_return_a_queued_job(client: TestClient, redis_backend):
    redis_backend.pipeline.return_value.execute.side_effect = RedisConnectionError("offline")
    response = client.post("/checks", json={"url": "https://example.com"})
    assert response.status_code == 503
    assert "job_id" not in response.json()


def test_lookup_error_returns_503(client: TestClient, redis_backend):
    redis_backend.hgetall.side_effect = RedisConnectionError("offline")
    response = client.get("/checks/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 503
    assert "job_id" not in response.json()


def test_invalid_job_id_returns_404(client: TestClient, redis_backend):
    assert client.get("/checks/not-a-job-id").status_code == 404
    redis_backend.hgetall.assert_not_awaited()
