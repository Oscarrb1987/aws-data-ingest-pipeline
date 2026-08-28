#!/usr/bin/env python3
"""Genera el diagrama de arquitectura como SVG.

El diagrama es codigo, no una imagen suelta: si cambia la arquitectura se
regenera y no se queda desfasado en el README. Produce tres salidas desde una
sola definicion de geometria:

  docs/aws-architecture.svg       colores fijos, para tema claro
  docs/aws-architecture-dark.svg  colores fijos, para tema oscuro
  docs/_architecture-fragment.svg colores por variable CSS, para incrustar

Ejecutar: python scripts/make_architecture_svg.py
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs"
W, H = 1200, 830

SANS = "'Source Sans 3', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, 'SFMono-Regular', Menlo, monospace"

# Categoria de servicio -> clave de color. La categoria es informacion: dice
# que tipo de servicio es cada caja, y por eso la leyenda se gana su sitio.
LIGHT = {
    "bg": "#FBFAFD",
    "surface": "#FFFFFF",
    "ink": "#1A1726",
    "muted": "#5D5872",
    "line": "#DFDCEA",
    "conn": "#8B85A3",
    "storage": "#4F7A0C",
    "integration": "#C4106A",
    "compute": "#BE5405",
    "analytics": "#6A2FD4",
    "db": "#9C1CA8",
    "obs": "#A81E38",
}

DARK = {
    "bg": "#131120",
    "surface": "#1D1A31",
    "ink": "#EDEAF7",
    "muted": "#A29CBE",
    "line": "#332E4E",
    "conn": "#7C7597",
    "storage": "#9ECC3E",
    "integration": "#FF74B1",
    "compute": "#FF9F45",
    "analytics": "#B896FF",
    "db": "#E97CF2",
    "obs": "#FF8FA0",
}

TOKENS = {k: f"var(--d-{k})" for k in LIGHT}


# --------------------------------------------------------------- primitivas


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(
    x: float,
    y: float,
    content: str,
    *,
    size: float = 11,
    fill: str,
    weight: int = 400,
    anchor: str = "start",
    family: str = SANS,
    opacity: float | None = None,
) -> str:
    extra = f' opacity="{opacity}"' if opacity is not None else ""
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{extra}>'
        f"{esc(content)}</text>"
    )


def node(
    c: dict[str, str],
    x: float,
    y: float,
    w: float,
    h: float,
    color_key: str,
    title: str,
    lines: list[str],
    *,
    badge: str | None = None,
    dashed: bool = False,
) -> str:
    """Caja de servicio: borde en el color de su categoria, texto neutro."""
    stroke = c[color_key]
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
        f'fill="{c["surface"]}" stroke="{stroke}" stroke-width="1.6"{dash}/>',
        text(x + 14, y + 28, title, size=13, weight=600, fill=c["ink"]),
    ]
    for i, line in enumerate(lines):
        family = MONO if line.endswith("/") or "·" in line else SANS
        parts.append(text(x + 14, y + 48 + i * 16, line, size=10.5, fill=c["muted"], family=family))
    if badge:
        parts.append(
            text(
                x + w - 12,
                y + 26,
                badge,
                size=11,
                weight=600,
                fill=stroke,
                anchor="end",
                family=MONO,
            )
        )
    return "".join(parts)


def arrow(c: dict[str, str], d: str, *, dashed: bool = False) -> str:
    dash = ' stroke-dasharray="5 5"' if dashed else ""
    return (
        f'<path d="{d}" fill="none" stroke="{c["conn"]}" stroke-width="1.5"'
        f'{dash} marker-end="url(#punta)"/>'
    )


def label(c: dict[str, str], x: float, y: float, content: str, anchor: str = "middle") -> str:
    return text(x, y, content, size=10.5, fill=c["muted"], anchor=anchor)


# ------------------------------------------------------------------ dibujo


def body(c: dict[str, str]) -> str:
    p: list[str] = []

    # --- disparo -----------------------------------------------------------
    p.append(node(c, 70, 48, 250, 76, "storage", "Amazon S3", ["landing/", "CSV y su manifest"]))
    p.append(arrow(c, "M 320 86 H 394"))
    p.append(label(c, 357, 78, "Object Created"))
    p.append(
        node(
            c,
            400,
            48,
            250,
            76,
            "integration",
            "Amazon EventBridge",
            ["regla: landing/*.manifest.json"],
        )
    )
    p.append(arrow(c, "M 525 124 V 180"))
    p.append(label(c, 535, 158, "StartExecution", anchor="start"))

    # --- leyenda -----------------------------------------------------------
    p.append(
        f'<rect x="760" y="32" width="370" height="116" rx="10" fill="none" '
        f'stroke="{c["line"]}" stroke-width="1.2"/>'
    )
    p.append(text(780, 54, "CATEGORÍA DE SERVICIO", size=9.5, weight=600, fill=c["muted"]))
    leyenda = [
        (782, 78, "storage", "Almacenamiento"),
        (782, 104, "compute", "Cómputo"),
        (782, 130, "integration", "Integración"),
        (962, 78, "analytics", "Analítica"),
        (962, 104, "db", "Base de datos"),
        (962, 130, "obs", "Observabilidad"),
    ]
    for cx, cy, key, nombre in leyenda:
        p.append(f'<circle cx="{cx}" cy="{cy - 4}" r="5" fill="{c[key]}"/>')
        p.append(text(cx + 14, cy, nombre, size=11, fill=c["ink"]))

    # --- maquina de estados ------------------------------------------------
    p.append(
        f'<rect x="70" y="186" width="1060" height="286" rx="14" fill="none" '
        f'stroke="{c["integration"]}" stroke-width="1.6" stroke-dasharray="7 5"/>'
    )
    p.append(text(90, 216, "AWS Step Functions", size=14, weight=600, fill=c["integration"]))
    p.append(
        text(
            90,
            234,
            "orquesta el proceso entero, incluida la espera hasta la hora acordada",
            size=10.5,
            fill=c["muted"],
        )
    )

    pasos = [
        (100, "compute", "AWS Lambda", ["validar fichero"], "1"),
        (306, "analytics", "AWS Glue", ["ETL a Parquet"], "2"),
        (512, "compute", "AWS Lambda", ["verificar carga A"], "3"),
        (718, "integration", "Estado Wait", ["espera sin cómputo"], "4"),
        (924, "compute", "AWS Lambda", ["verificar carga B"], "5"),
    ]
    for x, key, titulo, lineas, badge in pasos:
        p.append(node(c, x, 252, 176, 76, key, titulo, lineas, badge=badge))
    for x0 in (276, 482, 688, 894):
        p.append(arrow(c, f"M {x0} 290 H {x0 + 24}"))

    centros = [188, 394, 600, 806, 1012]
    for cx in centros:
        p.append(
            f'<path d="M {cx} 328 V 352" fill="none" stroke="{c["conn"]}" '
            f'stroke-width="1.2" stroke-dasharray="4 4"/>'
        )
    p.append(
        f'<path d="M 188 352 H 1012" fill="none" stroke="{c["conn"]}" '
        f'stroke-width="1.2" stroke-dasharray="4 4"/>'
    )
    p.append(arrow(c, "M 600 352 V 386", dashed=True))
    p.append(label(c, 614, 374, "Catch: cualquier fallo", anchor="start"))
    p.append(node(c, 490, 392, 220, 64, "compute", "AWS Lambda", ["notificar fallo"]))

    # --- del pipeline a los servicios de datos -----------------------------
    p.append(arrow(c, "M 215 472 V 540"))
    p.append(label(c, 215, 516, "escribe datos"))
    p.append(arrow(c, "M 815 472 V 540"))
    p.append(label(c, 815, 516, "consulta SQL"))
    p.append(arrow(c, "M 1050 472 V 540"))
    p.append(label(c, 1050, 516, "registra estado"))
    p.append(arrow(c, "M 940 472 V 694", dashed=True))
    p.append(label(c, 940, 516, "envía logs"))

    # --- almacenamiento y consulta -----------------------------------------
    p.append(
        node(
            c,
            70,
            546,
            270,
            76,
            "storage",
            "Amazon S3",
            ["curated/ · quarantine/ · reports/", "Parquet particionado por fecha"],
        )
    )
    p.append(arrow(c, "M 340 584 H 394"))
    p.append(label(c, 370, 576, "ubicación"))
    p.append(
        node(
            c,
            400,
            546,
            240,
            76,
            "analytics",
            "AWS Glue Data Catalog",
            ["proyección de particiones"],
        )
    )
    p.append(arrow(c, "M 640 584 H 694"))
    p.append(label(c, 670, 576, "esquema"))
    p.append(node(c, 700, 546, 210, 76, "analytics", "Amazon Athena", ["ejecuta las reglas"]))
    p.append(node(c, 970, 546, 160, 76, "db", "Amazon DynamoDB", ["ledger de", "ejecuciones"]))

    # --- aviso, observabilidad y despliegue --------------------------------
    p.append(arrow(c, "M 490 424 H 36 V 738 H 64", dashed=True))
    p.append(label(c, 44, 508, "alerta", anchor="start"))
    p.append(node(c, 70, 700, 250, 76, "integration", "Amazon SNS", ["alerta a correo o Slack"]))
    p.append(
        node(
            c,
            380,
            700,
            300,
            76,
            "muted",
            "AWS CDK → CloudFormation",
            ["despliega los dos stacks"],
            dashed=True,
        )
    )
    p.append(
        node(
            c,
            800,
            700,
            330,
            76,
            "obs",
            "Amazon CloudWatch",
            ["logs estructurados, métricas y alarmas"],
        )
    )

    return "".join(p)


def render(c: dict[str, str], *, standalone: bool, aria: str) -> str:
    defs = (
        f'<defs><marker id="punta" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c["conn"]}"/></marker></defs>'
    )
    fondo = f'<rect width="{W}" height="{H}" fill="{c["bg"]}"/>' if standalone else ""
    cabecera = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img" aria-label="{esc(aria)}">'
        if standalone
        else (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'role="img" aria-label="{esc(aria)}">'
        )
    )
    return cabecera + defs + fondo + body(c) + "</svg>\n"


ARIA = (
    "Arquitectura del pipeline en AWS: S3 y EventBridge disparan una maquina de estados "
    "de Step Functions que valida con Lambda, transforma con Glue y verifica dos veces "
    "consultando Athena sobre el Glue Data Catalog, registrando cada paso en DynamoDB y "
    "avisando por SNS, con CloudWatch como observabilidad."
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    salidas = {
        "aws-architecture.svg": render(LIGHT, standalone=True, aria=ARIA),
        "aws-architecture-dark.svg": render(DARK, standalone=True, aria=ARIA),
        "_architecture-fragment.svg": render(TOKENS, standalone=False, aria=ARIA),
    }
    for nombre, contenido in salidas.items():
        (OUT / nombre).write_text(contenido, encoding="utf-8")
        print(f"  {nombre}  ({len(contenido)} bytes)")


if __name__ == "__main__":
    main()
