"""Registro de modelos SQLAlchemy para la aplicación y Alembic."""

from app.models.analysis import (
    AnalysisExecution,
    Evidence,
    EvidenceMetric,
)
from app.models.company import Company
from app.models.finding import Finding, FindingEvidence, FindingEvent
from app.models.ingestion import (
    IngestionBatch,
    IngestionError,
    IngestionFile,
)
from app.models.normality import NormalityProfile, NormalityRule
from app.models.observations import EventNormalized, MetricNormalized
from app.models.resource_dependency import ResourceDependency
from app.models.source import Source
from app.models.technology import Technology

__all__ = [
    "Company",
    "Technology",
    "Source",
    "ResourceDependency",
    "IngestionBatch",
    "IngestionFile",
    "IngestionError",
    "MetricNormalized",
    "EventNormalized",
    "NormalityProfile",
    "NormalityRule",
    "AnalysisExecution",
    "Evidence",
    "EvidenceMetric",
    "Finding",
    "FindingEvidence",
    "FindingEvent",
]