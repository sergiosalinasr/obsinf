import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.normality import NormalityProfile, NormalityRule
from app.models.source import Source
from app.schemas.normality import ProfileCreate, RuleCreate


class NormalityError(Exception):
    """Error de negocio que podrá traducirse a una respuesta HTTP."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_dimensions(dimensions: dict) -> str:
    """Genera la identidad estable de las dimensiones de una serie."""
    try:
        return json.dumps(
            dimensions,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise NormalityError(
            "INVALID_DIMENSIONS",
            "Las dimensiones deben ser un objeto JSON válido y finito",
        ) from exc


def lock_company(db: Session, company_id: int) -> Company:
    """Serializa los cambios de normalidad de una empresa."""
    company = db.scalar(
        select(Company)
        .where(Company.id == company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    if company is None:
        raise NormalityError(
            "COMPANY_NOT_FOUND", "Empresa no encontrada"
        )

    if not company.is_active:
        raise NormalityError(
            "COMPANY_INACTIVE", "La empresa está inactiva"
        )

    return company


def lock_profile(
    db: Session,
    company_id: int,
    profile_id: int,
) -> NormalityProfile:
    """Obtiene y bloquea un perfil de la empresa indicada."""
    profile = db.scalar(
        select(NormalityProfile)
        .where(
            NormalityProfile.id == profile_id,
            NormalityProfile.company_id == company_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    if profile is None:
        raise NormalityError(
            "PROFILE_NOT_FOUND", "Perfil no encontrado"
        )

    return profile


def create_profile(
    db: Session,
    company_id: int,
    payload: ProfileCreate,
) -> NormalityProfile:
    """Crea una versión de perfil en estado draft."""
    try:
        lock_company(db, company_id)

        profile = NormalityProfile(
            company_id=company_id,
            code=payload.code,
            version=payload.version,
            name=payload.name,
            description=payload.description,
            profile_type="CONFIGURED",
            status="draft",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile

    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(
            getattr(exc.orig, "diag", None), "constraint_name", None
        )

        if (
            getattr(exc.orig, "sqlstate", None) == "23505"
            and constraint
            == "uq_normality_profiles_company_id_code_version"
        ):
            raise NormalityError(
                "PROFILE_VERSION_EXISTS",
                "Ya existe esa versión del perfil",
            ) from None

        raise

    except Exception:
        db.rollback()
        raise


def create_rule(
    db: Session,
    company_id: int,
    profile_id: int,
    payload: RuleCreate,
) -> NormalityRule:
    """Agrega una regla a un perfil en borrador de la empresa."""
    try:
        lock_company(db, company_id)
        profile = lock_profile(db, company_id, profile_id)

        if profile.status != "draft":
            raise NormalityError(
                "PROFILE_NOT_DRAFT",
                "Solo se pueden agregar reglas a un perfil en borrador",
            )

        source = db.scalar(
            select(Source)
            .where(
                Source.id == payload.source_id,
                Source.company_id == company_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        if source is None:
            raise NormalityError(
                "SOURCE_NOT_FOUND", "Fuente no encontrada"
            )

        if not source.is_active:
            raise NormalityError(
                "SOURCE_INACTIVE", "La fuente está inactiva"
            )

        # Los adaptadores actuales todavía no definen dimensiones.
        # Evitamos crear reglas que el análisis aún no podría aplicar.
        if payload.dimensions:
            raise NormalityError(
                "DIMENSIONS_NOT_SUPPORTED",
                "Por ahora solo se admiten dimensiones vacías",
            )

        series_key = canonical_dimensions(payload.dimensions)

        rule = NormalityRule(
            company_id=company_id,
            profile_id=profile.id,
            series_key=series_key,
            **payload.model_dump(),
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(
            getattr(exc.orig, "diag", None), "constraint_name", None
        )

        if (
            getattr(exc.orig, "sqlstate", None) == "23505"
            and constraint == "uq_normality_rules_series"
        ):
            raise NormalityError(
                "RULE_ALREADY_EXISTS",
                "Ya existe una regla para esa serie en el perfil",
            ) from None

        raise

    except Exception:
        db.rollback()
        raise


def activate_profile(
    db: Session,
    company_id: int,
    profile_id: int,
) -> NormalityProfile:
    """Publica un borrador y retira la versión activa anterior.

    Ambas modificaciones se confirman o revierten juntas.
    """
    try:
        lock_company(db, company_id)
        profile = lock_profile(db, company_id, profile_id)

        if profile.status != "draft":
            raise NormalityError(
                "PROFILE_NOT_DRAFT",
                "Solo se puede activar un perfil en borrador",
            )

        has_rule = db.scalar(
            select(NormalityRule.id)
            .where(
                NormalityRule.company_id == company_id,
                NormalityRule.profile_id == profile_id,
            )
            .limit(1)
        )

        if has_rule is None:
            raise NormalityError(
                "PROFILE_HAS_NO_RULES",
                "El perfil necesita al menos una regla",
            )

        previous = db.scalar(
            select(NormalityProfile)
            .where(
                NormalityProfile.company_id == company_id,
                NormalityProfile.code == profile.code,
                NormalityProfile.status == "active",
            )
            .with_for_update()
        )

        if previous is not None:
            previous.status = "retired"

            # Aplicamos primero el retiro para respetar el índice parcial.
            db.flush()

        profile.status = "active"
        db.commit()
        db.refresh(profile)
        return profile

    except Exception:
        db.rollback()
        raise

def list_profiles(
    db: Session,
    company_id: int,
    after_id: int = 0,
    limit: int = 100,
) -> list[NormalityProfile]:
    """Lista versiones de perfiles, incluidas las históricas."""
    if db.get(Company, company_id) is None:
        raise NormalityError(
            "COMPANY_NOT_FOUND", "Empresa no encontrada"
        )

    return list(
        db.scalars(
            select(NormalityProfile)
            .where(
                NormalityProfile.company_id == company_id,
                NormalityProfile.id > after_id,
            )
            .order_by(NormalityProfile.id)
            .limit(limit)
        ).all()
    )


def get_profile(
    db: Session,
    company_id: int,
    profile_id: int,
) -> tuple[NormalityProfile, list[NormalityRule]]:
    """Consulta un perfil y sus reglas dentro de una empresa."""
    profile = db.scalar(
        select(NormalityProfile).where(
            NormalityProfile.company_id == company_id,
            NormalityProfile.id == profile_id,
        )
    )

    if profile is None:
        # Un perfil ajeno recibe la misma respuesta que uno inexistente.
        raise NormalityError(
            "PROFILE_NOT_FOUND", "Perfil no encontrado"
        )

    rules = list(
        db.scalars(
            select(NormalityRule)
            .where(
                NormalityRule.company_id == company_id,
                NormalityRule.profile_id == profile_id,
            )
            .order_by(NormalityRule.id)
        ).all()
    )

    return profile, rules