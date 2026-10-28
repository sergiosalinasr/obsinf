import argparse
import asyncio
import json
import sys
from collections import defaultdict

from sqlalchemy import select

from app.agents.weblogic_agent import (
    analyze_resource,
    load_agent_configuration,
)
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.analysis import AnalysisExecution, Evidence
from app.models.source import Source
from app.models.technology import Technology
from app.services.findings import save_finding
from app.services.event_context import load_event_context


def load_evidence(
    company_id: int,
    execution_id: int,
    source_id: int,
) -> tuple[list[dict], str]:
    """Lee evidencias de una ejecución y fuente de la misma empresa."""
    with SessionLocal() as db:
        execution = db.scalar(
            select(AnalysisExecution).where(
                AnalysisExecution.company_id == company_id,
                AnalysisExecution.id == execution_id,
            )
        )

        if execution is None:
            raise ValueError("Ejecución no encontrada en la empresa")

        if execution.status not in ("completed", "partial"):
            raise ValueError(
                f"La ejecución no está disponible: {execution.status}"
            )

        source = db.scalar(
            select(Source)
            .join(Technology, Source.technology_id == Technology.id)
            .where(
                Source.company_id == company_id,
                Source.id == source_id,
                Technology.code == "weblogic",
            )
        )

        if source is None:
            raise ValueError(
                "Fuente WebLogic no encontrada en la empresa"
            )

        rows = list(
            db.scalars(
                select(Evidence)
                .where(
                    Evidence.company_id == company_id,
                    Evidence.execution_id == execution_id,
                    Evidence.source_id == source_id,
                )
                .order_by(
                    Evidence.resource_key,
                    Evidence.start_at,
                    Evidence.id,
                )
            ).all()
        )

        # Solo enviamos al modelo los datos necesarios para interpretar.
        data = [
            {
                "id": item.id,
                "resource_key": item.resource_key,
                "evidence_type": item.evidence_type,
                "metric_name": item.metric_name,
                "unit": item.unit,
                "comparison": item.comparison,
                "threshold_value": item.threshold_value,
                "min_observed": item.min_observed,
                "max_observed": item.max_observed,
                "start_at": item.start_at.isoformat(),
                "end_at": item.end_at.isoformat(),
                "duration_seconds": item.duration_seconds,
                "sample_count": item.sample_count,
            }
            for item in rows
        ]

        return data, execution.status


async def run(
    company_id: int,
    execution_id: int,
    source_id: int,
    *,
    persist: bool = False,
    event_margin_seconds: int = 120,
    event_limit: int = 100,
) -> int:
    """Interpreta evidencias y, opcionalmente, guarda los hallazgos."""
    evidence, execution_status = load_evidence(
        company_id, execution_id, source_id
    )

    print(f"Estado del análisis: {execution_status}")
    print(f"Evidencias WebLogic: {len(evidence)}")
    print(f"Modo: {'PERSISTENCIA' if persist else 'PRUEBA'}")

    if execution_status == "partial":
        print(
            "Cobertura parcial: revisa el detalle del análisis "
            "antes de interpretar los resultados."
        )

    if not evidence:
        print("No hay evidencias; no se invocará al modelo.")
        return 0

    configuration = load_agent_configuration()

    grouped = defaultdict(list)

    for item in evidence:
        grouped[item["resource_key"]].append(item)

    for resource_key in sorted(grouped):
        print(
            f"\nAnalizando recurso: {resource_key}",
            flush=True,
        )

        # Se cierra la sesión antes de invocar al modelo. El servicio de
        # persistencia volverá a verificar la selección contra PostgreSQL.
        with SessionLocal() as db:
            event_context = load_event_context(
                db,
                company_id=company_id, execution_id=execution_id,
                source_id=source_id, resource_key=resource_key,
                evidence_ids=[item["id"] for item in grouped[resource_key]],
                margin_seconds=event_margin_seconds, event_limit=event_limit,
            )
        print(f"Eventos de contexto: {len(event_context.events)}")
        if event_context.has_more_events:
            print("Contexto limitado: hay eventos adicionales no enviados al agente.")
        if any(event.message_truncated for event in event_context.events):
            print("Contexto limitado: uno o más mensajes fueron recortados.")

        # La llamada al modelo ocurre sin mantener abierta una sesión de BD.
        proposal = await analyze_resource(
            resource_key,
            grouped[resource_key],
            configuration,
            event_context=event_context,
        )

        print(json.dumps(
            proposal.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ))

        if persist:
            # El servicio vuelve a verificar las evidencias en PostgreSQL.
            with SessionLocal() as db:
                finding = save_finding(
                    db,
                    company_id=company_id,
                    execution_id=execution_id,
                    source_id=source_id,
                    proposal=proposal,
                    agent_name=configuration.agent_name,
                    model_name=configuration.model_name,
                    instruction=configuration.instruction,
                    event_context=event_context,
                )
                print(f"Hallazgo guardado con ID: {finding.id}")

    if not persist:
        print("\nModo de prueba: los hallazgos no se guardaron.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interpretar evidencias WebLogic con ADK y OpenAI"
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--execution-id", type=int, required=True)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Guardar los hallazgos validados en PostgreSQL",
    )
    parser.add_argument(
        "--event-margin-seconds", type=int, default=120,
        help="Margen antes y después de cada evidencia (0 a 3600 segundos)",
    )
    parser.add_argument(
        "--event-limit", type=int, default=100,
        help="Máximo de eventos por recurso enviados al agente (1 a 100)",
    )
    args = parser.parse_args()

    if min(args.company_id, args.execution_id, args.source_id) <= 0:
        parser.error("Los identificadores deben ser positivos")

    if not 0 <= args.event_margin_seconds <= 3600:
        parser.error("El margen de eventos debe estar entre 0 y 3600")
    if not 1 <= args.event_limit <= 100:
        parser.error("El límite de eventos debe estar entre 1 y 100")

    settings = get_settings()

    if settings.env != "local" or not settings.local_dev_mode:
        parser.error("Esta ejecución requiere modo local habilitado")

    try:
        return asyncio.run(
            run(
                args.company_id,
                args.execution_id,
                args.source_id,
                persist=args.persist,
                event_margin_seconds=args.event_margin_seconds,
                event_limit=args.event_limit,
            )
        )

    except Exception as exc:
        print(
            f"No fue posible completar la interpretación: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
