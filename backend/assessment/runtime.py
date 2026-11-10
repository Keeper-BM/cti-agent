"""Reviewed, CVE-specific applicability. Never waive unrelated runtime conditions."""

from backend.models.runtime import HTTP2_CONDITION

HTTP2_CVE = "CVE-2024-27316"
HTTP2_RELEASE = "24.04"
HTTP2_VULNERABLE = "2.4.58-1ubuntu8"
HTTP2_FIXED = "2.4.58-1ubuntu8.1"


def reviewed_http2_record(data, supported):
    return bool(
        supported
        and data.cve_id == HTTP2_CVE
        and data.package_name == "apache2"
        and data.release == HTTP2_RELEASE
        and data.fixed_version == HTTP2_FIXED
        and HTTP2_VULNERABLE in data.affected_versions
    )


def http2_condition_evidence(inventory, package, advisory, rule):
    observed = inventory.apache_http2
    if not observed:
        return None
    if not (
        rule.runtime_condition == HTTP2_CONDITION
        and advisory.cve_id == HTTP2_CVE
        and rule.package_kind == "SOURCE"
        and rule.package_name == "apache2"
        and rule.release == HTTP2_RELEASE
        and rule.fixed_version == HTTP2_FIXED
        and inventory.os.id == "ubuntu"
        and inventory.os.version_id == HTTP2_RELEASE
        and inventory.os.architecture == "amd64"
        and not inventory.is_synthetic
        and inventory.collection_method == "SSH"
        and package.binary_name == "apache2-bin"
        and package.source_name == "apache2"
        and package.architecture == "amd64"
        and package.origin_status == "OFFICIAL_MATCH"
        and package.source_version == observed.source_version == HTTP2_VULNERABLE
        and package.binary_version == observed.package_version == HTTP2_VULNERABLE
        and inventory.verification_id == observed.verification_id
        and package.origin_evidence_ref == str(observed.verification_id)
        and abs((observed.observed_at - inventory.collected_at).total_seconds()) <= 600
    ):
        return None
    return observed
