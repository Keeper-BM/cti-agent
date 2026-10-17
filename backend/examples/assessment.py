"""Validate and load a connected example without a database, collector, or model."""

import json
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from backend.models.contracts import Answer, Contract, FeedSnapshot, Finding, InventorySnapshot

DATA = Path(__file__).with_name("data")


class AssessmentExample(Contract):
    example_id: Literal["synthetic-package-assessment"] = "synthetic-package-assessment"
    is_synthetic: Literal[True] = True
    description: str
    inventory: InventorySnapshot
    feed: FeedSnapshot
    expected_findings: list[Finding]
    expected_answer: Answer

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        if not self.feed.is_synthetic:
            raise ValueError("The development example must use a synthetic feed")
        packages = {item.package_id: item for item in self.inventory.packages}
        rules = {
            rule.rule_id: (advisory, rule)
            for advisory in self.feed.advisories
            for rule in advisory.rules
        }
        for finding in self.expected_findings:
            if (
                finding.asset_id != self.inventory.asset_id
                or finding.inventory_id != self.inventory.inventory_id
                or finding.feed_snapshot_id != self.feed.feed_snapshot_id
            ):
                raise ValueError("Finding snapshot references do not match the example")
            if finding.package_ref not in packages or finding.matched_rule_id not in rules:
                raise ValueError("Finding package or rule reference does not exist")
            package = packages[finding.package_ref]
            advisory, rule = rules[finding.matched_rule_id]
            name, version = (
                (package.binary_name, package.binary_version)
                if finding.comparison_basis == "BINARY"
                else (package.source_name, package.source_version)
            )
            if (
                name != rule.package_name
                or version != finding.installed_version
                or finding.comparison_basis != rule.package_kind
                or finding.cve_id != advisory.cve_id
                or finding.fixed_version != rule.fixed_version
                or rule.os_id != self.inventory.os.id
                or rule.release != self.inventory.os.version_id
                or (rule.architecture and rule.architecture != package.architecture)
            ):
                raise ValueError("Finding package, version, or condition does not match its rule")
            if not finding.evidence_refs or any(
                item not in advisory.evidence_refs for item in finding.evidence_refs
            ):
                raise ValueError("Finding evidence must come from its normalized advisory")
        answer = self.expected_answer
        if set(answer.requested_asset_ids) != {self.inventory.asset_id} or set(
            answer.analysis_ids
        ) != {item.analysis_id for item in self.expected_findings}:
            raise ValueError("Answer scope does not match the example findings")
        evidence = [item for finding in self.expected_findings for item in finding.evidence_refs]
        if not answer.citations or any(item not in evidence for item in answer.citations):
            raise ValueError("Answer citations must refer to finding evidence")
        return self


def load_assessment_example() -> AssessmentExample:
    return AssessmentExample.model_validate(
        {
            "description": "가상 패키지·CVE·근거와 고정 결과입니다. 실제 분석 결과가 아닙니다.",
            "inventory": InventorySnapshot.model_validate_json(
                (DATA / "inventory.json").read_text(encoding="utf-8")
            ),
            "feed": FeedSnapshot.model_validate_json(
                (DATA / "feed.json").read_text(encoding="utf-8")
            ),
            **json.loads((DATA / "expected.json").read_text(encoding="utf-8")),
        }
    )
