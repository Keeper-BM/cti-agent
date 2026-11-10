"""Small synthetic wire-format fixtures; not evidence of actual CVE impact."""

CVE = "CVE-2099-10001"
OTHER_CVE = "CVE-2099-10002"
UBUNTU = {
    "vulns": [
        {
            "id": f"UBUNTU-{CVE}",
            "details": "Synthetic conditional vulnerability",
            "published": "2026-01-01T00:00:00Z",
            "modified": "2026-02-01T00:00:00Z",
            "affected": [
                {
                    "package": {"name": "apache2", "ecosystem": "Ubuntu:22.04:LTS"},
                    "ranges": [
                        {
                            "type": "ECOSYSTEM",
                            "events": [{"introduced": "0"}, {"fixed": "2.4.52-1ubuntu4.4"}],
                        }
                    ],
                    "versions": ["2.4.52-1ubuntu4.3"],
                }
            ],
            "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/TEST"}],
            "references": [{"url": "https://www.oracle.com/security-alerts/cpujan2024.html"}],
        }
    ],
}
NVD = {
    "totalResults": 1,
    "vulnerabilities": [
        {
            "cve": {
                "id": CVE,
                "vulnStatus": "Analyzed",
                "descriptions": [{"lang": "en", "value": "Synthetic NVD description"}],
                "metrics": {
                    "cvssMetricV31": [
                        {
                            "source": "nvd@nist.gov",
                            "cvssData": {
                                "version": "3.1",
                                "vectorString": "CVSS:3.1/TEST",
                                "baseScore": 9.8,
                            },
                        }
                    ]
                },
                "weaknesses": [{"description": [{"value": "CWE-444"}]}],
                "references": [
                    {"url": "javascript:alert(1)"},
                    {"url": "https://example.invalid/reference"},
                ],
            }
        }
    ],
}
KEV = {
    "count": 1,
    "catalogVersion": "test",
    "dateReleased": "2026-11-09T00:00:00Z",
    "vulnerabilities": [
        {
            "cveID": CVE,
            "vulnerabilityName": "Synthetic KEV",
            "shortDescription": "Test only",
            "dateAdded": "2026-11-09",
            "vendorProject": "Example",
            "product": "Example",
            "requiredAction": "Apply vendor instructions",
            "knownRansomwareCampaignUse": "Unknown",
        }
    ],
}
APACHE = f'''<html><dl><dt><h3 id="{CVE}">Example Apache issue</h3></dt><dd>
<p>Only affects a particular configuration.</p><table>
<tr><td>Update 2.4.56 released</td><td>2023-03-07</td></tr>
<tr><td>Affects</td><td>2.4.0 through 2.4.55</td></tr></table></dd></dl></html>'''
ORACLE = f"""<h3>Oracle MySQL Risk Matrix</h3><table><thead><tr>
<th>CVE ID</th><th>Product</th><th>Supported Versions Affected</th></tr></thead>
<tbody><tr><th>{CVE}</th><td>MySQL Server</td><td>8.0.34 and prior</td></tr>
<tr><th>{CVE}</th><td>MySQL Cluster</td><td>8.0.34 and prior</td></tr></tbody></table>"""
