# PostgreSQL 통합 시험

## 기존 검사와 확장 범위

기본 `pytest`는 대부분의 통합 검사를 임시 SQLite DB에서 실행합니다.
`TEST_POSTGRES_URL`을 지정하면 기존 `test_postgres.py`가 PostgreSQL 마이그레이션·
pgvector 확장·작업 처리·단일 Worker 잠금을 추가 검사합니다.

`--postgres-matrix`를 추가하면 다음 6개 파일의 기존 시험을 SQLite와 PostgreSQL에서
각각 실행합니다. 기대값이나 API 시나리오를 복제하지 않고 같은 검사를 재사용합니다.

- `test_api.py`: 자산 CRUD·비활성화, 인증, 입력 검증, 작업 멱등성.
- `test_asset_csv.py`: 수정 감사 이력, CSV 입력·JSON과의 동일 검증, 거절된 입력의 무변경.
- `test_inventories.py`: 불변 스냅샷, 페이지 조회, 잘못된 JSON·초과 크기·자산 범위.
- `test_auth.py`: 세션·만료·CSRF·실패 제한, 역할·자산·작업·보고서 권한과 권한 회수.
- `test_collections.py`: 실제 루프백 SSH 프로토콜과 가상 원격 출력, 정상·부분·실패,
  서비스 관찰, 고정 호스트 키·허가 대상·동시 실행 제한·기존 이력 보존.
- `test_worker.py`: 작업 처리, 중단 복구, 감사 이벤트 중복 방지 및 트랜잭션 롤백.

SSH fixture의 출력은 합성 자료입니다. 실제 Ubuntu·MySQL 시험과는 구분하며,
판정 엔진·LLM 전체를 PostgreSQL 매트릭스로 검증했다고 주장하지 않습니다.
기존 SSH→분석→보고서와 권한 연결 검사는 해당 파일의 일부로 함께 실행됩니다.

## 실행과 데이터 격리

**전용 시험 PostgreSQL 서버**를 사용합니다. `TEST_POSTGRES_URL`의 계정은 DB 생성
권한과 마이그레이션에 필요한 pgvector 확장 생성 권한이 있어야 합니다.
URL은 비공개 환경 변수로 주입하고 셸 기록·로그·소스 저장소에 남기지 않습니다.

```bash
# TEST_POSTGRES_URL은 전용 시험 DB 접속 정보로 미리 설정합니다.
uv run pytest --postgres-matrix

# PostgreSQL에 추가된 검사만 빠르게 확인합니다.
uv run pytest --postgres-matrix -k postgresql tests/integration
```

옵션을 지정했는데 URL이 없으면 검사를 건너뛰지 않고 설정 오류로 종료합니다.
`tests/fixtures/database.py`는 각 검사에 UUID 이름의 `cti_test_*` DB를 생성하고
실제 Alembic 마이그레이션을 적용합니다. API와 Worker가 그 DB를 함께 사용합니다.
종료 시 연결을 정리하고 **해당 검사에서 생성에 성공한 DB만** 제거합니다.
외부에서 넘긴 DB 이름을 DROP 명령에 사용하지 않습니다.

기존 단독 `test_postgres.py`는 URL에 지정한 DB에 마이그레이션을 적용하므로 그 DB도
전용 시험 DB여야 합니다. 강제 프로세스 종료로 fixture 정리가 실행되지 않았다면
공유 서버에서 이름만 보고 삭제하지 말고 시험 전용 서버·컨테이너 자체를 정리합니다.

CI의 PostgreSQL 서비스는 전용 pgvector 0.8.7/PostgreSQL 17 컨테이너이며
백엔드 명령을 `uv run pytest --postgres-matrix`로 확장했습니다.
원격 CI 결과와 로컬 실행 결과는 구분합니다.

## 로컬 검증 — 2026-11-11 KST

별도 Docker PostgreSQL 17.11·pgvector 0.8.7 서버에서 추가 매트릭스의
**67개 PostgreSQL 검사 통과, 29.72초**를 확인했습니다.
SQLite 67개는 이 표적 실행에서 선택하지 않았으며 건너뛰기 성공으로 세지 않습니다.
기존 TestClient deprecation 경고 1건이 있습니다.

JUnit·실행 로그는 Git 제외 경로 `.data/postgres-matrix-20261111/`에 보관합니다.

같은 서버와 실제 Ubuntu 22.04 Apache·MySQL을 연결한 최종 전체 실행은
**398 passed, 0 skipped / 74.11초**입니다. SQLite·PostgreSQL 두 실행의 67개씩과
기존 단독 PostgreSQL 검사, 실제 VM 수집·호스트 키 오류·SQLite 백업 복원을 포함합니다.
검사 후 `cti_test_*` DB가 0개 남았음을 확인하고 전용 컨테이너를 제거했습니다.

최종 JUnit 실행에는 TestClient deprecation 경고와 `record_property`/xunit2 호환 경고
각 1건이 있었습니다. 실패·누락은 없었습니다. VM 메타데이터를 포함한 JUnit을 재생성할 때는
`--junitxml=시험결과.xml -o junit_family=legacy`를 지정해 두 번째 경고를 피할 수 있습니다.
