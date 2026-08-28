"""Lambda 3: calcula el instante de la verificacion diferida.

La maquina de estados espera con un estado `Wait` hasta un timestamp
absoluto. No consume tiempo de Lambda ni de computo: Step Functions
simplemente no avanza hasta esa hora, asi que esperar seis horas cuesta cero.

La hora se configura por dataset (`VERIFY_B_SCHEDULE`, formato HH:MM en la
zona horaria del negocio). Si esa hora ya ha pasado hoy, se programa para el
dia siguiente.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.common.logging import get_logger, log_event

logger = get_logger(__name__)


def next_occurrence(
    schedule: str,
    timezone: str = "Europe/Madrid",
    now: datetime | None = None,
    min_delay_seconds: int = 60,
) -> datetime:
    """Devuelve el proximo instante (en UTC) que corresponde a `schedule`."""
    try:
        hour, minute = (int(p) for p in schedule.split(":", 1))
        target_time = time(hour=hour, minute=minute)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"VERIFY_B_SCHEDULE invalido: '{schedule}' (formato HH:MM)") from exc

    tz = ZoneInfo(timezone)
    now = (now or datetime.now(UTC)).astimezone(tz)
    target = datetime.combine(now.date(), target_time, tzinfo=tz)

    if target <= now + timedelta(seconds=min_delay_seconds):
        target += timedelta(days=1)

    return target.astimezone(UTC)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:  # noqa: ARG001
    schedule = event.get("schedule") or os.getenv("VERIFY_B_SCHEDULE", "08:00")
    timezone = event.get("timezone") or os.getenv("BUSINESS_TIMEZONE", "Europe/Madrid")

    # En la demo local no se espera de verdad: se acorta a unos segundos.
    if delay := int(os.getenv("VERIFY_B_DELAY_SECONDS", "0") or 0):
        target = datetime.now(UTC) + timedelta(seconds=delay)
    else:
        target = next_occurrence(schedule, timezone)

    iso = target.isoformat(timespec="seconds").replace("+00:00", "Z")
    log_event(logger, "verificacion diferida programada", at=iso, schedule=schedule, tz=timezone)
    return {**event, "verify_b_at": iso}


lambda_handler = handler
