"""Factory domain logic: cascading unit/division control, usage rollups,
and meter reconciliation.

Pure functions only, same reasoning as household.py — the repository layer
fetches rows from Postgres, this module decides what to do with them.

Division, unit, and device are structurally the same thing here (a scope
that might contain child devices with their own busy/idle state), which is
why one planning function serves all three levels of the hierarchy instead
of three separate implementations — the Composite pattern, without needing
a literal class hierarchy since we're already working with plain rows.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class BlockedDevice:
    device_id: str
    device_name: str
    unit_name: str
    division_name: str

    @property
    def message(self) -> str:
        return f"{self.device_name} ({self.unit_name}, {self.division_name}) is still completing a task"


@dataclass
class CascadePlan:
    to_command: list[str] = field(default_factory=list)
    blocked: list[BlockedDevice] = field(default_factory=list)

    @property
    def is_clear(self) -> bool:
        return not self.blocked


def plan_cascade_command(devices: list[dict], *, force: bool = False) -> CascadePlan:
    """Decide which devices in a unit/division shutdown can proceed.

    A device with status "running_task" (mid-weld, mid-press-stroke — not
    safely interruptible right now) is held back unless the caller passes
    force=True, in which case it's included but the caller is responsible
    for writing an audit_log entry noting the forced interrupt.
    """
    plan = CascadePlan()
    for device in devices:
        if device["status"] == "running_task" and not force:
            plan.blocked.append(
                BlockedDevice(
                    device_id=str(device["id"]),
                    device_name=device["name"],
                    unit_name=device["unit_name"],
                    division_name=device["division_name"],
                )
            )
        else:
            plan.to_command.append(str(device["id"]))
    return plan


def sum_unit_usage(unit_readings_kwh: list[Decimal]) -> Decimal:
    return sum(unit_readings_kwh, Decimal("0"))


def reconcile_meter(
    division_reading_kwh: Decimal, units_sum_kwh: Decimal, tolerance_pct: Decimal = Decimal("5")
) -> dict:
    """Compare a division's main meter against the sum of its units' sub-meters.

    A persistent mismatch beyond tolerance usually means sensor drift or a
    wiring fault, not an actual usage anomaly — this is a data-quality
    check, not a usage alert.
    """
    if division_reading_kwh == 0:
        discrepancy_pct = Decimal("100") if units_sum_kwh != 0 else Decimal("0")
    else:
        discrepancy_pct = abs(division_reading_kwh - units_sum_kwh) / division_reading_kwh * 100
    return {
        "discrepancy_pct": discrepancy_pct,
        "flagged": discrepancy_pct > tolerance_pct,
    }


def check_threshold_breach(current_kw: Decimal, threshold_kw: Decimal) -> bool:
    return current_kw >= threshold_kw
