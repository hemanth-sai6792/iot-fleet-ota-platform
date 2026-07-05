from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DeviceCreate(BaseModel):
    name: str
    model: str = "generic-sensor"
    firmware_version: str = "1.0.0"


class DeviceOut(BaseModel):
    id: UUID
    name: str
    model: str
    status: str
    firmware_version: str
    desired_state: dict[str, Any]
    reported_state: dict[str, Any]
    last_seen: datetime | None
    created_at: datetime


class RolloutCreate(BaseModel):
    firmware_version: str
    canary_percent: int = 20
    failure_threshold_percent: float = 20.0


class RolloutOut(BaseModel):
    id: UUID
    firmware_version: str
    previous_firmware_version: str
    canary_percent: int
    failure_threshold_percent: float
    status: str
    target_device_ids: list[UUID]
    started_at: datetime
    ended_at: datetime | None


class RolloutProgress(BaseModel):
    rollout: RolloutOut
    applied: int
    failed: int
    pending: int
    total: int
