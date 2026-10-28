import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator


PARSER_VERSION = "weblogic_log_v1:1.0.0"

# Once campos de encabezado, seguidos del mensaje.
# El mensaje puede contener saltos de línea y símbolos < o >.
RECORD_PATTERN = re.compile(
    r"^####"
    r"(?P<header>(?:<[^>]*>\s*){11})"
    r"<(?P<message>.*)>\s*$",
    re.DOTALL,
)

SEVERITY_MAP = {
    "trace": "debug",
    "debug": "debug",
    "info": "info",
    "notice": "info",
    "warning": "warning",
    "error": "error",
    "critical": "critical",
    "alert": "critical",
    "emergency": "critical",
}


@dataclass(frozen=True)
class ParsedEvent:
    """Evento normalizado, todavía sin empresa, fuente ni lote."""

    record_locator: str
    resource_key: str
    record_type: str
    severity: str
    original_severity: str
    event_code: str
    message: str
    occurred_at: datetime
    attributes: dict[str, Any]
    dedup_key: str


@dataclass(frozen=True)
class LogParseError:
    """Error localizable sin copiar el registro original completo."""

    record_locator: str
    code: str
    message: str


def locator(start: int, end: int) -> str:
    """Identifica una línea o un rango de líneas físicas."""
    return f"line:{start}" if start == end else f"lines:{start}-{end}"


def parse_record(
    text: str,
    start: int,
    end: int,
    file_sha256: str,
) -> ParsedEvent | LogParseError:
    """Interpreta un registro completo, incluidas sus continuaciones."""
    position = locator(start, end)
    match = RECORD_PATTERN.fullmatch(text.rstrip("\r\n"))

    if match is None:
        return LogParseError(
            position,
            "INVALID_LOG_RECORD",
            "El registro no cumple el perfil WebLogic admitido",
        )

    fields = re.findall(r"<([^>]*)>", match.group("header"))

    (
        timestamp,
        severity,
        subsystem,
        host,
        server,
        thread,
        user,
        transaction,
        context,
        raw_time,
        event_code,
    ) = fields

    try:
        # Este perfil exige fecha ISO 8601 con zona explícita.
        instant = datetime.fromisoformat(
            timestamp.strip().replace("Z", "+00:00")
        )

        if instant.tzinfo is None:
            raise ValueError("Falta zona horaria")

        instant = instant.astimezone(timezone.utc)

    except (ValueError, OverflowError):
        return LogParseError(
            position,
            "INVALID_TIMESTAMP",
            "Se requiere una fecha ISO 8601 con zona horaria",
        )

    if not server.strip():
        return LogParseError(
            position,
            "MISSING_RESOURCE",
            "El registro no identifica el servidor",
        )

    # La posición permite conservar entradas idénticas legítimas
    # dentro del mismo archivo, sin duplicarlas al recibirlo de nuevo.
    dedup_key = hashlib.sha256(
        f"{file_sha256}:{start}:{end}".encode("utf-8")
    ).hexdigest()

    return ParsedEvent(
        record_locator=position,
        resource_key=server.strip(),
        record_type="log",
        severity=SEVERITY_MAP.get(severity.strip().lower(), "unknown"),
        original_severity=severity,
        event_code=event_code.strip(),
        message=match.group("message").strip(),
        occurred_at=instant,
        attributes={
            "original_timestamp": timestamp,
            "subsystem": subsystem,
            "host": host,
            "thread": thread,
            "user": user,
            "transaction": transaction,
            "context": context,
            "raw_time": raw_time,
        },
        dedup_key=dedup_key,
    )


def parse_weblogic_log(
    lines: Iterable[str],
    file_sha256: str,
) -> Iterator[ParsedEvent | LogParseError]:
    """Agrupa registros y conserva las líneas de continuación.

    Un encabezado que comienza con ####< inicia otro registro.
    La memoria utilizada depende del tamaño de un registro,
    no del archivo completo.
    """
    buffer: list[str] = []
    start = 0
    last_line = 0

    for line_number, line in enumerate(lines, start=1):
        last_line = line_number

        if line_number == 1:
            line = line.removeprefix("\ufeff")

        if line.startswith("####<"):
            if buffer:
                yield parse_record(
                    "".join(buffer),
                    start,
                    line_number - 1,
                    file_sha256,
                )

            buffer = [line]
            start = line_number

        elif buffer:
            buffer.append(line)

        else:
            # No descartamos contenido anterior al primer encabezado.
            yield LogParseError(
                locator(line_number, line_number),
                "ORPHAN_LINE",
                "Línea sin encabezado WebLogic",
            )

    if buffer:
        yield parse_record(
            "".join(buffer),
            start,
            last_line,
            file_sha256,
        )
    elif last_line == 0:
        yield LogParseError(
            "line:0",
            "EMPTY_FILE",
            "El archivo está vacío",
        )