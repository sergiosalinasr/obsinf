import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


PARSER_VERSION = "obsinf_metrics_jsonl_v1:1.0.0"

# Catálogo de métricas admitidas por este contrato de intercambio.
METRIC_UNITS = {
    "cpu_usage_percent": "percent",
    "memory_usage_percent": "percent",
    "jdbc_active_connections": "count",
    "http_response_time_ms": "ms",
}


class MetricInput(BaseModel):
    """Valida y normaliza una línea de métricas.

    No contiene identificadores de empresa o fuente:
    esos datos proceden del lote autorizado, no del archivo.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: AwareDatetime
    resource_key: str = Field(min_length=1)
    metric_name: Literal[
        "cpu_usage_percent",
        "memory_usage_percent",
        "jdbc_active_connections",
        "http_response_time_ms",
    ]
    value: float
    unit: str
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def require_text_timestamp(cls, value):
        """Requiere una fecha textual; no admite épocas numéricas."""
        if not isinstance(value, str):
            raise ValueError("timestamp debe ser una fecha ISO 8601 textual")

        return value

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """AwareDatetime exige zona horaria; aquí convertimos a UTC."""
        return value.astimezone(timezone.utc)

    @field_validator("resource_key")
    @classmethod
    def normalize_resource(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("resource_key no puede estar vacío")

        return value

    @field_validator("value", mode="before")
    @classmethod
    def validate_numeric_value(cls, value):
        """No acepta booleanos ni números escritos como texto."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("value debe ser un número JSON")

        try:
            normalized = float(value)
        except (OverflowError, ValueError):
            raise ValueError("value está fuera del rango admitido") from None

        if not math.isfinite(normalized):
            raise ValueError("value debe ser finito")

        # Normalizamos -0.0 para obtener la misma huella que 0.0.
        return 0.0 if normalized == 0 else normalized

    @model_validator(mode="after")
    def validate_unit_and_range(self):
        """Comprueba las reglas específicas de cada métrica."""
        expected_unit = METRIC_UNITS[self.metric_name]

        if self.unit != expected_unit:
            raise ValueError(
                f"La unidad de {self.metric_name} debe ser {expected_unit}"
            )

        if self.metric_name in (
            "cpu_usage_percent",
            "memory_usage_percent",
        ):
            if not 0 <= self.value <= 100:
                raise ValueError("El porcentaje debe estar entre 0 y 100")

        elif self.metric_name == "jdbc_active_connections":
            if self.value < 0 or not self.value.is_integer():
                raise ValueError(
                    "Las conexiones deben ser un entero no negativo"
                )

        elif self.value < 0:
            raise ValueError("El tiempo de respuesta no puede ser negativo")

        return self


@dataclass(frozen=True)
class ParsedMetric:
    """Resultado válido, listo para vincularse con un lote y guardarse."""

    line_number: int
    metric: MetricInput
    dedup_key: str

    @property
    def record_locator(self) -> str:
        return f"line:{self.line_number}"


@dataclass(frozen=True)
class ParseError:
    """Error localizable sin exponer el contenido completo de la línea."""

    line_number: int
    code: str
    message: str

    @property
    def record_locator(self) -> str:
        return f"line:{self.line_number}"


def reject_nonstandard_number(value: str):
    """Rechaza NaN e Infinity, que no pertenecen al estándar JSON."""
    raise ValueError("Número no permitido en JSON")


def unique_object(pairs):
    """Rechaza claves repetidas, también dentro de attributes."""
    result = {}

    for key, value in pairs:
        if key in result:
            raise ValueError("El objeto JSON contiene claves repetidas")
        result[key] = value

    return result


def dedup_key_for(metric: MetricInput) -> str:
    """Calcula una huella estable de la observación normalizada.

    No incluye archivo, lote ni línea: la misma medición recibida
    nuevamente debe producir la misma clave dentro de una fuente.
    """
    canonical = json.dumps(
        metric.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_metrics_jsonl(
    lines: Iterable[str],
) -> Iterator[ParsedMetric | ParseError]:
    """Procesa texto UTF-8 ya decodificado, sin cargar todo en memoria.

    Cada línea física debe contener un objeto JSON.
    Los errores de registros no detienen las líneas siguientes.
    Los errores de lectura o codificación los gestionará el procesador
    del archivo, que deberá abrirlo con encoding='utf-8-sig'.
    """
    found_line = False

    for line_number, line in enumerate(lines, start=1):
        found_line = True

        # También admite un BOM cuando se prueba con texto en memoria.
        if line_number == 1:
            line = line.removeprefix("\ufeff")

        if not line.strip():
            yield ParseError(
                line_number, "EMPTY_LINE", "La línea está vacía"
            )
            continue

        try:
            payload = json.loads(
                line,
                parse_constant=reject_nonstandard_number,
                object_pairs_hook=unique_object,
            )
        except (ValueError, RecursionError):
            yield ParseError(
                line_number,
                "INVALID_JSON",
                "La línea no contiene JSON válido para este contrato",
            )
            continue

        if not isinstance(payload, dict):
            yield ParseError(
                line_number,
                "INVALID_RECORD",
                "Cada línea debe contener un objeto JSON",
            )
            continue

        try:
            metric = MetricInput.model_validate(payload)
            key = dedup_key_for(metric)
        except ValidationError as exc:
            # No incluimos input ni contexto para evitar copiar datos.
            messages = [
                f"{'.'.join(map(str, error['loc'])) or 'record'}: "
                f"{error['msg']}"
                for error in exc.errors(
                    include_input=False,
                    include_context=False,
                    include_url=False,
                )
            ]
            yield ParseError(
                line_number,
                "INVALID_METRIC",
                "; ".join(messages),
            )
            continue
        except (ValueError, OverflowError, RecursionError):
            # También comprueba que attributes sea JSON finito serializable.
            yield ParseError(
                line_number,
                "INVALID_METRIC",
                "El registro contiene valores no serializables o no finitos",
            )
            continue

        yield ParsedMetric(line_number, metric, key)

    if not found_line:
        yield ParseError(0, "EMPTY_FILE", "El archivo está vacío")