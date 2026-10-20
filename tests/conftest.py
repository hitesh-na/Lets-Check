"""Shared Redis mocks and queued job data, without a live server."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.schemas import CheckResult


@pytest.fixture(autouse=True)
def demo_hosts(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com,httpbin.org")


@pytest.fixture
def queued_job():
    return CheckResult(
        job_id=uuid4(),
        url="https://example.com/",
        status="queued",
        submitted_at=datetime.now(UTC),
    )


@pytest.fixture
def redis_backend():
    backend = MagicMock(spec=Redis)
    backend.hgetall = AsyncMock(return_value={})
    backend.hset = AsyncMock(return_value=14)
    backend.xack = AsyncMock(return_value=1)
    backend.xgroup_create = AsyncMock(return_value=True)
    backend.xreadgroup = AsyncMock(return_value=[])
    pipeline = MagicMock()
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock(return_value=False)
    pipeline.execute = AsyncMock(return_value=[14, "1-0"])
    backend.pipeline.return_value = pipeline
    return backend


@pytest.fixture
def stored_job(redis_backend, queued_job):
    redis_backend.hgetall.return_value = {
        "job_id": str(queued_job.job_id),
        "url": str(queued_job.url),
        "status": "queued",
        "submitted_at": queued_job.submitted_at.isoformat(),
    }
    return queued_job
