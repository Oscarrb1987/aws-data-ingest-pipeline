#!/usr/bin/env bash
#
# Empaqueta el codigo de las Lambdas en build/lambda/.
#
# Se hace con un script y no con el bundling de CDK a proposito: asi el
# `cdk synth` no necesita Docker y la CI puede validar la infraestructura en
# cualquier runner. boto3 no se incluye porque ya viene en el runtime.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${ROOT}/build/lambda"

echo "==> Limpiando ${BUILD}"
rm -rf "${BUILD}"
mkdir -p "${BUILD}"

echo "==> Copiando codigo de la aplicacion"
cp -r "${ROOT}/src" "${BUILD}/src"
cp -r "${ROOT}/rules" "${BUILD}/rules"

# El job de Glue se ejecuta en Spark, no en Lambda: fuera del paquete.
rm -rf "${BUILD}/src/glue_jobs"
# DuckDB solo se usa en la demo local.
rm -f "${BUILD}/src/engines/duckdb_engine.py"
rm -rf "${BUILD}/src/transform"

echo "==> Instalando dependencias de runtime"
python -m pip install \
  --quiet \
  --no-warn-conflicts \
  --disable-pip-version-check \
  --target "${BUILD}" \
  --platform manylinux2014_aarch64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  "PyYAML==6.0.2"

echo "==> Limpiando artefactos innecesarios"
find "${BUILD}" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "${BUILD}" -type d -name "*.dist-info" -prune -exec rm -rf {} + 2>/dev/null || true
find "${BUILD}" -type f -name "*.pyc" -delete 2>/dev/null || true

echo "==> Paquete listo: ${BUILD} ($(du -sh "${BUILD}" | cut -f1))"
