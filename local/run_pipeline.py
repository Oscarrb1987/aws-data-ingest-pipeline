#!/usr/bin/env python3
"""Ejecuta el pipeline completo en local, sin cuenta de AWS.

Reproduce paso a paso la maquina de estados de Step Functions:

    ValidarFichero -> TransformarConGlue -> VerificarCargaA
                   -> EsperarHoraProgramada -> VerificarCargaB

Los unicos dos elementos sustituidos son los que LocalStack community no
ofrece: Glue (lo hace DuckDB con las mismas reglas de esquema) y Athena (lo
hace DuckDB ejecutando el mismo SQL). Todo lo demas -S3, DynamoDB, SNS,
validaciones, reglas, ledger, informes- es el codigo que se despliega.

Uso:
    python local/run_pipeline.py --file sample_data/clientes_ok.csv
    python local/run_pipeline.py --file sample_data/clientes_ko.csv
    python local/run_pipeline.py --file sample_data/clientes_ok.csv --simulate-drift
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from local import env  # noqa: E402

env.configure()

from src.common import ledger, storage  # noqa: E402  (el entorno debe fijarse antes)
from src.common.config import get_settings  # noqa: E402
from src.common.models import Manifest, Phase, RunStatus  # noqa: E402
from src.common.rules import get_dataset_rules  # noqa: E402
from src.engines.duckdb_engine import DuckDBEngine  # noqa: E402
from src.handlers import notify_failure, schedule, validate_file, verify_load  # noqa: E402
from src.handlers.errors import PipelineError, ValidationFailed  # noqa: E402
from src.transform import run_local_transform  # noqa: E402

SEP = "-" * 72


def step(n: int, title: str) -> None:
    print(f"\n{SEP}\n[{n}] {title}\n{SEP}")


def upload(csv_path: Path) -> tuple[str, str, Manifest]:
    """Sube CSV y manifest a landing/, como haria el proceso de Datamap."""
    settings = get_settings()
    manifest_path = csv_path.with_suffix("").with_suffix(".manifest.json")
    if not manifest_path.exists():
        manifest_path = csv_path.parent / (csv_path.stem + ".manifest.json")

    manifest = Manifest.from_json(manifest_path.read_bytes())
    data_key = settings.landing_key(manifest.dataset, manifest.business_date, csv_path.name)
    manifest_key = data_key.replace(".csv", ".manifest.json")

    storage.put_bytes(settings.data_bucket, data_key, csv_path.read_bytes(), "text/csv")
    storage.put_bytes(
        settings.data_bucket, manifest_key, manifest_path.read_bytes(), "application/json"
    )
    print(f"  subido s3://{settings.data_bucket}/{data_key}")
    print(f"  subido s3://{settings.data_bucket}/{manifest_key}")
    return data_key, manifest_key, manifest


def simulate_drift(warehouse: Path, table: str, business_date: str) -> None:
    """Duplica un fichero de la particion: como un reproceso que pisa datos."""
    partition = warehouse / table / f"dt={business_date}"
    files = sorted(partition.glob("*.parquet"))
    if not files:
        print("  (no hay particion que alterar)")
        return
    shutil.copy(files[0], partition / "part-reproceso.parquet")
    print(f"  se ha inyectado un fichero extra en {partition.name} (simula un reproceso)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline de ingesta y verificacion en local")
    parser.add_argument("--file", default="sample_data/clientes_ok.csv", help="CSV a cargar")
    parser.add_argument("--dataset", default="clientes")
    parser.add_argument(
        "--simulate-drift",
        action="store_true",
        help="Altera la particion entre la verificacion A y la B",
    )
    parser.add_argument("--wait", type=int, default=5, help="Segundos de espera antes de la fase B")
    args = parser.parse_args()

    env.resolve_alert_topic()
    settings = get_settings()
    csv_path = (ROOT / args.file).resolve()
    if not csv_path.exists():
        print(f"No existe {csv_path}")
        return 1

    state: dict = {}
    try:
        # --------------------------------------------------- 0. Subida
        step(0, "Datamap deposita el CSV y su manifest en landing/")
        data_key, manifest_key, manifest = upload(csv_path)
        print(
            f"  dataset={manifest.dataset} fecha={manifest.business_date} "
            f"filas declaradas={manifest.row_count}"
        )

        # ----------------------------------- 1. ValidarFichero (Lambda)
        step(1, "ValidarFichero: checksum, filas y cabecera frente al manifest")
        event = {
            "detail": {
                "bucket": {"name": settings.data_bucket},
                "object": {"key": manifest_key},
            }
        }
        state = validate_file.handler(event)
        print(f"  OK  run_id={state['run_id']}  filas esperadas={state['expected_rows']}")

        # ------------------------------- 2. TransformarConGlue (DuckDB)
        step(2, "TransformarConGlue: CSV -> Parquet particionado en curated/")
        rules = get_dataset_rules(settings.rules_path, state["dataset"])
        rows = run_local_transform(
            bucket=state["bucket"],
            source_key=state["source_key"],
            rules=rules,
            business_date=state["business_date"],
            run_id=state["run_id"],
            warehouse=settings.local_warehouse,
            delimiter=state.get("delimiter", ","),
        )
        ledger.update(state["run_id"], RunStatus.TRANSFORMING, rows_written=rows)
        print(f"  escritas {rows} filas en {settings.local_warehouse}/{rules.table}")

        # ----------------------------------- 3. VerificarCargaA (Lambda)
        step(3, "VerificarCargaA: comprobacion inmediata tras la carga")
        state = verify_load.handler({**state, "phase": str(Phase.A_POST_LOAD)})
        print(f"  OK  informe: {state['report_uri']}")
        print(f"  huella: {json.dumps(state['fingerprint'])}")

        # ---------------------------- 4. CalcularHora + Wait (SFN Wait)
        step(4, "EsperarHoraProgramada: en AWS es un estado Wait, aqui unos segundos")
        state = schedule.handler(state)
        print(f"  verificacion B programada para {state['verify_b_at']}")

        if args.simulate_drift:
            simulate_drift(Path(settings.local_warehouse), rules.table, state["business_date"])

        for remaining in range(args.wait, 0, -1):
            print(f"  esperando... {remaining}s ", end="\r", flush=True)
            time.sleep(1)
        print(" " * 40, end="\r")

        # ----------------------------------- 5. VerificarCargaB (Lambda)
        step(5, "VerificarCargaB: comprobacion diferida y comparacion de huella")
        state = verify_load.handler({**state, "phase": str(Phase.B_SCHEDULED)})
        print(f"  OK  informe: {state['report_uri']}")

    except PipelineError as exc:
        step(99, f"La maquina de estados entra en el Catch: {type(exc).__name__}")
        state.setdefault("run_id", exc.run_id)
        state.setdefault("dataset", args.dataset)
        print(f"  motivo: {exc}")

        if isinstance(exc, ValidationFailed):
            # Igual que en la maquina de estados: la validacion previa ya movio
            # el fichero a cuarentena y aviso, asi que aqui solo se cierra.
            print("  -> estado FicheroRechazado (el fichero ya esta en quarantine/)")
        else:
            notify_failure.handler(
                {**state, "error": {"Error": type(exc).__name__, "Cause": str(exc)}}
            )
            print("  -> estado NotificarFallo")

        _resumen(state)
        print("\nEjecucion detenida a proposito: el pipeline hizo su trabajo.\n")
        return 2

    _resumen(state)
    print("\nCarga verificada de principio a fin.\n")
    return 0


def _resumen(state: dict) -> None:
    run_id = state.get("run_id")
    if not run_id:
        return
    record = ledger.get(run_id) or {}
    print(f"\n{SEP}\nRESUMEN DEL LEDGER (DynamoDB)\n{SEP}")
    for key in (
        "run_id",
        "dataset",
        "business_date",
        "status",
        "expected_rows",
        "rows_written",
        "fingerprint_a",
        "fingerprint_b",
        "problems",
        "error_type",
    ):
        if key in record:
            print(f"  {key:16} {record[key]}")

    engine = DuckDBEngine()
    try:
        rules = get_dataset_rules(get_settings().rules_path, record.get("dataset", "clientes"))
        table = engine.table_ref(rules)
        count = engine.scalar(
            f"SELECT COUNT(*) FROM {table} WHERE {rules.partition_filter(record['business_date'])}"
        )
        print(f"  {'filas en curated':16} {count}")
    except Exception:
        print(f"  {'filas en curated':16} (particion no creada)")
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
