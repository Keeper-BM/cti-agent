"""Build a balanced Ubuntu OSV retrieval evaluation sample."""

import json
import random
import tarfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = (
    Path.home()
    / "Desktop/cti-agent-main/data/raw/ubuntu/official_osv/osv-all.tar.xz"
)
OUTPUT = ROOT / "data/evaluation/ubuntu_osv_balanced_300.json"

YEARS = (2023, 2024, 2025, 2026)
PER_YEAR = 75
SEED = 42


def main():
    samples = {year: [] for year in YEARS}
    counts = Counter()
    rng = {year: random.Random(SEED + year) for year in YEARS}

    with tarfile.open(ARCHIVE, "r|xz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".json"):
                continue

            parts = member.name.split("/")
            if len(parts) < 4 or parts[-3] != "cve":
                continue

            try:
                year = int(parts[-2])
            except ValueError:
                continue

            if year not in samples:
                continue

            source = archive.extractfile(member)
            if source is None:
                continue

            data = json.load(source)
            description = data.get("details") or data.get("summary") or ""

            if not description.strip():
                continue

            if "rejected or withdrawn" in description.lower():
                continue

            cve_id = data["id"].removeprefix("UBUNTU-")

            affected = []
            for item in data.get("affected", []):
                package = item.get("package", {})
                fixed_versions = [
                    event["fixed"]
                    for range_item in item.get("ranges", [])
                    for event in range_item.get("events", [])
                    if "fixed" in event
                ]
                affected.append({
                    "package": package.get("name"),
                    "ecosystem": package.get("ecosystem"),
                    "fixed_versions": fixed_versions,
                })

            text = "\n".join([
                f"CVE: {cve_id}",
                f"Description: {description}",
                *[
                    f"Package: {a['package']}; "
                    f"Ubuntu: {a['ecosystem']}; "
                    f"Fixed: {', '.join(a['fixed_versions']) or 'unknown'}"
                    for a in affected
                ],
            ])

            record = {
                "id": cve_id,
                "text": text,
                "affected": affected,
                "source": member.name,
            }

            counts[year] += 1
            bucket = samples[year]

            if len(bucket) < PER_YEAR:
                bucket.append(record)
            else:
                index = rng[year].randrange(counts[year])
                if index < PER_YEAR:
                    bucket[index] = record

    for year in YEARS:
        if len(samples[year]) < PER_YEAR:
            raise RuntimeError(f"{year}년 데이터 부족: {len(samples[year])}건")

    records = [
        record
        for year in YEARS
        for record in samples[year]
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("평가 데이터셋 저장 완료:", OUTPUT)
    print("총 CVE:", len(records))
    print("연도별 분포:", dict(Counter(
        record["id"].split("-")[1] for record in records
    )))
    print("파일 크기:", round(OUTPUT.stat().st_size / 1024 / 1024, 2), "MB")


if __name__ == "__main__":
    main()
