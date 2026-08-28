"""Motores de consulta intercambiables para las verificaciones.

`AthenaEngine` en AWS, `DuckDBEngine` en la demo local. Las reglas y las
Lambdas dependen solo de la interfaz `QueryEngine`, de modo que se pueden
probar sin cuenta de AWS y sin cambiar una linea de la logica de negocio.
"""

from src.engines.base import QueryEngine
from src.engines.factory import get_engine

__all__ = ["QueryEngine", "get_engine"]
