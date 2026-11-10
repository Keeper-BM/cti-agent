"""Convert validated file input into an immutable inventory snapshot."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.api.schemas.inventories import InventoryImport
from backend.models.contracts import Coverage, InstalledPackage, InventorySnapshot, OperatingSystem
from backend.models.enums import CollectionMethod, CollectionStatus, OriginStatus


def import_inventory(asset_id: UUID, payload: InventoryImport) -> InventorySnapshot:
    now = datetime.now(UTC)
    missing = []
    for field in ("architecture", "codename"):
        if getattr(payload.os, field) is None:
            missing.append(f"os.{field}")
    packages = []
    for index, item in enumerate(payload.packages):
        for field in ("binary_version", "source_name", "source_version", "architecture", "origin"):
            if getattr(item, field) is None:
                missing.append(f"packages[{index}].{field}")
        packages.append(
            InstalledPackage(
                package_id=uuid4(),
                binary_name=item.binary_name,
                binary_version=item.binary_version,
                source_name=item.source_name,
                source_version=item.source_version,
                architecture=item.architecture,
                install_status="installed",
                origin_status=OriginStatus.USER_DECLARED if item.origin else OriginStatus.UNKNOWN,
                origin_description=item.origin,
            )
        )
    return InventorySnapshot(
        inventory_id=uuid4(),
        asset_id=asset_id,
        collected_at=payload.collected_at.astimezone(UTC),
        ingested_at=now,
        collection_method=CollectionMethod.JSON,
        collection_status=(
            CollectionStatus.COMPLETE if payload.package_list_complete else CollectionStatus.PARTIAL
        ),
        os=OperatingSystem(**payload.os.model_dump()),
        packages=packages,
        coverage=Coverage(
            package_list_complete=payload.package_list_complete, missing_fields=missing
        ),
        collector_version="json-import/1.0",
        is_synthetic=payload.is_synthetic,
    )
