"""Strict CSV input translated into the same untrusted inventory input as JSON."""

import csv
import io
from uuid import UUID

from pydantic import ValidationError

from backend.api.schemas.inventories import InventoryImport
from backend.collectors.json_import import import_inventory
from backend.core.errors import AppError
from backend.models.enums import CollectionMethod

METADATA = {
    "os_release",
    "os_architecture",
    "collected_at",
    "package_list_complete",
    "is_synthetic",
}
PACKAGE = {
    "binary_name",
    "binary_version",
    "source_name",
    "source_version",
    "architecture",
    "origin",
}
REQUIRED = {"os_release", "collected_at", "binary_name"}


def invalid(message="CSV 열·행·값을 확인하세요. 입력 예제를 참고하세요."):
    return AppError("INVALID_INVENTORY_CSV", message, 422)


def boolean(value, default):
    if value in {None, ""}:
        return default
    if value not in {"true", "false"}:
        raise invalid("CSV의 참/거짓 값은 true 또는 false여야 합니다.")
    return value == "true"


def parse_csv(asset_id: UUID, text: str):
    if len(text.encode("utf-8")) > 2 * 1024 * 1024 or "\x00" in text:
        raise invalid()
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline=""), strict=True)
    try:
        fields = reader.fieldnames
        if (
            not fields
            or len(set(fields)) != len(fields)
            or not REQUIRED <= set(fields)
            or set(fields) - METADATA - PACKAGE
        ):
            raise invalid(
                "CSV 필수 열: os_release, collected_at, binary_name. 알 수 없는 열은 거부합니다."
            )
        packages = []
        metadata = None
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise invalid()
            if len(packages) >= 5000:
                raise invalid("CSV 패키지는 최대 5,000개입니다.")
            current = {name: (row.get(name) or "").strip() for name in METADATA}
            if metadata is not None and current != metadata:
                raise invalid(
                    "같은 CSV의 OS·확인 시각·목록 범위·가상 여부는 모든 행에서 같아야 합니다."
                )
            metadata = current
            packages.append({name: (row.get(name) or "").strip() or None for name in PACKAGE})
        if not packages:
            raise invalid("CSV에 패키지 행이 없습니다.")
        payload = InventoryImport.model_validate(
            {
                "collected_at": metadata["collected_at"],
                "os": {
                    "id": "ubuntu",
                    "version_id": metadata["os_release"],
                    "architecture": metadata["os_architecture"] or None,
                },
                "packages": packages,
                "package_list_complete": boolean(metadata["package_list_complete"], False),
                "is_synthetic": boolean(metadata["is_synthetic"], False),
            }
        )
    except (csv.Error, ValidationError, UnicodeError):
        raise invalid() from None
    inventory = import_inventory(asset_id, payload)
    inventory.collection_method = CollectionMethod.CSV
    inventory.collector_version = "csv-import/1.0"
    return inventory
