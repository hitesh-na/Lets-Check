"""Redis job hashes and the shared Streams consumer group."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.schemas import CheckRequest, CheckResult

STREAM = "letscheck:checks"
GROUP = "letscheck-workers"
JOB_PREFIX = "letscheck:job:"
RESULT_TTL_SECONDS = 24 * 60 * 60


def connect_redis() -> Redis:
    return Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=10,
    )


def job_key(job_id: UUID) -> str:
    return f"{JOB_PREFIX}{job_id}"


def encode_job(job: CheckResult) -> dict[str, str]:
    """Redis hashes contain strings; empty values represent unknown fields."""
    encoded = {}
    for key, value in job.model_dump(mode="json").items():
        if value is None:
            encoded[key] = ""
        elif isinstance(value, bool):
            encoded[key] = "true" if value else "false"
        else:
            encoded[key] = str(value)
    return encoded


async def enqueue_job(redis: Redis, request: CheckRequest) -> CheckResult:
    job = CheckResult(
        job_id=uuid4(),
        url=request.url,
        status="queued",
        submitted_at=datetime.now(UTC),
    )
    # Keep initial storage and publication together before returning success.
    async with redis.pipeline(transaction=True) as pipeline:
        pipeline.hset(job_key(job.job_id), mapping=encode_job(job))
        pipeline.xadd(STREAM, {"job_id": str(job.job_id)})
        await pipeline.execute()
    return job


async def get_job(redis: Redis, job_id: UUID) -> CheckResult | None:
    values = await redis.hgetall(job_key(job_id))
    if not values:
        return None
    return CheckResult.model_validate(
        {key: None if value == "" else value for key, value in values.items()}
    )


async def save_job(redis: Redis, job: CheckResult) -> None:
    async with redis.pipeline(transaction=True) as pipeline:
        pipeline.hset(job_key(job.job_id), mapping=encode_job(job))
        if job.status == "completed":
            pipeline.expire(job_key(job.job_id), RESULT_TTL_SECONDS)
        await pipeline.execute()


async def ensure_group(redis: Redis) -> None:
    try:
        # Start at the beginning so jobs submitted before workers are not skipped.
        await redis.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
    except ResponseError as error:
        if not str(error).startswith("BUSYGROUP"):
            raise
