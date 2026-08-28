"""Lambda 2: verificacion de la carga (fases A y B).

Este handler es el que sustituye a las dos comprobaciones manuales:

  Fase A - se ejecuta en cuanto el job de Glue termina. Responde a
           "los datos estan cargados y cuadran con el fichero de origen".
           Ademas guarda una huella (`fingerprint`) de la particion.

  Fase B - se ejecuta pasada la hora programada. Repite las mismas reglas y,
           sobre todo, compara la huella actual con la de la fase A. Si algun
           proceso ha reprocesado, duplicado o pisado la particion entre
           medias, se detecta aqui. Eso es lo que la comprobacion manual "a
           ojo" no ve.

El mismo codigo sirve para las dos fases: cambia el parametro, no la logica.
"""

from __future__ import annotations

from typing import Any

from src.common import ledger, notifications, storage
from src.common.config import get_settings
from src.common.logging import get_logger, log_event
from src.common.models import Fingerprint, Phase, RunStatus, VerificationReport
from src.common.rules import get_dataset_rules
from src.engines import QueryEngine, get_engine
from src.handlers.errors import DriftDetected, VerificationFailed

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:  # noqa: ARG001
    settings = get_settings()
    phase = Phase(event.get("phase", Phase.A_POST_LOAD))
    run_id = event["run_id"]
    dataset = event["dataset"]
    business_date = event["business_date"]
    expected_rows = int(event["expected_rows"])
    bucket = event.get("bucket", settings.data_bucket)

    engine = get_engine()
    try:
        report = run_verification(
            engine=engine,
            rules_path=settings.rules_path,
            run_id=run_id,
            dataset=dataset,
            business_date=business_date,
            expected_rows=expected_rows,
            phase=phase,
            previous_fingerprint=_previous_fingerprint(run_id, phase),
        )
    finally:
        engine.close()

    report_key = settings.report_key(dataset, business_date, run_id, str(phase))
    storage.put_json(bucket, report_key, report.to_dict())
    storage.put_text(
        bucket, report_key.replace(".json", ".md"), report.to_markdown(), "text/markdown"
    )
    report_uri = f"s3://{bucket}/{report_key}"

    _persist(run_id, phase, report)
    notifications.notify_report(report, report_uri)

    log_event(
        logger,
        "verificacion completada",
        run_id=run_id,
        phase=str(phase),
        passed=report.passed,
        failed=len(report.failed_checks),
    )

    payload = {
        **event,
        "phase": str(phase),
        "passed": report.passed,
        "report_uri": report_uri,
        "fingerprint": report.fingerprint.to_dict() if report.fingerprint else None,
        "failed_checks": [r.check_id for r in report.failed_checks],
        "drift": report.drift,
    }

    if report.drift:
        raise DriftDetected(
            f"los datos cambiaron tras la carga: {'; '.join(report.drift)}", run_id=run_id
        )
    if not report.passed:
        blocking = [r.message for r in report.failed_checks if r.blocking]
        raise VerificationFailed(
            "; ".join(blocking) or "reglas criticas incumplidas", run_id=run_id
        )

    return payload


def run_verification(
    *,
    engine: QueryEngine,
    rules_path: str,
    run_id: str,
    dataset: str,
    business_date: str,
    expected_rows: int,
    phase: Phase,
    previous_fingerprint: Fingerprint | None = None,
) -> VerificationReport:
    """Nucleo puro: sin S3, sin SNS, sin DynamoDB. Es lo que prueban los tests."""
    rules = get_dataset_rules(rules_path, dataset)
    table = engine.table_ref(rules)

    results = []
    for assertion in rules.compile(table, business_date, expected_rows):
        try:
            observed = engine.scalar(assertion.sql)
        except Exception as exc:
            log_event(
                logger,
                "regla no evaluable",
                check_id=assertion.check_id,
                error=str(exc),
            )
            observed = "ERROR"
        results.append(assertion.evaluate(observed))

    fingerprint = engine.fingerprint(rules, business_date)

    drift: list[str] = []
    if phase is Phase.B_SCHEDULED and previous_fingerprint is not None:
        drift = fingerprint.differs_from(previous_fingerprint)

    return VerificationReport(
        run_id=run_id,
        dataset=dataset,
        business_date=business_date,
        phase=phase,
        results=results,
        fingerprint=fingerprint,
        drift=drift,
    )


def _previous_fingerprint(run_id: str, phase: Phase) -> Fingerprint | None:
    """Recupera del ledger la huella tomada en la fase A."""
    if phase is not Phase.B_SCHEDULED:
        return None
    record = ledger.get(run_id) or {}
    raw = record.get("fingerprint_a")
    return Fingerprint.from_dict(raw) if raw else None


def _persist(run_id: str, phase: Phase, report: VerificationReport) -> None:
    fields: dict[str, Any] = {
        f"report_{phase.name[0].lower()}": report.to_dict(),
    }
    if report.fingerprint:
        key = "fingerprint_a" if phase is Phase.A_POST_LOAD else "fingerprint_b"
        fields[key] = report.fingerprint.to_dict()

    if report.drift:
        status = RunStatus.DRIFT_DETECTED
    elif not report.passed:
        status = RunStatus.FAILED
    elif phase is Phase.A_POST_LOAD:
        status = RunStatus.LOADED
    else:
        status = RunStatus.VERIFIED

    ledger.update(run_id, status, **fields)


lambda_handler = handler
