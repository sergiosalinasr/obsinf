"""Interpretación conjunta con persistencia opcional."""

import argparse
import asyncio
import json
import sys

from app.agents.dependency_coordinator import (
    analyze_dependency,
    load_agent_configuration,
)
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.correlations import (
    ensure_correlation_not_saved,
    save_correlation,
)
from app.services.dependency_context import build_dependency_context


def load_context(
    company_id: int,
    dependency_id: int,
    consumer_finding_id: int,
    provider_finding_id: int,
) -> dict:
    """Cierra la sesión antes de invocar al modelo."""
    with SessionLocal() as db:
        return build_dependency_context(
            db,
            company_id=company_id,
            dependency_id=dependency_id,
            consumer_finding_id=consumer_finding_id,
            provider_finding_id=provider_finding_id,
        )


async def run(
    company_id: int,
    dependency_id: int,
    consumer_finding_id: int,
    provider_finding_id: int,
    *,
    persist: bool = False,
) -> int:
    context = load_context(
        company_id,
        dependency_id,
        consumer_finding_id,
        provider_finding_id,
    )

    print(f"Modo: {'PERSISTENCIA' if persist else 'PRUEBA — sin persistencia'}")
    print(f"Dependencia: {context['dependency']['id']}")
    print(
        "Hallazgos: "
        f"{context['consumer']['finding']['id']} / "
        f"{context['provider']['finding']['id']}"
    )

    if not context["comparison"]["same_data_cutoff"]:
        print("Los análisis tienen distintos cortes de recepción de datos.")

    configuration = load_agent_configuration()

    if persist:
        with SessionLocal() as db:
            ensure_correlation_not_saved(
                db,
                company_id=company_id,
                context=context,
                configuration=configuration,
            )

    print("Interpretando contexto conjunto...", flush=True)
    proposal = await analyze_dependency(context, configuration)

    print(json.dumps(
        proposal.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    ))

    if persist:
        with SessionLocal() as db:
            correlation = save_correlation(
                db,
                company_id=company_id,
                context=context,
                proposal=proposal,
                configuration=configuration,
            )
            print(f"\nCorrelación guardada con ID: {correlation.id}")
    else:
        print("\nLa correlación no se guardó.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interpretar una dependencia WebLogic–Oracle"
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--dependency-id", type=int, required=True)
    parser.add_argument("--consumer-finding-id", type=int, required=True)
    parser.add_argument("--provider-finding-id", type=int, required=True)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Guardar la correlación validada y su contexto",
    )
    args = parser.parse_args()

    identifiers = (
        args.company_id,
        args.dependency_id,
        args.consumer_finding_id,
        args.provider_finding_id,
    )
    if min(identifiers) <= 0:
        parser.error("Los identificadores deben ser positivos")

    settings = get_settings()
    if settings.env != "local" or not settings.local_dev_mode:
        parser.error("Esta ejecución requiere modo local habilitado")

    try:
        return asyncio.run(run(*identifiers, persist=args.persist))
    except Exception as exc:
        print(
            f"No fue posible completar la interpretación: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())