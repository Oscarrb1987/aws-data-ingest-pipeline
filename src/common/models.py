"""Modelos de dominio del pipeline.

Todo lo que viaja entre estados de Step Functions se serializa desde estas
dataclasses, de modo que el contrato entre Lambdas este definido en un unico
sitio y sea testeable sin AWS.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    """Estados por los que pasa una ejecucion en el ledger."""

    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    QUARANTINED = "QUARANTINED"
    TRANSFORMING = "TRANSFORMING"
    LOADED = "LOADED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    DRIFT_DETECTED = "DRIFT_DETECTED"


class Severity(StrEnum):
    """Gravedad de una regla de calidad."""

    CRITICAL = "critical"
    WARNING = "warning"


class Phase(StrEnum):
    """Las dos comprobaciones que sustituyen al trabajo manual.

    A: justo despues de que el job de transformacion termina.
    B: pasada la hora programada, para detectar reprocesos o llegadas tardias.
    """

    A_POST_LOAD = "A_POST_LOAD"
    B_SCHEDULED = "B_SCHEDULED"


def utcnow() -> str:
    """Timestamp ISO-8601 en UTC, con sufijo Z."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(slots=True)
class Manifest:
    """Contrato que acompana a cada CSV.

    Sin manifest no hay carga: es lo que permite comprobar que el fichero que
    llega es exactamente el que el origen dice haber generado.
    """

    dataset: str
    business_date: str
    row_count: int
    sha256: str
    source_system: str = "sistema-origen"
    delimiter: str = ","
    encoding: str = "utf-8"
    columns: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utcnow)

    @classmethod
    def from_json(cls, raw: str | bytes) -> Manifest:
        data = json.loads(raw)
        missing = {"dataset", "business_date", "row_count", "sha256"} - data.keys()
        if missing:
            raise ValueError(f"manifest incompleto, faltan campos: {sorted(missing)}")
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CheckResult:
    """Resultado de una regla de calidad."""

    check_id: str
    passed: bool
    severity: Severity
    observed: Any
    expected: Any
    message: str
    sql: str | None = None

    @property
    def blocking(self) -> bool:
        """Una regla critica que falla detiene el pipeline."""
        return not self.passed and self.severity is Severity.CRITICAL

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = str(self.severity)
        return d


@dataclass(slots=True)
class Fingerprint:
    """Huella de una particion, para comparar la verificacion B contra la A.

    Si la huella cambia entre ambas, alguien ha reprocesado o pisado los datos
    despues de que los diesemos por buenos.
    """

    row_count: int
    numeric_checksum: float
    distinct_keys: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fingerprint:
        return cls(
            row_count=int(data["row_count"]),
            numeric_checksum=float(data["numeric_checksum"]),
            distinct_keys=int(data["distinct_keys"]),
        )

    def differs_from(self, other: Fingerprint, tolerance: float = 0.01) -> list[str]:
        """Devuelve la lista de diferencias encontradas (vacia si son iguales)."""
        diffs: list[str] = []
        if self.row_count != other.row_count:
            diffs.append(f"row_count {other.row_count} -> {self.row_count}")
        if abs(self.numeric_checksum - other.numeric_checksum) > tolerance:
            diffs.append(
                f"numeric_checksum {other.numeric_checksum:.2f} -> {self.numeric_checksum:.2f}"
            )
        if self.distinct_keys != other.distinct_keys:
            diffs.append(f"distinct_keys {other.distinct_keys} -> {self.distinct_keys}")
        return diffs


@dataclass(slots=True)
class VerificationReport:
    """Salida de una fase de verificacion, apta para S3 y para SNS."""

    run_id: str
    dataset: str
    business_date: str
    phase: Phase
    results: list[CheckResult]
    fingerprint: Fingerprint | None = None
    drift: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utcnow)

    @property
    def passed(self) -> bool:
        return not any(r.blocking for r in self.results) and not self.drift

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset": self.dataset,
            "business_date": self.business_date,
            "phase": str(self.phase),
            "passed": self.passed,
            "generated_at": self.generated_at,
            "checks_total": len(self.results),
            "checks_failed": len(self.failed_checks),
            "drift": self.drift,
            "fingerprint": self.fingerprint.to_dict() if self.fingerprint else None,
            "results": [r.to_dict() for r in self.results],
        }

    def to_markdown(self) -> str:
        """Version legible del informe, la que se adjunta a la alerta."""
        icon = "OK" if self.passed else "KO"
        lines = [
            f"# Verificacion {self.phase} [{icon}]",
            "",
            f"- **run_id**: `{self.run_id}`",
            f"- **dataset**: `{self.dataset}`",
            f"- **fecha de negocio**: `{self.business_date}`",
            f"- **generado**: {self.generated_at}",
            "",
            "| Regla | Resultado | Observado | Esperado |",
            "| --- | --- | --- | --- |",
        ]
        for r in self.results:
            mark = "PASS" if r.passed else f"FAIL ({r.severity})"
            lines.append(f"| `{r.check_id}` | {mark} | {r.observed} | {r.expected} |")
        if self.drift:
            lines += ["", "## Divergencia detectada frente a la verificacion A", ""]
            lines += [f"- {d}" for d in self.drift]
        return "\n".join(lines) + "\n"
