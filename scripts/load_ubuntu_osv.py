"""Load a reproducible sample of Ubuntu OSV CVE records."""

import json
import random
import tarfile
from pathlib import Path

ARCHIVE = Path.home() / "Desktop/cti-agent-main/data/raw/ubuntu/official_osv/osv-all.tar.xz"

YEARS = {2023, 2024, 2025, 2026}
SAMPLE_SIZE = 300
SEED = 42


def load_records():
    records = []

    with tarfile.open(ARCHIVE, "r:xz") as archive:
        rng = random.Random(SEED)
        seen = 0

        for member in archive:
            if not (
                member.isfile()
                and member.name.endswith(".json")
                and any(f"/cve/{year}/" in member.name for year in YEARS)
            ):
                continue

            source = archive.extractfile(member)
            if source is None:
                continue

            data = json.load(source)
            cve_id = data["id"].removeprefix("UBUNTU-")
            description = data.get("details") or data.get("summary") or ""

            affected = []
            for item in data.get("affected", []):
                package = item.get("package", {})
                fixed_versions = [
                    event["fixed"]
                    for range_item in item.get("ranges", [])
                    for event in range_item.get("events", [])
                    if "fixed" in event
                ]

                affected.append(
                    {
                        "package": package.get("name"),
                        "ecosystem": package.get("ecosystem"),
                        "fixed_versions": fixed_versions,
                    }
                )

            text = "\n".join(
                [
                    f"CVE: {cve_id}",
                    f"Description: {description}",
                    *[
                        f"Package: {a['package']}; "
                        f"Ubuntu: {a['ecosystem']}; "
                        f"Fixed: {', '.join(a['fixed_versions']) or 'unknown'}"
                        for a in affected
                    ],
                ]
            )

            record = {
                "id": cve_id,
                "text": text,
                "affected": affected,
                "source": member.name,
            }

            seen += 1
            if len(records) < SAMPLE_SIZE:
                records.append(record)
            else:
                index = rng.randrange(seen)
                if index < SAMPLE_SIZE:
                    records[index] = record

    return records


if __name__ == "__main__":
    records = load_records()

    print("로드한 CVE 수:", len(records))
    print("첫 번째 CVE:", records[0]["id"] if records else "없음")
    print("첫 번째 문서:")
    print(records[0]["text"][:1200] if records else "없음")
