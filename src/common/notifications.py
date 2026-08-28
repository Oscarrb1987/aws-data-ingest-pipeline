"""Publicacion de alertas en SNS.

El topic se suscribe a correo o a un webhook de Slack/Teams: es el aviso que
hoy se sustituye por "entrar a mirar si esta cargado".
"""

from __future__ import annotations

from src.common.aws import client
from src.common.config import get_settings
from src.common.logging import get_logger
from src.common.models import VerificationReport

logger = get_logger(__name__)

_MAX_SNS_BYTES = 250_000


def publish(subject: str, message: str, attributes: dict[str, str] | None = None) -> None:
    settings = get_settings()
    if not settings.alert_topic_arn:
        logger.warning("ALERT_TOPIC_ARN no configurado; alerta no enviada")
        return
    body = message.encode("utf-8")
    if len(body) > _MAX_SNS_BYTES:
        message = message[: _MAX_SNS_BYTES // 2] + "\n\n[...informe truncado, ver S3...]"
    client("sns").publish(
        TopicArn=settings.alert_topic_arn,
        Subject=subject[:100],
        Message=message,
        MessageAttributes={
            k: {"DataType": "String", "StringValue": v} for k, v in (attributes or {}).items()
        },
    )


def notify_report(report: VerificationReport, report_uri: str | None = None) -> None:
    state = "OK" if report.passed else "FALLO"
    subject = f"[{state}] {report.dataset} {report.business_date} - verificacion {report.phase}"
    body = report.to_markdown()
    if report_uri:
        body += f"\nInforme completo: {report_uri}\n"
    publish(
        subject,
        body,
        {
            "dataset": report.dataset,
            "phase": str(report.phase),
            "status": "ok" if report.passed else "failed",
        },
    )


def notify_failure(dataset: str, business_date: str, reason: str, detail: str = "") -> None:
    publish(
        f"[FALLO] {dataset} {business_date} - {reason}",
        f"Dataset: {dataset}\nFecha de negocio: {business_date}\nMotivo: {reason}\n\n{detail}\n",
        {"dataset": dataset, "status": "failed"},
    )
