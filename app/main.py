"""Let's Check API: submit Redis jobs and retrieve their current state."""

import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.queue import connect_redis, enqueue_job, get_job
from app.schemas import CheckAccepted, CheckRequest, CheckResult

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.redis = connect_redis()
    try:
        yield
    finally:
        await application.state.redis.aclose()


app = FastAPI(
    title="Let's Check",
    description="Submit website checks and retrieve their results.",
    version="0.5.0",
    lifespan=lifespan,
)


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


RedisDependency = Annotated[Redis, Depends(get_redis)]


@app.post(
    "/checks",
    response_model=CheckAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={503: {"description": "Job queue unavailable"}},
)
async def create_check(request: CheckRequest, redis: RedisDependency) -> CheckAccepted:
    try:
        job = await enqueue_job(redis, request)
    except RedisError:
        logger.exception("Could not enqueue a check")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job queue is unavailable",
        ) from None
    return CheckAccepted(job_id=job.job_id)


@app.get(
    "/checks/{job_id}",
    response_model=CheckResult,
    responses={
        404: {"description": "Job not found"},
        503: {"description": "Job storage unavailable"},
    },
)
async def get_check(job_id: str, redis: RedisDependency) -> CheckResult:
    try:
        parsed_id = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found") from None
    try:
        job = await get_job(redis, parsed_id)
    except (RedisError, ValidationError):
        logger.exception("Could not load job %s", parsed_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job storage is unavailable",
        ) from None
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
