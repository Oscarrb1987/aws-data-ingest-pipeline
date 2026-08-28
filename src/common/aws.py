"""Clientes boto3 con soporte de endpoint alternativo (LocalStack).

Centralizar la creacion de clientes evita repetir el `endpoint_url` en cada
modulo y permite que los tests sustituyan el factory con un solo parche.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import boto3
from botocore.config import Config

from src.common.config import get_settings

_BOTO_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "standard"},
    connect_timeout=5,
    read_timeout=60,
)


@cache
def client(service: str) -> Any:
    """Devuelve un cliente boto3 cacheado por servicio."""
    settings = get_settings()
    kwargs: dict[str, Any] = {"region_name": settings.region, "config": _BOTO_CONFIG}
    if settings.endpoint_url:
        kwargs["endpoint_url"] = settings.endpoint_url
    return boto3.client(service, **kwargs)


@cache
def resource(service: str) -> Any:
    """Devuelve un recurso boto3 cacheado por servicio."""
    settings = get_settings()
    kwargs: dict[str, Any] = {"region_name": settings.region, "config": _BOTO_CONFIG}
    if settings.endpoint_url:
        kwargs["endpoint_url"] = settings.endpoint_url
    return boto3.resource(service, **kwargs)


def reset_clients() -> None:
    """Limpia la cache de clientes (necesario entre tests con moto)."""
    client.cache_clear()
    resource.cache_clear()
