"""Lambda 1: validacion previa a la carga.

Es la puerta de entrada. Comprueba, sin desplegar un cluster y en cuestion de
segundos, que el fichero que ha dejado Datamap es el que dice ser:

  - existe el manifest y el CSV al que apunta
  - el checksum SHA-256 coincide (el fichero no se ha truncado ni corrompido)
  - el numero de filas coincide con lo declarado
  - la cabecera contiene todas las columnas obligatorias del contrato

Si algo falla, el fichero se mueve a `quarantine/` y la ejecucion termina ahi:
no se arranca el job de Glue, que es la parte cara del pipeline.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote_plus

from src.common import ledger, notifications, storage
from src.common.config import get_settings
from src.common.logging import get_logger, log_event
from src.common.models import Manifest, RunStatus
from src.common.rules import get_dataset_rules
from src.handlers.errors import ValidationFailed

logger = get_logger(__name__)


def extract_location(event: dict[str, Any]) -> tuple[str, str]:
    """Acepta tanto un evento de EventBridge como una invocacion directa."""
    if "detail" in event:
        detail = event["detail"]
        return detail["bucket"]["name"], unquote_plus(detail["object"]["key"])
    if "Records" in event:  # notificacion nativa de S3
        record = event["Records"][0]["s3"]
        return record["bucket"]["name"], unquote_plus(record["object"]["key"])
    if "bucket" in event and "manifest_key" in event:
        return event["bucket"], event["manifest_key"]
    raise ValidationFailed(f"evento no reconocido: claves {sorted(event)}")


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:  # noqa: ARG001
    settings = get_settings()
    bucket, manifest_key = extract_location(event)
    log_event(logger, "manifest recibido", bucket=bucket, key=manifest_key)

    manifest = Manifest.from_json(storage.get_bytes(bucket, manifest_key))
    data_key = manifest_key.replace(".manifest.json", ".csv")
    filename = data_key.rsplit("/", 1)[-1]

    run_id = ledger.new_run_id(manifest.dataset, manifest.business_date)
    ledger.register(
        run_id=run_id,
        dataset=manifest.dataset,
        business_date=manifest.business_date,
        source_key=data_key,
        manifest_key=manifest_key,
        expected_rows=manifest.row_count,
        source_system=manifest.source_system,
    )

    try:
        problems = _validate(bucket, data_key, manifest, settings.rules_path)
    except Exception as exc:
        _quarantine(bucket, data_key, manifest_key, manifest, run_id, [str(exc)])
        raise ValidationFailed(str(exc), run_id=run_id) from exc

    if problems:
        _quarantine(bucket, data_key, manifest_key, manifest, run_id, problems)
        raise ValidationFailed("; ".join(problems), run_id=run_id)

    ledger.update(run_id, RunStatus.VALIDATED, validated_at=manifest.generated_at)
    log_event(
        logger,
        "fichero validado",
        run_id=run_id,
        dataset=manifest.dataset,
        rows=manifest.row_count,
    )

    return {
        "run_id": run_id,
        "bucket": bucket,
        "dataset": manifest.dataset,
        "table": get_dataset_rules(settings.rules_path, manifest.dataset).table,
        "business_date": manifest.business_date,
        "source_key": data_key,
        "manifest_key": manifest_key,
        "expected_rows": manifest.row_count,
        "delimiter": manifest.delimiter,
        "filename": filename,
        "status": str(RunStatus.VALIDATED),
    }


def _validate(bucket: str, data_key: str, manifest: Manifest, rules_path: str) -> list[str]:
    """Devuelve la lista de incumplimientos (vacia si el fichero es correcto)."""
    problems: list[str] = []

    if not storage.exists(bucket, data_key):
        return [f"el manifest apunta a {data_key}, que no existe en el bucket"]

    actual_sha = storage.sha256_of_object(bucket, data_key)
    if actual_sha != manifest.sha256:
        problems.append(
            f"checksum distinto: declarado {manifest.sha256[:12]}..., "
            f"calculado {actual_sha[:12]}..."
        )

    actual_rows = storage.count_data_lines(bucket, data_key, has_header=True)
    if actual_rows != manifest.row_count:
        problems.append(f"filas: declaradas {manifest.row_count}, encontradas {actual_rows}")

    header = storage.read_header(bucket, data_key, manifest.delimiter)
    if len(header) == 1 and manifest.delimiter != ";":
        problems.append(
            f"la cabecera no se separa con '{manifest.delimiter}'; revisa el delimitador"
        )

    rules = get_dataset_rules(rules_path, manifest.dataset)
    missing = [c for c in rules.required_columns if c not in header]
    if missing:
        problems.append(f"faltan columnas obligatorias en la cabecera: {missing}")

    unexpected = [c for c in header if c and c not in rules.column_names]
    if unexpected:
        problems.append(f"columnas no declaradas en el contrato: {unexpected}")

    return problems


def _quarantine(
    bucket: str,
    data_key: str,
    manifest_key: str,
    manifest: Manifest,
    run_id: str,
    problems: list[str],
) -> None:
    settings = get_settings()
    filename = data_key.rsplit("/", 1)[-1]
    dest = settings.quarantine_key(manifest.dataset, manifest.business_date, filename)

    for src, dst in ((data_key, dest), (manifest_key, dest.replace(".csv", ".manifest.json"))):
        try:
            storage.move(bucket, src, dst)
        except Exception:  # pragma: no cover - el fichero puede no existir
            logger.warning("no se pudo mover a cuarentena: %s", src)

    detail = "\n".join(f"- {p}" for p in problems)
    storage.put_text(bucket, dest + ".motivo.txt", detail + "\n")

    ledger.update(
        run_id,
        RunStatus.QUARANTINED,
        quarantine_key=dest,
        problems=problems,
    )
    notifications.notify_failure(
        manifest.dataset,
        manifest.business_date,
        "fichero rechazado en la validacion previa",
        f"Fichero: s3://{bucket}/{data_key}\nCuarentena: s3://{bucket}/{dest}\n\n{detail}",
    )
    log_event(logger, "fichero en cuarentena", run_id=run_id, problems=problems)


# Alias esperado por el runtime de Lambda
lambda_handler = handler

if __name__ == "__main__":  # pragma: no cover - ayuda para pruebas manuales
    import json
    import sys

    print(json.dumps(handler(json.loads(sys.argv[1])), indent=2, ensure_ascii=False))
