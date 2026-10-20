"""Worker behavior with mocked HTTP and Redis; no public network calls."""

import asyncio

import httpx
import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError, ResponseError

from app.queue import GROUP, STREAM, ensure_group, job_key
from app.worker import consume, process_message


class UnreadBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise AssertionError("The worker must not download the response body")
        yield b""

    async def aclose(self):
        pass


def run_message(redis_backend, stored_job, handler):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5, follow_redirects=False
        ) as client:
            await process_message(
                redis_backend, client, "worker-1", "1-0",
                {"job_id": str(stored_job.job_id)},
            )
    asyncio.run(run())


def test_success_saves_result_before_ack_without_reading_body(redis_backend, stored_job):
    events = []
    pipeline = redis_backend.pipeline.return_value

    async def save():
        current_status = pipeline.hset.call_args.kwargs["mapping"]["status"]
        events.append(current_status)
        if current_status == "running":
            pipeline.expire.assert_not_called()
        else:
            pipeline.expire.assert_called_once_with(job_key(stored_job.job_id), 86400)

    async def ack(*args):
        events.append("ack")

    pipeline.execute.side_effect = save
    redis_backend.xack.side_effect = ack
    run_message(redis_backend, stored_job, lambda request: httpx.Response(200, stream=UnreadBody()))
    result = pipeline.hset.call_args.kwargs["mapping"]
    assert result["worker_id"] == "worker-1"
    assert result["reachable"] == "true"
    assert result["healthy"] == "true"
    assert result["http_status"] == "200"
    assert int(result["latency_ms"]) >= 0
    assert result["attempts"] == "1"
    assert events == ["running", "completed", "ack"]
    redis_backend.xack.assert_awaited_once_with(STREAM, GROUP, "1-0")


@pytest.mark.parametrize("status_code", [400, 404, 429, 500, 503])
def test_http_error_is_reachable_but_unhealthy_without_retry(
    redis_backend, stored_job, status_code,
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status_code)

    run_message(redis_backend, stored_job, handler)
    result = redis_backend.pipeline.return_value.hset.call_args.kwargs["mapping"]
    assert result["status"] == "completed"
    assert result["http_status"] == str(status_code)
    assert result["reachable"] == "true"
    assert result["healthy"] == "false"
    assert result["attempts"] == "1"
    assert result["error"] == ""
    assert len(requests) == 1


def test_redirect_is_not_followed(redis_backend, stored_job):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1"})

    run_message(redis_backend, stored_job, handler)
    result = redis_backend.pipeline.return_value.hset.call_args.kwargs["mapping"]
    assert result["http_status"] == "302"
    assert len(requests) == 1


@pytest.mark.parametrize("error_type", [
    httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
    httpx.WriteTimeout, httpx.PoolTimeout,
])
def test_transient_failure_stops_after_two_attempts_without_leaking_text(
    redis_backend, stored_job, error_type, caplog,
):
    requests = []

    def handler(request):
        requests.append(request)
        raise error_type("secret-query-token", request=request)

    with caplog.at_level("INFO", logger="app.worker"):
        run_message(redis_backend, stored_job, handler)
    result = redis_backend.pipeline.return_value.hset.call_args.kwargs["mapping"]
    assert result["status"] == "completed"
    assert result["reachable"] == "false"
    assert result["healthy"] == "false"
    assert result["http_status"] == ""
    assert error_type.__name__ in result["error"]
    assert "secret-query-token" not in result["error"]
    assert "secret-query-token" not in caplog.text
    assert result["attempts"] == "2"
    assert len(requests) == 2
    redis_backend.xack.assert_awaited_once_with(STREAM, GROUP, "1-0")


@pytest.mark.parametrize("error_type", [
    httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
])
def test_success_on_retry_records_both_attempts_and_total_latency(
    redis_backend, stored_job, error_type, monkeypatch,
):
    requests = []
    # Controlled clock proves elapsed time covers the whole check, including retry.
    clock = iter([10.0, 10.25])
    monkeypatch.setattr("app.worker.perf_counter", lambda: next(clock))

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise error_type("temporary failure", request=request)
        return httpx.Response(200, stream=UnreadBody())

    run_message(redis_backend, stored_job, handler)
    result = redis_backend.pipeline.return_value.hset.call_args.kwargs["mapping"]
    assert result["status"] == "completed"
    assert result["http_status"] == "200"
    assert result["reachable"] == "true"
    assert result["healthy"] == "true"
    assert result["error"] == ""
    assert result["attempts"] == "2"
    assert result["latency_ms"] == "250"
    assert len(requests) == 2
    redis_backend.xack.assert_awaited_once_with(STREAM, GROUP, "1-0")


def test_http_error_on_retry_is_terminal(redis_backend, stored_job):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("temporary failure", request=request)
        return httpx.Response(503)

    run_message(redis_backend, stored_job, handler)
    result = redis_backend.pipeline.return_value.hset.call_args.kwargs["mapping"]
    assert result["status"] == "completed"
    assert result["http_status"] == "503"
    assert result["reachable"] == "true"
    assert result["healthy"] == "false"
    assert result["attempts"] == "2"
    assert result["error"] == ""
    assert len(requests) == 2


def test_other_request_error_is_not_retried(redis_backend, stored_job):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadError("secret-query-token", request=request)

    run_message(redis_backend, stored_job, handler)
    result = redis_backend.pipeline.return_value.hset.call_args.kwargs["mapping"]
    assert result["status"] == "completed"
    assert result["http_status"] == ""
    assert result["reachable"] == "false"
    assert result["healthy"] == "false"
    assert result["attempts"] == "1"
    assert result["error"] == "ReadError: HTTP request failed"
    assert len(requests) == 1


def test_failed_result_storage_leaves_message_unacknowledged(redis_backend, stored_job):
    redis_backend.pipeline.return_value.execute.side_effect = [[14], RedisConnectionError("offline")]
    with pytest.raises(RedisConnectionError):
        run_message(redis_backend, stored_job, lambda request: httpx.Response(200))
    redis_backend.xack.assert_not_awaited()


def test_worker_revalidates_url_before_network_request(redis_backend, stored_job):
    redis_backend.hgetall.return_value["url"] = "http://127.0.0.1"
    with pytest.raises(ValidationError):
        run_message(
            redis_backend, stored_job,
            lambda request: pytest.fail("Blocked URL reached the HTTP client"),
        )
    redis_backend.pipeline.return_value.execute.assert_not_awaited()
    redis_backend.xack.assert_not_awaited()


def test_existing_group_is_allowed_but_other_group_errors_propagate(redis_backend):
    redis_backend.xgroup_create.side_effect = ResponseError("BUSYGROUP Consumer Group name already exists")
    asyncio.run(ensure_group(redis_backend))
    redis_backend.xgroup_create.assert_awaited_once_with(STREAM, GROUP, id="0-0", mkstream=True)
    redis_backend.xgroup_create.side_effect = ResponseError("permission denied")
    with pytest.raises(ResponseError, match="permission denied"):
        asyncio.run(ensure_group(redis_backend))


def test_bad_message_does_not_stop_processing_the_next_job(redis_backend, stored_job):
    redis_backend.xreadgroup.side_effect = [
        [(STREAM, [("1-0", {"job_id": "bad-id"})])],
        [(STREAM, [("2-0", {"job_id": str(stored_job.job_id)})])],
        asyncio.CancelledError(),
    ]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        ) as client:
            await consume(redis_backend, client, "worker-1")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    redis_backend.xack.assert_awaited_once_with(STREAM, GROUP, "2-0")
