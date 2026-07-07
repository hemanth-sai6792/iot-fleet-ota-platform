"""Background loop: threshold alerts and division/unit meter reconciliation.

Uses the pure functions in factory.py — this module is just the async
wiring (fetch latest readings, call the pure check, write the result).
"""

import asyncio
import logging
from decimal import Decimal

import asyncpg

from app.config import METER_RECONCILE_TOLERANCE_PCT, USAGE_MONITOR_INTERVAL_SECONDS
from app.factory import check_threshold_breach, reconcile_meter

logger = logging.getLogger("usage_monitor")


async def _latest_reading(pool: asyncpg.Pool, scope_type: str, scope_id) -> Decimal | None:
    row = await pool.fetchrow(
        """
        SELECT kwh FROM usage_readings
        WHERE scope_type = $1 AND scope_id = $2
        ORDER BY ts DESC LIMIT 1
        """,
        scope_type,
        scope_id,
    )
    return row["kwh"] if row else None


async def _check_thresholds(pool: asyncpg.Pool, scope_type: str, table: str) -> None:
    rows = await pool.fetch(
        f"SELECT id, alert_threshold_kw FROM {table} WHERE alert_threshold_kw IS NOT NULL"
    )
    for row in rows:
        reading = await _latest_reading(pool, scope_type, row["id"])
        if reading is None:
            continue
        breached = check_threshold_breach(reading, row["alert_threshold_kw"])
        active = await pool.fetchrow(
            """
            SELECT id FROM threshold_alerts
            WHERE scope_type = $1 AND scope_id = $2 AND status = 'active'
            """,
            scope_type,
            row["id"],
        )
        if breached and active is None:
            await pool.execute(
                """
                INSERT INTO threshold_alerts (scope_type, scope_id, threshold_kw)
                VALUES ($1, $2, $3)
                """,
                scope_type,
                row["id"],
                row["alert_threshold_kw"],
            )
            logger.warning("threshold breach: %s %s at %.2f kW", scope_type, row["id"], reading)
        elif not breached and active is not None:
            await pool.execute(
                "UPDATE threshold_alerts SET status = 'resolved', resolved_at = now() WHERE id = $1",
                active["id"],
            )


async def _reconcile_divisions(pool: asyncpg.Pool) -> None:
    divisions = await pool.fetch("SELECT id FROM divisions")
    for division in divisions:
        division_reading = await _latest_reading(pool, "division", division["id"])
        if division_reading is None:
            continue
        units = await pool.fetch("SELECT id FROM units WHERE division_id = $1", division["id"])
        unit_readings = []
        for unit in units:
            reading = await _latest_reading(pool, "unit", unit["id"])
            if reading is not None:
                unit_readings.append(reading)
        units_sum = sum(unit_readings, Decimal("0"))
        result = reconcile_meter(division_reading, units_sum, Decimal(str(METER_RECONCILE_TOLERANCE_PCT)))
        await pool.execute(
            """
            INSERT INTO meter_reconciliations
                (division_id, division_reading_kwh, units_sum_kwh, discrepancy_pct, flagged)
            VALUES ($1, $2, $3, $4, $5)
            """,
            division["id"],
            division_reading,
            units_sum,
            result["discrepancy_pct"],
            result["flagged"],
        )
        if result["flagged"]:
            logger.warning(
                "meter mismatch: division %s off by %.1f%%", division["id"], result["discrepancy_pct"]
            )


async def usage_monitor_loop(pool: asyncpg.Pool) -> None:
    while True:
        await _check_thresholds(pool, "unit", "units")
        await _check_thresholds(pool, "division", "divisions")
        await _reconcile_divisions(pool)
        await asyncio.sleep(USAGE_MONITOR_INTERVAL_SECONDS)
