"""Request validation and the public job response models."""

import os
from datetime import datetime
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


class CheckRequest(BaseModel):
    url: AnyHttpUrl

    @field_validator("url", mode="before")
    @classmethod
    def reject_raw_credentials(cls, value: object) -> object:
        # Check before URL normalization can remove empty user information.
        if isinstance(value, str) and "@" in urlsplit(value).netloc:
            raise ValueError("URLs with embedded credentials are not allowed")
        return value

    @field_validator("url")
    @classmethod
    def restrict_host(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        host = (value.host or "").lower()
        if not host:
            raise ValueError("A hostname is required")
        if value.username is not None or value.password is not None:
            raise ValueError("URLs with embedded credentials are not allowed")

        local_name = host.rstrip(".")
        if local_name == "localhost" or local_name.endswith(".localhost"):
            raise ValueError("Local hosts are not allowed")

        try:
            address = ip_address(host.strip("[]"))
        except ValueError:
            address = None
        if address is not None and (
            not address.is_global
            or address.is_multicast
            or address.is_reserved
        ):
            raise ValueError("Only public IP addresses are allowed")

        allowed_hosts = {
            entry.strip().lower()
            for entry in os.getenv("ALLOWED_HOSTS", "example.com,httpbin.org").split(",")
            if entry.strip()
        }
        if host not in allowed_hosts:
            raise ValueError("Hostname is not in ALLOWED_HOSTS")
        return value


class CheckAccepted(BaseModel):
    job_id: UUID
    status: Literal["queued"] = "queued"


class CheckResult(BaseModel):
    job_id: UUID
    url: AnyHttpUrl
    status: Literal["queued", "running", "completed"]
    http_status: int | None = None
    reachable: bool | None = None
    healthy: bool | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    attempts: int | None = Field(default=None, ge=1, le=2)
    worker_id: str | None = None
    error: str | None = None
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
