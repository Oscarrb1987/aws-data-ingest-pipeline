"""Operaciones sobre S3 usadas por el pipeline."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.common.aws import client

_CHUNK = 1024 * 1024


def get_bytes(bucket: str, key: str) -> bytes:
    return client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()


def get_json(bucket: str, key: str) -> dict[str, Any]:
    return json.loads(get_bytes(bucket, key))


def put_bytes(bucket: str, key: str, body: bytes, content_type: str) -> None:
    client("s3").put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)


def put_json(bucket: str, key: str, payload: dict[str, Any]) -> None:
    put_bytes(
        bucket,
        key,
        json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
        "application/json",
    )


def put_text(bucket: str, key: str, text: str, content_type: str = "text/plain") -> None:
    put_bytes(bucket, key, text.encode("utf-8"), content_type)


def exists(bucket: str, key: str) -> bool:
    try:
        client("s3").head_object(Bucket=bucket, Key=key)
    except client("s3").exceptions.ClientError:
        return False
    except Exception:
        return False
    return True


def sha256_of_object(bucket: str, key: str) -> str:
    """Checksum en streaming: no carga el fichero entero en memoria.

    Importante porque las Lambdas tienen memoria limitada y los ficheros de
    Datamap pueden superar el gigabyte.
    """
    digest = hashlib.sha256()
    body = client("s3").get_object(Bucket=bucket, Key=key)["Body"]
    for chunk in iter(lambda: body.read(_CHUNK), b""):
        digest.update(chunk)
    return digest.hexdigest()


def count_data_lines(bucket: str, key: str, has_header: bool = True) -> int:
    """Cuenta lineas de datos del CSV sin materializarlo en memoria."""
    body = client("s3").get_object(Bucket=bucket, Key=key)["Body"]
    lines = 0
    tail = b""
    for chunk in iter(lambda: body.read(_CHUNK), b""):
        buf = tail + chunk
        lines += buf.count(b"\n")
        tail = buf[buf.rfind(b"\n") + 1 :] if b"\n" in buf else buf
    if tail.strip():
        lines += 1  # ultima linea sin salto final
    return max(lines - 1, 0) if has_header else lines


def read_header(
    bucket: str, key: str, delimiter: str = ",", max_bytes: int = 64 * 1024
) -> list[str]:
    """Lee solo la primera linea usando un Range request."""
    obj = client("s3").get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{max_bytes - 1}")
    first = obj["Body"].read().split(b"\n", 1)[0]
    text = first.decode("utf-8-sig", errors="replace").strip().strip("\r")
    return [c.strip().strip('"').lower() for c in text.split(delimiter)]


def move(bucket: str, src_key: str, dst_key: str) -> None:
    s3 = client("s3")
    s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": src_key}, Key=dst_key)
    s3.delete_object(Bucket=bucket, Key=src_key)


def list_keys(bucket: str, prefix: str) -> list[str]:
    paginator = client("s3").get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    return keys
