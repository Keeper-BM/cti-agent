"""Server-created evidence for one bounded Apache HTTP/2 observation."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

HTTP2_CONDITION = "apache-http2-cve-2024-27316/1.0"
OBSERVER_VERSION = "apache-runtime/1.0"


class ApacheHTTP2Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observer_version: Literal["apache-runtime/1.0"]
    observed_at: AwareDatetime
    main_pid: int = Field(ge=1)
    process_start_ticks: int = Field(ge=1)
    boot_id: UUID
    service_active: Literal[True]
    module_loaded: Literal[True]
    listener_owned: Literal[True]
    process_unchanged: Literal[True]
    endpoint: Literal["http://127.0.0.1:80/"]
    http_version: Literal["2"]
    http_status: Literal[200]
    executable_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    module_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ApacheHTTP2Evidence(ApacheHTTP2Observation):
    verification_id: UUID
    package_version: str
    source_version: str
