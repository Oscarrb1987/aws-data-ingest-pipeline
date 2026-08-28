"""Lambda 4: destino de todos los `Catch` de la maquina de estados.

Traduce el error tecnico de Step Functions a un aviso comprensible y deja el
ledger en un estado final coherente, de forma que un fallo nunca queda como
una ejecucion "en curso" para siempre.
"""

from __future__ import annotations

import json
from typing import Any

from src.common import ledger, notifications
from src.common.logging import get_logger, log_event
from src.common.models import RunStatus

logger = get_logger(__name__)

_MENSAJES = {
    "ValidationFailed": "el fichero no supero la validacion previa",
    "VerificationFailed": "los datos cargados incumplen reglas criticas",
    "DriftDetected": "los datos cambiaron entre la verificacion A y la B",
    "States.TaskFailed": "fallo la tarea de transformacion",
    "States.Timeout": "la tarea excedio el tiempo maximo",
}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:  # noqa: ARG001
    error = event.get("error", {})
    error_type = error.get("Error", "Desconocido")
    cause = _readable_cause(error.get("Cause", ""))
    dataset = event.get("dataset", "desconocido")
    business_date = event.get("business_date", "desconocida")
    run_id = event.get("run_id")

    reason = _MENSAJES.get(error_type, error_type)

    if run_id:
        status = RunStatus.DRIFT_DETECTED if error_type == "DriftDetected" else RunStatus.FAILED
        try:
            ledger.update(run_id, status, error_type=error_type, error_cause=cause[:2000])
        except Exception:  # pragma: no cover - el ledger no debe tumbar la alerta
            logger.warning("no se pudo actualizar el ledger para %s", run_id)

    notifications.notify_failure(dataset, business_date, reason, cause)
    log_event(logger, "fallo notificado", run_id=run_id, error_type=error_type, reason=reason)

    return {"notified": True, "run_id": run_id, "error_type": error_type, "reason": reason}


def _readable_cause(cause: str) -> str:
    """Step Functions envuelve el error de Lambda en un JSON anidado."""
    if not cause:
        return ""
    try:
        parsed = json.loads(cause)
    except (json.JSONDecodeError, TypeError):
        return cause
    message = parsed.get("errorMessage", cause)
    trace = parsed.get("stackTrace") or []
    return f"{message}\n\n{''.join(trace[-3:])}" if trace else str(message)


lambda_handler = handler
