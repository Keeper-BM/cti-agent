from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.tables import AuditEvent

CSV = Path("frontend/public/examples/inventory.sample.csv").read_text(encoding="utf-8")


def asset(client, headers, name="csv-lab"):
    return client.post(
        "/api/v1/assets", headers=headers, json={"asset_name": name, "exposure_source": "test"}
    ).json()


def test_asset_edit_validation_and_audit_preserve_history(client, headers, engine):
    created = asset(client, headers)
    target = f"/api/v1/assets/{created['id']}"
    updated = client.patch(
        target,
        headers=headers,
        json={
            "asset_name": "renamed",
            "expected_release": "24.04",
            "host": "127.0.0.1",
            "criticality": "HIGH",
        },
    )
    assert updated.status_code == 200 and updated.json()["asset_name"] == "renamed"
    for body in [
        {},
        {"asset_name": None},
        {"is_active": None},
        {"host": "example.com;whoami"},
        {"exposure": "INVALID"},
    ]:
        assert client.patch(target, headers=headers, json=body).status_code == 422
    duplicate = asset(client, headers, "duplicate")
    assert (
        client.patch(target, headers=headers, json={"asset_name": "duplicate"}).status_code == 409
    )
    with Session(engine) as db:
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.asset_id == created["id"])
                .order_by(AuditEvent.created_at)
            )
        )
        assert [e.action for e in events] == ["asset.created", "asset.updated"]
        assert events[-1].details["before"]["asset_name"] == "csv-lab"
    assert (
        client.get(f"/api/v1/assets/{duplicate['id']}", headers=headers).json()["asset_name"]
        == "duplicate"
    )


def test_csv_and_json_share_validated_unverified_inventory(client, headers):
    a = asset(client, headers)
    path = f"/api/v1/assets/{a['id']}/inventories"
    result = client.post(path + "/csv", headers=headers, json={"csv_text": CSV})
    assert result.status_code == 201, result.text
    saved = result.json()
    assert saved["collection_method"] == "CSV" and saved["is_synthetic"]
    assert saved["packages"][0]["origin_status"] == "USER_DECLARED"
    assert not saved["coverage"]["package_list_complete"]
    assert client.get(path, headers=headers).json()["total"] == 1
    assert client.get(path + "/" + saved["inventory_id"], headers=headers).json() == saved
    client.patch(f"/api/v1/assets/{a['id']}", headers=headers, json={"is_active": False})
    assert client.post(path + "/csv", headers=headers, json={"csv_text": CSV}).status_code == 409


def test_csv_rejects_duplicates_mixed_metadata_unknown_columns_and_injection(client, headers):
    a = asset(client, headers)
    path = f"/api/v1/assets/{a['id']}/inventories/csv"
    head, row = CSV.strip().splitlines()
    inputs = [
        CSV + "\n" + row,
        CSV.replace("binary_name", "origin_status"),
        CSV.replace("apache2-bin", "=COMMAND()"),
        CSV.replace("true", "yes"),
        head
        + "\n"
        + row
        + "\n"
        + row.replace("24.04", "22.04").replace("apache2-bin", "apache2-utils"),
        head + "," + head + "\n" + row + "," + row,
        head + "\n",
        CSV.replace("+09:00", ""),
    ]
    for content in inputs:
        result = client.post(path, headers=headers, json={"csv_text": content})
        assert result.status_code == 422, result.text
    assert client.post(path, json={"csv_text": CSV}).status_code == 401
    assert client.get(path.removesuffix("/csv"), headers=headers).json()["total"] == 0
