"""Excepciones de dominio.

Step Functions enruta por el nombre de la excepcion, asi que cada fallo
esperado tiene su propio tipo y la maquina de estados puede reaccionar de
forma distinta a un fichero corrupto y a una regla de calidad incumplida.

Ademas llevan el `run_id` para que quien capture el error pueda ir al ledger
sin tener que reconstruir el contexto.
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base de todos los fallos controlados del pipeline."""

    def __init__(self, message: str, *, run_id: str | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id


class ValidationFailed(PipelineError):
    """El fichero no cumple el contrato: se envia a cuarentena."""


class VerificationFailed(PipelineError):
    """Los datos se cargaron pero incumplen alguna regla critica."""


class DriftDetected(PipelineError):
    """Los datos cambiaron entre la verificacion A y la B."""
