"""Run one independent, sequential consumer with python -m app.worker."""

import asyncio
import logging
import os
import socket
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.queue import GROUP, STREAM, connect_redis, ensure_group, get_job, save_job
from app.schemas import CheckRequest

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 2


async def process_message(
    redis: Redis,
    client: httpx.AsyncClient,
    worker_id: str,
    message_id: str,
    fields: dict[str, str],
) -> None:
    job = await get_job(redis, UUID(fields["job_id"]))
    if job is None:
        raise LookupError("Stream message references a missing job")

    # Recheck the allowlist in this process before performing any HTTP request.
    request = CheckRequest(url=job.url)
    job.status = "running"
    job.worker_id = worker_id
    job.started_at = datetime.now(UTC)
    await save_job(redis, job)

    started = perf_counter()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        job.attempts = attempt
        try:
            async with client.stream("GET", str(request.url)) as response:
                job.http_status = response.status_code
                job.reachable = True
                job.healthy = 200 <= response.status_code < 400
                job.error = None
            break
        except httpx.RequestError as error:
            if (
                isinstance(error, (httpx.ConnectError, httpx.TimeoutException))
                and attempt < MAX_ATTEMPTS
            ):
                logger.info(
                    "worker=%s job=%s attempt=%s error=%s retrying",
                    worker_id, job.job_id, attempt, type(error).__name__,
                )
                continue
            job.http_status = None
            job.reachable = False
            job.healthy = False
            # Exception text may contain the URL, including sensitive query strings.
            job.error = f"{type(error).__name__}: HTTP request failed"
            break

    job.latency_ms = int((perf_counter() - started) * 1000)
    job.status = "completed"
    job.finished_at = datetime.now(UTC)
    await save_job(redis, job)
    # An unsuccessful HTTP check is still a successfully processed job.
    await redis.xack(STREAM, GROUP, message_id)
    logger.info(
        "worker=%s job=%s status=completed attempts=%s http_status=%s reachable=%s",
        worker_id, job.job_id, job.attempts, job.http_status, job.reachable,
    )


async def consume(redis: Redis, client: httpx.AsyncClient, worker_id: str) -> None:
    while True:
        try:
            messages = await redis.xreadgroup(
                GROUP, worker_id, streams={STREAM: ">"}, count=1, block=5000
            )
        except RedisError:
            logger.exception("Worker %s could not read Redis", worker_id)
            await asyncio.sleep(1)
            continue
        for _, entries in messages:
            for message_id, fields in entries:
                try:
                    await process_message(redis, client, worker_id, message_id, fields)
                except Exception:
                    # Leave the failed message pending; keep consuming new jobs.
                    logger.exception(
                        "Worker %s left message %s pending", worker_id, message_id
                    )


async def run_worker() -> None:
    worker_id = os.getenv("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
    redis = connect_redis()
    try:
        await ensure_group(redis)
        async with httpx.AsyncClient(
            timeout=5.0,
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0"
            },
        ) as client:
            logger.info("Worker %s ready", worker_id)
            await consume(redis, client, worker_id)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Worker stopped")
