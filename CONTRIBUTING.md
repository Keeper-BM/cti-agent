# 개발 가이드

이 문서는 코드 구성, 스키마 갱신, 데이터베이스 변경, 품질 검사 절차를 설명합니다. 애플리케이션 실행은 [README](README.md), 환경 변수는 [설정 안내](docs/configuration.md)를 참고합니다.

## 개발 환경 준비

저장소 루트에서 실행합니다.

```bash
make dev
# API·웹만: make dev-ui
# 설치·설정·마이그레이션만: python3 scripts/dev.py --prepare-only
```

실행기는 Python 3.10 이상에서 동작하며 애플리케이션은 Python 3.12, Node.js는 24를 사용합니다. TypeScript는 API 타입 생성 도구와의 호환성을 위해 5.9 계열로 지정되어 있습니다.

## 기능별 코드 구성

| 구성                    | 위치                                                     |
| ----------------------- | -------------------------------------------------------- |
| HTTP 라우터             | `backend/api/routes/`                                    |
| HTTP 요청·응답 스키마   | `backend/api/schemas/`                                   |
| 도메인 계약·상태 코드   | `backend/models/contracts.py`, `backend/models/enums.py` |
| 데이터베이스 모델       | `backend/models/tables.py`                               |
| 업무 로직               | 수집·정규화·판정·검색·LLM·보고서 모듈                    |
| 화면과 기능별 HTTP 호출 | `frontend/src/features/`                                 |
| 공통 탐색·세션·레이아웃 | `frontend/src/app/`                                      |
| 공통 표시·조회 상태     | `frontend/src/shared/`                                   |

기능 구현은 라우터, 업무 모듈, 화면을 해당 계층에 배치합니다. 도메인 계약과 HTTP 스키마는 용도에 따라 구분하고, 생성된 클라이언트 타입으로 서버·화면의 형식을 맞춥니다.

미구현 기능을 연결할 때에는 API 처리, `capabilities` 플래그, 메뉴 상태, 화면 호출을 함께 갱신합니다. 비동기 작업을 추가하는 경우 작업 접수·실행·상태 조회와 오류 처리가 필요합니다. 기존 501 응답을 성공으로 변경하는 것만으로 기능이 구현되지는 않습니다.

## 작은 변경의 확인

외부 수집·모델 없이 작업할 때에는 [시험 예제 안내](docs/development-example.md)를 사용합니다. 가상 입력, 정규화 자료, 기대 판정과 설명은 `backend/examples/data/`에 있습니다. 화면은 `frontend/src/features/examples/`이며 예제 API는 데이터베이스를 변경하지 않습니다.

```bash
make example
uv run pytest tests/unit/test_example_contracts.py tests/integration/test_examples.py
npm --prefix frontend test
```

패키지 식별값과 버전, 비교 규칙, 근거, 설명의 참조를 함께 유지합니다. 판정 엔진 구현에서는 `AssessmentEngine.assess(inventory, feed)`에 고정된 `FeedSnapshot`을 전달하며 ID만으로 미완성 저장소에 의존하지 않습니다. 예제의 기대 결과를 실제 판정 구현으로 취급하지 않습니다.

## API 명세와 타입 생성

```bash
uv run python scripts/export_openapi.py
npm --prefix frontend run api:types
```

`docs/openapi.json`과 `frontend/src/api/schema.d.ts`는 직접 수정하지 않습니다. 라우터나 HTTP 스키마 변경 후 위 명령으로 갱신합니다. CI는 생성 결과와 저장된 파일의 차이를 검사합니다.

## 데이터베이스 변경

저장 모델 변경 후 Alembic 이력을 생성하고, 자동 생성 결과의 컬럼·제약·데이터 변환·복원 동작을 확인합니다.

```bash
uv run alembic revision --autogenerate -m "describe schema change"
uv run alembic upgrade head
uv run alembic check
```

적용된 마이그레이션의 의미를 변경하지 않고 새 변경 이력을 추가합니다. 데이터 제거·형식 변경이 포함된 이력은 별도 시험 DB에서 적용과 복원을 검증합니다. PostgreSQL 전용 기능은 SQLite 결과만으로 확인할 수 없습니다.

## 품질 검사

```bash
uv run ruff check backend scripts tests
uv run ruff format --check backend scripts tests
uv run pytest
npm --prefix frontend run format:check
npm --prefix frontend test
npm --prefix frontend run build
```

포맷을 적용할 때에는 다음 명령을 사용합니다.

```bash
uv run ruff format backend scripts tests
npm --prefix frontend run format
```

테스트는 도메인 계약·예제 참조, 환경 초기화, 오류 진단, API, Worker, 마이그레이션을 검사합니다. 프론트엔드 테스트는 Node.js 내장 실행기로 조회 완료·갱신·취소·오류 복구를 검사합니다. PostgreSQL 전용 테스트는 `TEST_POSTGRES_URL`에 시험 전용 DB를 지정한 경우 실행합니다. 자세한 환경과 결과는 [검증 기록](docs/verification.md)을 참고합니다.

## 의존성과 실행 자료

Python 의존성 변경에는 `pyproject.toml`과 `uv.lock`, 프론트엔드 의존성 변경에는 `package.json`과 `package-lock.json`을 갱신합니다. 잠금 파일은 해당 패키지 관리 도구로 생성합니다.

가상 시험 자료는 실제 수집·판정 결과와 구분합니다. 실제 사례에는 적용 환경과 공식 근거를 기록합니다. 개인키, 실제 계정, 내부 접속 정보, VM 이미지, 모델 가중치는 소스 저장소에 포함하지 않습니다.

## 구현 원칙

- 판정 불가·자료 부재·수집 실패를 비영향 결과로 변환하지 않습니다.
- 패키지 전체 버전과 소스·바이너리 구분을 보존합니다.
- 판정 상태는 규칙과 데이터로 결정하고 모델은 설명을 생성합니다.
- 수집은 허용된 대상과 고정된 읽기 명령으로 제한합니다.
- 오류 응답은 입력값과 내부 예외 내용을 노출하지 않고 요청 ID로 추적합니다.
