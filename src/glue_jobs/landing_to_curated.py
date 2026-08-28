"""Job de AWS Glue: landing (CSV) -> curated (Parquet particionado).

Equivalente al job de Databricks del proceso original. Hace lo minimo
imprescindible y de forma idempotente:

  1. lee el CSV de landing con el esquema del contrato (nunca por inferencia:
     la inferencia hace que el mismo fichero se cargue distinto segun el dia)
  2. normaliza tipos y espacios
  3. anade la columna de particion `dt` y metadatos de trazabilidad
  4. sobrescribe UNICAMENTE la particion de esa fecha de negocio

El punto 4 es lo que permite reejecutar el job sin duplicar datos: con
`partitionOverwriteMode=dynamic`, volver a lanzarlo deja la particion como si
fuese la primera vez.

Ejecucion:
    aws glue start-job-run --job-name dataflow-landing-to-curated \\
        --arguments '{"--dataset":"clientes","--business_date":"2026-08-27", ...}'
"""

from __future__ import annotations

import sys

from awsglue.context import GlueContext  # type: ignore[import-not-found]
from awsglue.job import Job  # type: ignore[import-not-found]
from awsglue.utils import getResolvedOptions  # type: ignore[import-not-found]
from pyspark.context import SparkContext  # type: ignore[import-not-found]
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

_TYPES = {
    "string": StringType(),
    "int": IntegerType(),
    "integer": IntegerType(),
    "double": DoubleType(),
    "date": DateType(),
    "timestamp": TimestampType(),
}

ARGS = [
    "JOB_NAME",
    "dataset",
    "business_date",
    "run_id",
    "source_path",
    "target_path",
    "rules_path",
    "delimiter",
]


def build_schema(columns: list[dict]) -> StructType:
    """Esquema explicito a partir del contrato YAML."""
    return StructType(
        [
            StructField(c["name"], _TYPES.get(c.get("type", "string"), StringType()), True)
            for c in columns
        ]
    )


def normalize(df: DataFrame, columns: list[dict]) -> DataFrame:
    """Recorta espacios y convierte cadenas vacias en null.

    Un `""` y un `NULL` son la misma cosa para el negocio, pero distintos para
    una regla `not_null`. Normalizarlo aqui evita falsos positivos aguas abajo.
    """
    for col in columns:
        name = col["name"]
        if col.get("type", "string") == "string":
            trimmed = F.trim(F.col(name))
            df = df.withColumn(name, F.when(trimmed == "", None).otherwise(trimmed))
    return df


def main() -> None:
    args = getResolvedOptions(sys.argv, ARGS)

    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)
    spark: SparkSession = glue_context.spark_session
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)

    # Sobrescribe solo las particiones afectadas, no la tabla entera.
    spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")
    spark.conf.set("spark.sql.parquet.compression.codec", "snappy")

    import boto3
    import yaml

    bucket, key = args["rules_path"].replace("s3://", "").split("/", 1)
    contract = yaml.safe_load(boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read())
    columns = contract["datasets"][args["dataset"]]["schema"]

    df = (
        spark.read.option("header", "true")
        .option("sep", args["delimiter"])
        .option("mode", "PERMISSIVE")
        .option("encoding", "UTF-8")
        .schema(build_schema(columns))
        .csv(args["source_path"])
    )

    df = normalize(df, columns)

    # Trazabilidad: cada fila sabe de que ejecucion viene.
    df = (
        df.withColumn("dt", F.lit(args["business_date"]))
        .withColumn("_run_id", F.lit(args["run_id"]))
        .withColumn("_ingested_at", F.current_timestamp())
    )

    row_count = df.count()
    print(f"[dataflow] dataset={args['dataset']} dt={args['business_date']} filas={row_count}")

    (
        df.repartition(1)
        .write.mode("overwrite")
        .partitionBy("dt")
        .format("parquet")
        .save(args["target_path"])
    )

    job.commit()


if __name__ == "__main__":
    main()
