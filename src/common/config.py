"""Configuracion por variables de entorno.

Un unico objeto de configuracion sirve tanto a las Lambdas en AWS como al
runner local contra LocalStack; la unica diferencia es `endpoint_url`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class Settings:
    region: str
    data_bucket: str
    ledger_table: str
    alert_topic_arn: str | None
    endpoint_url: str | None
    query_engine: str
    glue_database: str
    glue_job_name: str
    athena_workgroup: str
    athena_output_location: str
    rules_path: str
    local_warehouse: str

    @property
    def is_local(self) -> bool:
        return bool(self.endpoint_url)

    def landing_key(self, dataset: str, business_date: str, filename: str) -> str:
        return f"landing/dataset={dataset}/dt={business_date}/{filename}"

    def curated_table_prefix(self, table: str) -> str:
        return f"curated/{table}/"

    def curated_prefix(self, table: str, business_date: str) -> str:
        return f"curated/{table}/dt={business_date}/"

    def quarantine_key(self, dataset: str, business_date: str, filename: str) -> str:
        return f"quarantine/dataset={dataset}/dt={business_date}/{filename}"

    def report_key(self, dataset: str, business_date: str, run_id: str, phase: str) -> str:
        return f"reports/dataset={dataset}/dt={business_date}/{run_id}_{phase}.json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Lee el entorno una sola vez por proceso (Lambda reutiliza el contenedor)."""
    return Settings(
        region=os.getenv("AWS_REGION", "eu-west-1"),
        data_bucket=os.environ.get("DATA_BUCKET", "datamap-datalake-local"),
        ledger_table=os.getenv("LEDGER_TABLE", "datamap-run-ledger"),
        alert_topic_arn=os.getenv("ALERT_TOPIC_ARN") or None,
        endpoint_url=os.getenv("AWS_ENDPOINT_URL") or None,
        query_engine=os.getenv("QUERY_ENGINE", "athena").lower(),
        glue_database=os.getenv("GLUE_DATABASE", "datamap_curated"),
        glue_job_name=os.getenv("GLUE_JOB_NAME", "datamap-landing-to-curated"),
        athena_workgroup=os.getenv("ATHENA_WORKGROUP", "datamap"),
        athena_output_location=os.getenv("ATHENA_OUTPUT_LOCATION", ""),
        rules_path=os.getenv("RULES_PATH", "rules/checks.yaml"),
        local_warehouse=os.getenv("LOCAL_WAREHOUSE", "local/out/warehouse"),
    )


def reset_settings_cache() -> None:
    """Util en tests, donde el entorno cambia entre casos."""
    get_settings.cache_clear()
