"""Parse fixed systemd observations without inferring package presence or vulnerability."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

SERVICE_UNITS = {"service_apache2": "apache2.service", "service_mysql": "mysql.service"}
PROPERTIES = {"Id", "LoadState", "ActiveState", "SubState", "UnitFileState"}
STATE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


class ServiceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit: Literal["apache2.service", "mysql.service"]
    status: Literal["OBSERVED", "NOT_FOUND", "UNKNOWN"]
    load_state: str | None = None
    active_state: str | None = None
    sub_state: str | None = None
    unit_file_state: str | None = None
    error_code: Literal["COMMAND_FAILED", "OUTPUT_INVALID"] | None = None


def parse_service(unit: str, exit_code: int, stdout: str) -> ServiceObservation:
    if exit_code != 0:
        return ServiceObservation(unit=unit, status="UNKNOWN", error_code="COMMAND_FAILED")
    fields = {}
    for line in stdout.splitlines():
        if not line:
            continue
        name, separator, value = line.partition("=")
        if not separator or name not in PROPERTIES or name in fields:
            return ServiceObservation(unit=unit, status="UNKNOWN", error_code="OUTPUT_INVALID")
        fields[name] = value
    if (
        set(fields) != PROPERTIES
        or fields["Id"] != unit
        or any(
            not STATE.fullmatch(fields[name]) for name in ("LoadState", "ActiveState", "SubState")
        )
        or (fields["UnitFileState"] and not STATE.fullmatch(fields["UnitFileState"]))
        or (fields["LoadState"] == "not-found" and fields["ActiveState"] != "inactive")
    ):
        return ServiceObservation(unit=unit, status="UNKNOWN", error_code="OUTPUT_INVALID")
    return ServiceObservation(
        unit=unit,
        status="NOT_FOUND" if fields["LoadState"] == "not-found" else "OBSERVED",
        load_state=fields["LoadState"],
        active_state=fields["ActiveState"],
        sub_state=fields["SubState"],
        unit_file_state=fields["UnitFileState"] or None,
    )
