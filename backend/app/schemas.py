from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class SiteCreate(BaseModel):
    name: str
    type: Literal["household", "showroom", "factory"]


class SiteOut(BaseModel):
    id: UUID
    name: str
    type: str
    created_at: datetime


class RoomCreate(BaseModel):
    site_id: UUID
    name: str


class RoomOut(BaseModel):
    id: UUID
    site_id: UUID
    name: str


class DeviceCreate(BaseModel):
    site_id: UUID
    name: str
    device_type: str
    room_id: UUID | None = None
    unit_id: UUID | None = None
    task_interruptible: bool = True


class DeviceOut(BaseModel):
    id: UUID
    site_id: UUID
    name: str
    device_type: str
    room_id: UUID | None
    unit_id: UUID | None
    status: str
    task_interruptible: bool
    desired_state: dict[str, Any]
    reported_state: dict[str, Any]
    last_seen: datetime | None


class DesiredStatePatch(BaseModel):
    patch: dict[str, Any]


class SceneDeviceIn(BaseModel):
    device_id: UUID
    target_state: dict[str, Any]


class SceneCreate(BaseModel):
    site_id: UUID
    name: str
    devices: list[SceneDeviceIn]


class SceneOut(BaseModel):
    id: UUID
    site_id: UUID
    name: str
    alexa_scene_id: str | None


class RuleCreate(BaseModel):
    site_id: UUID
    name: str
    trigger_type: Literal["time", "sensor", "voice"]
    trigger_config: dict[str, Any]
    action_type: Literal["device", "scene"]
    action_target_id: UUID
    enabled: bool = True


class RuleOut(BaseModel):
    id: UUID
    site_id: UUID
    name: str
    trigger_type: str
    trigger_config: dict[str, Any]
    action_type: str
    action_target_id: UUID
    enabled: bool


class RuleEvaluateRequest(BaseModel):
    reported_state: dict[str, Any] | None = None
    spoken_phrase: str | None = None


class DivisionCreate(BaseModel):
    site_id: UUID
    name: str
    alert_threshold_kw: float | None = None


class DivisionOut(BaseModel):
    id: UUID
    site_id: UUID
    name: str
    desired_state: dict[str, Any]
    reported_state: dict[str, Any]
    alert_threshold_kw: float | None


class UnitCreate(BaseModel):
    division_id: UUID
    name: str
    alert_threshold_kw: float | None = None


class UnitOut(BaseModel):
    id: UUID
    division_id: UUID
    name: str
    desired_state: dict[str, Any]
    reported_state: dict[str, Any]
    alert_threshold_kw: float | None


class PowerRequest(BaseModel):
    desired_power: Literal["on", "off"]
    force: bool = False
    actor: str = "site-operator"
    reason: str | None = None
    cross_site: bool = False


class BlockedDeviceOut(BaseModel):
    device_id: UUID
    device_name: str
    unit_name: str
    division_name: str
    message: str


class PowerResponse(BaseModel):
    commanded_device_ids: list[UUID]
    blocked: list[BlockedDeviceOut]


class AuditLogOut(BaseModel):
    id: int
    actor: str
    site_id: UUID
    action: str
    target_type: str
    target_id: UUID
    reason: str | None
    ts: datetime


class FaultLogOut(BaseModel):
    id: int
    device_id: UUID
    code: str
    message: str
    ts: datetime


class ThresholdAlertOut(BaseModel):
    id: UUID
    scope_type: str
    scope_id: UUID
    threshold_kw: float
    status: str
    triggered_at: datetime
    resolved_at: datetime | None


class MeterReconciliationOut(BaseModel):
    id: int
    division_id: UUID
    ts: datetime
    division_reading_kwh: float
    units_sum_kwh: float
    discrepancy_pct: float
    flagged: bool
