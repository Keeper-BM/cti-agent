# MySQL 버전 비교·PostgreSQL 복원 검증 — 2026-11-12 KST

## 실제 MySQL VM

이번 작업에서 새로 만든 `cti-mysql-pair-20261112`를 사용했습니다.
Ubuntu 24.04 noble, arm64, CPU 2개·메모리 3 GiB·디스크 14 GiB입니다.
브리지와 호스트 디렉터리 마운트 없이 기본 Multipass 네트워크를 사용했습니다.
MySQL은 VM의 `127.0.0.1:3306/33060`만 수신하며 수집 계정에는 sudo 권한이 없습니다.
SSH 키는 `restrict`와 root 소유 6개 고정 명령 래퍼로 제한하고 호스트 키를 고정했습니다.

`mysql-client-8.0`, `mysql-client-core-8.0`, `mysql-server`, `mysql-server-8.0`,
`mysql-server-core-8.0`의 5종 패키지를 함께 비교했습니다.

- 기준: `8.0.36-2ubuntu3`, 실제 패키지 691개 수집.
- 수정: `8.0.46-0ubuntu0.24.04.5`, 실제 패키지 691개 수집.
- 복원: `mysql-before-fix` VM 스냅샷 복원 후 `8.0.36-2ubuntu3`, 691개 재수집.

Nginx → API → PostgreSQL → 별도 Worker → 실제 SSH 경로를 사용했습니다.
공식 Ubuntu 자료 287건을 기존 자료 동기화 API로 수집했으며 분석 결과는 2,122건입니다.
CVE-2024-20994의 Ubuntu 수정 기준 `8.0.37-0ubuntu0.24.04.1`에 대해 5개 패키지 모두
`BELOW_FIX → MEETS_FIX → BELOW_FIX`를 확인했습니다. 전후 비교의 자료 기준본은 고정됐고
이전 수집·인벤토리 응답도 동일했습니다. 판정은 세 단계 모두 `NEEDS_REVIEW`이며
출처는 `UNKNOWN`입니다. 버전 관찰만으로 공식 파일 일치나 실제 공격 영향을 확정하지 않았습니다.
기준 근거: [Ubuntu CVE-2024-20994](https://ubuntu.com/security/CVE-2024-20994).

MySQL의 검증 테이블 행은 업그레이드 후와 VM 복원 후 모두 원래 값과 일치했습니다.
두 버전 `.deb` 10개, SHA-256, APT policy·sources·InRelease, OS·아키텍처·실제 서버 버전,
수신 주소와 검증 행을 별도 압축 파일로 보관했습니다.
정지 스냅샷 `mysql-before-fix`와 `mysql-fixed`를 만들었고 최종 VM은 `mysql-fixed`로
원복한 정지 상태입니다. 패키지 다운그레이드로 MySQL 데이터 디렉터리를 재사용하지 않았습니다.

첫 복원 인수 검사에서 수집마다 새로 생성되는 `origin_evidence_ref`까지 같아야 한다는
시험기 오류를 발견했습니다. 패키지/근거 ID를 제외한 상태 비교로 수정하고 실제 복원 재수집과
회귀 시험을 통과했습니다. 이 과정의 추가 수집·비교 이력도 삭제하지 않았습니다.

## PostgreSQL 자동화와 실제 복원

PostgreSQL 17.11, pgvector 0.8.7, Alembic `0011`에서 실행했습니다.
`scripts.postgres_backup`의 `create → verify → restore`를 실제 Compose DB에 적용했습니다.
백업 시 임시 DB 시험 복원과 복원 시 새 DB 내용 대조가 모두 성공했습니다.

최종 덤프에는 사용자 테이블 24개, 자산 1개, 수집/인벤토리 각 4개, 작업 9개,
분석 1개, 비교 3개, 판정 2,122개, 공식 자료 287개, 감사 이벤트 23개가 있습니다.
이번 시험 DB에는 로그인 사용자·세션·보고서 데이터가 없으므로 해당 실제 데이터의 복원
시나리오까지 검증한 것으로 확대하지 않습니다. 전체 테이블의 존재·행 수·내용 해시는 대조했습니다.

- 파일: `.data/mysql-pair-20261112/cti-verified.dump`, manifest는 `.dump.json`.
- 크기: 2,586,031 bytes.
- SHA-256: `0442ff0d8b49e296ac8a04e7ec40b2d64f41d6db1bd76a06cdec5ec57e61ea4b`.
- 새 복원 DB `cti_restored_pair`에 별도 API를 연결해 기준/수정/복원 수집 및 인벤토리
  6개 응답, 기준 분석 1개, 수정/복원 비교 2개 응답이 저장된 원본과 동일함을 확인했습니다.

자동 통합 시험에서는 원본 DB의 백업 후 변경, 한글 JSON과 SERIAL 시퀀스 보존,
따옴표 포함 식별자, 기존 대상 DB 덮어쓰기 거부, manifest 내용 불일치 후 새 DB 정리,
덤프 변조 검출, 검증용 임시 DB 잔여 없음도 확인했습니다.
정기 실행·외부 보관·재해 시 별도 호스트 복구·PITR은 이번 검증 범위가 아닙니다.

## 자동 검사와 증거

- 실제 MySQL SSH VM·PostgreSQL 매트릭스·Compose 복원 시험을 모두 지정한 전체 Python:
  **424 passed, 0 skipped**, 90.23초. 기존 Starlette deprecation 및 JUnit record_property 경고 2건.
- 이후 시험기의 수집별 근거 ID 비교를 수정하고 관련 단위 시험 **8개 통과**.
- 실제 HTTP MySQL 기준·수정·VM 복원 3단계 통과.
- Ruff 검사·포맷, 셸 문법, diff 공백 검사 통과.
- CI에는 Compose PostgreSQL 실제 백업·복원 시험을 추가했습니다. 실제 Multipass VM은
  CI에 연결하지 않으며 위 로컬 실검증과 구분합니다.

Git 제외 `.data/mysql-pair-20261112/`에 `baseline.json`, `upgraded.json`, `restored.json`,
`vm-restoration.json`, `mysql-package-evidence.tgz`, `full-suite.xml`, `postgres-backup.xml`,
`restored-api-verification.json`, 덤프·manifest, 환경 식별 정보를 보관합니다.
개인키·토큰·내부 연결 정보·원시 응답은 커밋하지 않습니다. 시험 컨테이너와 시험 볼륨은
백업·API 대조 완료 후 제거하며 VM 스냅샷과 로컬 증거는 보존합니다.

재실행: [MySQL 비교 환경](mysql-version-pair.md), [PostgreSQL 백업 자동화](postgres-backup.md).
