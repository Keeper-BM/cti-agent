from backend.verification.contracts import FileCheck, PackageCheck


def compare_package(package, artifact, observed):
    base = {
        "package_id": str(package.package_id),
        "name": package.binary_name,
        "version": package.binary_version,
        "architecture": package.architecture,
    }
    if artifact is None:
        return PackageCheck(
            **base,
            status="UNAVAILABLE",
            message="현재 서명된 저장소 목록에서 동일한 패키지 버전을 찾지 못했습니다.",
        )
    checks, missing = [], False
    for path, expected in sorted(artifact["files"].items()):
        actual = observed.get(path, {"status": "UNREADABLE"})
        kind = expected["kind"]
        value = expected.get("sha256") if kind == "file" else expected.get("target")
        observed_value = (
            actual.get("sha256") if actual.get("kind") == "file" else actual.get("target")
        )
        if expected.get("configuration"):
            status = "CONFIGURATION"
        elif actual.get("status") != "OK":
            status = (
                actual.get("status")
                if actual.get("status") in {"MISSING", "UNREADABLE", "UNSUPPORTED"}
                else "UNREADABLE"
            )
            missing = True
        else:
            same = actual.get("kind") == kind and value == observed_value
            if kind == "file":
                same = same and all(
                    actual.get(k) == expected.get(k) for k in ("mode", "uid", "gid")
                )
            status = "MATCH" if same else "DIFFERENT"
        checks.append(
            FileCheck(path=path, kind=kind, expected=value, observed=observed_value, status=status)
        )
    compared = [f for f in checks if f.status != "CONFIGURATION"]
    if not compared or missing:
        status, message = (
            "UNAVAILABLE",
            "일부 파일을 검사하지 못했습니다. 누락·권한·지원 범위를 확인하세요.",
        )
    elif any(f.status == "DIFFERENT" for f in compared):
        status, message = (
            "DIFFERENT",
            "공식 배포본과 다른 파일·권한이 있습니다. 악성 변조 여부는 별도로 확인해야 합니다.",
        )
    else:
        status, message = (
            "MATCH",
            "검사한 파일이 공식 배포본과 일치합니다. 설정·실행 중인 코드는 별도 확인 대상입니다.",
        )
    return PackageCheck(
        **base, status=status, message=message, archive=artifact["proof"], files=checks
    )
