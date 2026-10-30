"""Generador Markdown determinista de reportes de observabilidad."""

import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo


GENERATOR_VERSION = "observability_markdown:1.1.0"


def _text(value) -> str:
    """Presenta contenido externo como texto, sin ejecutar HTML o Markdown."""
    value = html.escape(str(value), quote=False)
    value = " ".join(value.split())
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>~-])", r"\\\1", value)


def _date(value: str, zone: ZoneInfo) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("El reporte contiene una fecha sin zona horaria")

    return instant.astimezone(zone).isoformat(timespec="seconds")


def _ids(values) -> str:
    return ", ".join(str(value) for value in sorted(values)) or "Ninguno"


def _quantity(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def render_report_markdown(data: dict) -> str:
    """Genera el mismo contenido para la misma selección y versión."""
    if data.get("schema_version") != "report_selection:1.0":
        raise ValueError("Versión de selección no soportada")

    request = data["request"]
    zone = ZoneInfo(request["timezone"])
    company = data["company"]

    findings = sorted(data["findings"], key=lambda item: item["id"])
    correlations = sorted(data["correlations"], key=lambda item: item["id"])
    executions = sorted(data["executions"], key=lambda item: item["id"])
    sources = {item["id"]: item for item in data["sources"]}

    lines = [
        "# Reporte de observabilidad",
        "",
        f"Empresa: {_text(company['name'])} — ID {company['id']}",
        "",
        (
            f"Período: {_date(request['period_start'], zone)} "
            f"hasta {_date(request['period_end'], zone)} "
            "(fin exclusivo)."
        ),
        "",
        f"Zona horaria de presentación: {_text(request['timezone'])}.",
        "",
        (
            "Las ventanas y los cortes presentados por el reporte usan esta "
            "zona horaria. Los textos históricos de especialistas y del "
            "coordinador conservan las fechas y zonas de su redacción original; "
            "Z y +00:00 indican UTC."
        ),
        "",
        "## Alcance",
        "",
        _text(data["scope_note"]),
        "",
        (
            "Resultados incluidos: "
            f"{_quantity(len(findings), 'hallazgo', 'hallazgos')} y "
            f"{_quantity(len(correlations), 'correlación', 'correlaciones')}."
        ),
        "",
        "Las correlaciones no se cuentan como incidentes adicionales.",
        "",
    ]

    for source in sorted(sources.values(), key=lambda item: item["id"]):
        resources = sorted({
            finding["resource_key"]
            for finding in findings
            if finding["source_id"] == source["id"]
        })
        lines.append(
            f"- Fuente {source['id']}: {_text(source['name'])}; "
            f"tecnología {_text(source['technology'])}; "
            f"recursos: {_text(', '.join(resources))}."
        )

    lines.extend(["", "## Hallazgos", ""])

    for finding in findings:
        source = sources[finding["source_id"]]
        lines.extend([
            f"### Hallazgo {finding['id']}: {_text(finding['resource_key'])}",
            "",
            (
                f"Tecnología: {_text(source['technology'])}. "
                f"Clasificación: {_text(finding['classification'])}. "
                f"Severidad: {_text(finding['severity'])}."
            ),
            "",
            (
                f"Ventana: {_date(finding['start_at'], zone)} "
                f"hasta {_date(finding['end_at'], zone)}."
            ),
            "",
            "Interpretación guardada del especialista:",
            "",
            _text(finding["finding"]),
            "",
            f"Evidencias: {_ids(finding['evidence_ids'])}.",
            "",
            f"Eventos citados: {_ids(finding['event_ids'])}.",
            "",
        ])

        if finding["possible_implications"]:
            lines.extend([
                "Implicancias propuestas por el especialista; "
                "no son hechos confirmados:",
                "",
            ])
            lines.extend(
                f"- {_text(item)}"
                for item in finding["possible_implications"]
            )
            lines.append("")

    lines.extend(["## Correlaciones", ""])

    if not correlations:
        lines.extend([
            "No se seleccionaron correlaciones. Esto no demuestra "
            "ausencia de relaciones entre los resultados.",
            "",
        ])

    for correlation in correlations:
        proposal = correlation["proposal"]
        lines.extend([
            f"### Correlación {correlation['id']}",
            "",
            (
                f"Dependencia: {correlation['dependency_id']}. "
                f"Hallazgos: {_ids(proposal['finding_ids'])}."
            ),
            "",
            (
                f"Evaluación: {_text(proposal['assessment'])}. "
                f"Causalidad: {_text(proposal['causality'])}."
            ),
            "",
            "Interpretación guardada del coordinador:",
            "",
            _text(proposal["summary"]),
            "",
            f"Evidencias: {_ids(proposal['evidence_ids'])}.",
            "",
            f"Eventos citados: {_ids(proposal['event_ids'])}.",
            "",
            "Coincidencias entre ventanas de evidencias:",
            "",
        ])

        pairs = sorted(
            proposal["evidence_overlaps"],
            key=lambda item: (
                item["consumer_evidence_id"],
                item["provider_evidence_id"],
            ),
        )
        if not pairs:
            lines.append("- Ninguna en las evidencias seleccionadas.")

        for pair in pairs:
            lines.append(
                f"- Evidencia consumidora {pair['consumer_evidence_id']} "
                f"y proveedora {pair['provider_evidence_id']}."
            )

        lines.extend(["", "Limitaciones de la correlación:", ""])
        lines.extend(
            f"- {_text(item)}"
            for item in proposal["limitations"]
        )
        lines.append("")

    lines.extend(["## Cobertura y cortes de datos", ""])

    for execution in executions:
        lines.extend([
            f"### Ejecución {execution['id']}",
            "",
            (
                f"Perfil: {_text(execution['profile_code'])}, "
                f"versión {_text(execution['profile_version'])}. "
                f"Estado: {_text(execution['status'])}."
            ),
            "",
            (
                "Corte de recepción de datos: "
                f"{_date(execution['data_cutoff_at'], zone)}."
            ),
            "",
        ])

        if execution["status"] == "partial":
            lines.extend([
                "**Cobertura parcial: no interpretar como normalidad global.**",
                "",
            ])

        if execution["coverage"]:
            lines.extend([
                "| Regla | Estado | Muestras | Excluidas | Evidencias |",
                "|---|---|---:|---:|---:|",
            ])
            for coverage in execution["coverage"]:
                cells = [
                    coverage.get("rule_id", "No informado"),
                    coverage.get("status", "No informado"),
                    coverage.get("samples", "No informado"),
                    coverage.get("excluded_samples", "No informado"),
                    coverage.get("evidence_count", "No informado"),
                ]
                lines.append(
                    "| " + " | ".join(_text(cell) for cell in cells) + " |"
                )
        else:
            lines.append("No se registró detalle de cobertura.")

        lines.append("")

    lines.extend([
        "## Limitaciones generales",
        "",
        "- La selección no demuestra cobertura completa de la empresa.",
        "- La ausencia de hallazgos seleccionados no equivale a normalidad.",
        "- Las interpretaciones y sus hipótesis se conservan como tales.",
        "- La coincidencia temporal no demuestra causalidad ni continuidad.",
        "- Cada ejecución conserva su propio corte de recepción de datos.",
        "",
        "## Trazabilidad",
        "",
        f"Generador: {_text(GENERATOR_VERSION)}.",
        "",
        f"Hallazgos incluidos: {_ids([item['id'] for item in findings])}.",
        "",
        (
            "Correlaciones incluidas: "
            f"{_ids([item['id'] for item in correlations])}."
        ),
        "",
    ])

    return "\n".join(lines)