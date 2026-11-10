# API 및 데이터 계약

HTTP API의 기준 명세는 코드에서 생성한 [OpenAPI](openapi.json)입니다. 실행 중인 서버는 `/api/openapi.json`과 `/api/docs`를 제공합니다. API 기본 경로는 `/api/v1`입니다.

## 인증

`GET /health`, `/readiness`, `/auth/status`와 로그인은 공개 경로입니다. 나머지는 선택한 인증 모드를 적용합니다.

- `AUTH_MODE=accounts`: 로그인 쿠키, 변경 요청의 `X-CSRF-Token`, 역할·자산 권한
- `AUTH_MODE=token`: `Authorization: Bearer <DEV_API_TOKEN>` 개발 관리자 연결

`POST /auth/login`, `GET /auth/me`, `POST /auth/logout`, `POST /auth/password`를 제공합니다. 관리자 경로는 `/admin/users`, `/admin/users/{id}`, `/admin/assets/{asset_id}/grants`, `/admin/assets/{asset_id}/grants/{user_id}`, `/audit`입니다. [계정·세션·복원 안내](operations.md)를 참고하세요.

## 구현된 경로

| 메서드 | 경로                                            | 동작                                                               | 정상 상태 |
| ------ | ----------------------------------------------- | ------------------------------------------------------------------ | --------- |
| GET    | `/health`                                       | 프로세스 응답과 API 버전 확인                                      | 200       |
| GET    | `/readiness`                                    | DB 연결, 마이그레이션 이력, 자산·작업·패키지 기록 테이블 접근 확인 | 200       |
| GET    | `/examples/assessment`                          | 연결된 가상 입력·기대 판정·설명 조회; 저장·외부 연결 없음          | 200       |
| GET    | `/capabilities`                                 | 실행 모드와 기능 플래그 조회                                       | 200       |
| GET    | `/assets`                                       | 자산 목록·전체 개수 조회                                           | 200       |
| POST   | `/assets`                                       | 수동 자산 등록                                                     | 201       |
| GET    | `/assets/{asset_id}`                            | 자산 상세 조회                                                     | 200       |
| PATCH  | `/assets/{asset_id}`                            | 이름·주소·예상 릴리스·노출·담당자·활성 상태 수정                   | 200       |
| POST   | `/assets/{asset_id}/inventories`                | JSON 패키지 정보 검증·새 기록 저장                                 | 201       |
| GET    | `/assets/{asset_id}/inventories`                | 입력 이력 요약·전체 개수 조회                                      | 200       |
| GET    | `/assets/{asset_id}/inventories/{inventory_id}` | 해당 자산의 기록과 패키지 목록 조회                                | 200       |
| POST   | `/jobs/system-checks`                           | 연결 확인 작업 접수                                                | 202       |
| GET    | `/jobs`                                         | 작업 목록·전체 개수 조회                                           | 200       |
| GET    | `/jobs/{job_id}`                                | 작업 결과·오류·시각 조회                                           | 200       |
| POST   | `/analyses`                                     | 패키지 입력·출처 고정과 분석 접수 (`Idempotency-Key` 필수)         | 202       |
| GET    | `/analyses`                                     | 자산별 분석 이력·작업 상태·요약                                    | 200       |
| GET    | `/analyses/{analysis_id}`                       | 분석 당시의 입력·출처·경고                                         | 200       |
| GET    | `/findings`                                     | 분석 ID·자산·판단·처리 상태·패키지/CVE 검색                        | 200       |
| GET    | `/findings/{finding_id}`                        | 비교 결과·판단 이유·당시 공식 출처·원문 참조                       | 200       |

표의 경로는 `/api/v1` 기준 상대 경로입니다. 목록 응답은 `items`와 `total`을 포함하며 `limit`은 1~100, `offset`은 0 이상입니다. 기본 `limit`은 자산 50건, 작업 20건입니다. 두 목록은 생성 시각 내림차순으로 조회합니다.

기능 플래그는 assets, inventory_import, ssh_collection, package_verification, security_feeds, assessment, ai_explanations, rag, reports, user_accounts, audit, comparisons, remediation, worker_system_check, development_examples가 true입니다. 기능 제공 여부이며 학교 API 설정·원격 서버 접속 성공을 뜻하지 않습니다.

## 자산 입력

```json
{
  "asset_name": "ubuntu-test",
  "host": "192.0.2.10",
  "expected_release": null,
  "exposure": "UNKNOWN",
  "exposure_source": "manual registration",
  "criticality": "UNKNOWN",
  "collection_method": "MANUAL"
}
```

예시는 문서용 주소를 사용하며 실제 수집 대상을 의미하지 않습니다.

| 필드                 | 제약                                                                  |
| -------------------- | --------------------------------------------------------------------- |
| `asset_name`         | 앞뒤 공백 제거 후 1~100자, 저장소 내 고유값                           |
| `host`               | IP 또는 호스트명, 최대 253자, 생략 가능; URL·포트·명령 문자열 제외    |
| `expected_release`   | `22.04`, `24.04` 또는 `null`; 입력 후보이며 검증된 지원 릴리스가 아님 |
| `exposure`           | `PUBLIC`, `INTERNAL`, `UNKNOWN`                                       |
| `exposure_source`    | 공개 범위 정보의 출처, 1~200자                                        |
| `criticality`        | `HIGH`, `MEDIUM`, `LOW`, `UNKNOWN`                                    |
| `owner_display_name` | 자산 관리 표시명, 최대 100자, 생략 가능                               |
| `collection_method`  | 현재 등록 API는 `MANUAL`만 허용                                       |

등록·수정은 정의되지 않은 필드를 거부합니다. PATCH는 변경 필드만 보내며 collection_method는 수정하지 않습니다. 이름·필수 출처 문자열은 공백만 허용하지 않습니다. host·expected_release·owner_display_name은 null로 비울 수 있습니다. 기존 인벤토리·분석의 이름과 판단 기준은 수정하지 않습니다.

JSON 입력은 `/assets/{asset_id}/inventories`, CSV는 `/assets/{asset_id}/inventories/csv`의 `{"csv_text":"UTF-8 CSV 내용"}`으로 201 응답을 반환합니다. 모든 업로드는 새 기록을 생성합니다. [입력 형식](inventory-import.md).

## 작업 접수와 상태

`POST /jobs/system-checks`는 `Idempotency-Key` 헤더를 요구합니다. 키는 영문·숫자·`_`·`-`로 구성된 1~100자 문자열입니다.

동일한 키를 다시 전송하면 기존 작업을 반환합니다. 기존 작업의 성공·실패 상태와 무관하게 중복 실행하지 않습니다. 새 실행에는 새로운 키가 필요합니다. 접수 응답은 작업 ID와 상태를 포함하며 처리 결과는 작업 조회 API에서 확인합니다.

현재 처리 흐름은 `QUEUED → RUNNING → SUCCEEDED/PARTIAL/FAILED`입니다. Worker 연결 확인은 데이터베이스 접근만 검증하며 서버 접속이나 모델 추론을 수행하지 않습니다.

## 공식 자료 API

`GET /sources/status`, `POST /sources/{source_id}/sync`, `GET /sources/snapshots`, `GET /sources/records`, `GET /sources/cves/{cve_id}`, `GET /sources/documents/{document_id}`를 제공합니다. 수집은 `Idempotency-Key`를 가진 명시적 요청으로 접수하고 `SOURCE_SYNC` Worker가 처리합니다. [출처·요청 형식·이력 규칙](security-sources.md)을 참고하세요.

## CVE AI 설명

`GET /explanations/status`, `POST /explanations`, `GET /explanations?finding_id=UUID`, `GET /explanations/{id}`를 제공합니다. 요청 본문은 `{"finding_id":"UUID"}`이며 `Idempotency-Key`가 필요합니다. `EXPLANATION` Worker 작업으로 생성하고 검증된 결과만 저장합니다. 설정·입력 범위·오류·인용 검증의 의미는 [AI 설명 안내](ai-explanations.md)를 따릅니다. 선택 분석에 대한 질문은 별도의 `/questions` API입니다.

## 대응 보고서

`POST /reports`, `GET /reports`, `GET /reports/{id}`, `GET /reports/{id}/markdown`을 제공합니다. 요청은 `{"analysis_id":"UUID","include_ai_explanations":false}`이며 `Idempotency-Key`가 필요합니다. 완료된 한 분석을 요청 시점에 고정하고 `REPORT` 작업으로 생성합니다. 마지막 경로는 저장된 UTF-8 Markdown을 첨부파일로 반환하며 미완료 시 409입니다. 기존 미구현 `analysis_ids` 배열은 받지 않습니다. [전체 계약과 저장 의미](reports.md).

## SSH 패키지 수집

`GET /collections/settings`, `GET/PUT /assets/{asset_id}/ssh-profile`, `POST/GET /assets/{asset_id}/collections`, `GET /assets/{asset_id}/collections/{id}`를 제공합니다. 수집 요청은 `{"profile_id":"UUID"}`와 `Idempotency-Key`가 필요하며 `SSH_COLLECTION` 작업을 반환합니다. 실행 시점에도 허용 대상을 재검사하고, 요청 당시 프로필과 조회 근거를 보존합니다. [설정·상태·오류·검증 한계](ssh-collection.md).

## 공식 파일 검증·질문·비교

| POST 경로                          | 입력                                                           | 상세 조회            |
| ---------------------------------- | -------------------------------------------------------------- | -------------------- |
| `/assets/{asset_id}/verifications` | `{"inventory_id":"UUID"}`                                      | 같은 경로 뒤 `/{id}` |
| `/questions`                       | `{"analysis_ids":["UUID"],"question":"질문 내용"}`             | `/questions/{id}`    |
| `/comparisons`                     | `{"baseline_analysis_id":"UUID","target_inventory_id":"UUID"}` | `/comparisons/{id}`  |

세 경로는 Idempotency-Key와 실행 권한이 필요하고 202로 접수합니다. 동일 경로의 GET은 limit·offset 이력을 제공합니다. 질문은 분석 1~5개·공백 제거 후 5~2,000자이며 모든 자산의 권한을 검사합니다. 실제 SSH 인벤토리만 파일 검증할 수 있습니다. 비교는 같은 자산·OS 릴리스·아키텍처의 다른 인벤토리만 받습니다.

[검증 계약](package-verification.md), [질문·조치·비교 계약](insights-comparisons.md)을 참고하세요. 대응 안내는 새 AssessmentFinding의 remediation 필드에 포함됩니다. 오래된 분석에는 이 필드가 없을 수 있습니다.

## 공통 오류

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "입력값을 확인하세요: body.asset_name",
    "request_id": "server-generated-uuid",
    "retryable": false
  }
}
```

요청 ID는 `X-Request-ID` 헤더에도 포함됩니다. 응답에는 `Cache-Control: no-store`를 적용합니다. 검증 오류는 필드 위치를 표시하며 원래 입력값, SQL, 내부 예외 내용은 반환하지 않습니다.

| 상태 | 의미                             |
| ---- | -------------------------------- |
| 401  | 로그인·토큰 누락, 세션 만료      |
| 403  | 역할·CSRF·접근 권한 거절         |
| 404  | 자산·작업·경로를 찾을 수 없음    |
| 409  | 중복 자산 이름, 비활성 자산 입력 |
| 413  | 패키지 파일 2 MiB 크기 초과      |
| 422  | 요청 필드·형식 검증 실패         |
| 500  | 내부 처리 오류                   |
| 429  | 로그인 요청 한도 초과            |
| 502  | 외부 응답·모델·검증 처리 실패    |
| 503  | 데이터베이스 준비 상태 확인 실패 |

## 도메인 계약

`backend/models/contracts.py`는 수집·판정·검색·설명을 연결하는 초기 Python 모델을 정의합니다. HTTP 응답 스키마와 데이터베이스 테이블은 별도로 관리합니다.

| 계약                | 주요 내용                                            | 사용 방향          |
| ------------------- | ---------------------------------------------------- | ------------------ |
| `InventorySnapshot` | 자산·스냅샷 ID, 시각, OS, 패키지, 출처 수준, 완전성  | 수집 → 판정        |
| `Finding`           | 패키지 참조·설치 버전·비교 기준·규칙, 상태·판정·근거 | 판정 → API·설명    |
| `Evidence`          | 문서 버전 ID, 출처, 제목, 원문 주소, 발췌            | 검색 → 설명·보고서 |
| `Answer`            | 자산 범위, 분석 ID, 설명, 인용, 경고                 | 설명 → 화면·보고서 |

현재 모델은 다음 불변 조건을 검증합니다.

- 패키지 ID는 인벤토리 안에서, 규칙 ID는 보안 자료 기준본 안에서 고유합니다.
- `FIX_RELEASED` 정규화 규칙에는 전체 수정 버전이 필요합니다.
- 완전한 수집은 OS 식별값과 완전한 패키지 목록을 요구합니다. 불완전한 수집은 완전한 목록으로 표시할 수 없습니다.
- `EVALUATED` 상태에는 `verdict`가 필수이며 다른 처리 상태에는 판정값이 없습니다.
- `AFFECTED`, `FIXED`, `NOT_AFFECTED`에는 CVE ID, 근거, 자료 기준본 ID, 패키지 참조, 설치 버전, 비교 기준과 규칙 ID가 필요합니다.

이 검증은 데이터 구조의 일관성에 관한 것입니다. 계정 모드의 자산 접근 검사와 공식 패키지 검증은 별도의 실행 경로에서 적용합니다. 한 CVE AI 설명은 기준값·인용 ID 검사를 제공하며 의미 전체의 일치는 보장하지 않습니다. 판정 구현의 한계는 분석 안내에 명시합니다.

## 정규화와 패키지 참조

`InstalledPackage.package_id`는 스냅샷 안의 패키지를 식별합니다. `Finding.package_ref`는 해당 ID를 참조하며 `installed_version`과 `comparison_basis`에 실제 대조한 버전과 `BINARY` 또는 `SOURCE`를 기록합니다. `matched_rule_id`는 자료 기준본 안의 규칙을 식별합니다.

`FeedSnapshot`은 기준본 ID·수집 시점·정규화 버전·공지 목록을 포함합니다. 공지는 CVE·근거와 `AdvisoryPackageRule` 목록으로 구성됩니다. 규칙은 패키지 종류·이름, OS·릴리스·선택적 아키텍처, 공지 상태, 전체 수정 버전과 `DEBIAN` 비교 방식을 보존합니다. 공지 상태는 `AFFECTED`, `FIX_RELEASED`, `NOT_AFFECTED`, `UNKNOWN`이며 설치 자산의 판정값과 구분합니다. 해결되지 않은 조건은 `limitations`에 기록합니다.

판정 인터페이스는 `assess(inventory, feed)`로 두 개의 고정 입력을 받습니다. 실제 출처 자료는 `backend/sources/`의 `SecurityRecord`로 정규화·저장합니다. `backend/assessment/`가 고정된 Ubuntu 자료를 판정 입력으로 변환하고 비교·판단을 저장합니다. [시험 예제](development-example.md)는 별도의 가상 JSON과 기대 출력을 제공합니다.

## 개발용 예제 응답

`GET /examples/assessment`의 `AssessmentExample`에는 `is_synthetic=true`, `inventory`, `feed`, `expected_findings`, `expected_answer`가 포함됩니다. 패키지·버전·자료·규칙·인용 참조를 적재 시 검증합니다. 실제 판정·설명 실행 응답을 대신하지 않으며 자산·작업 테이블을 변경하지 않습니다.

## 명세 생성

```bash
uv run python scripts/export_openapi.py
npm --prefix frontend run api:types
```

`docs/openapi.json`과 `frontend/src/api/schema.d.ts`는 생성 파일입니다. 원본 HTTP 스키마는 `backend/api/schemas/`에, 기능별 클라이언트 호출은 `frontend/src/features/*/api.ts`에 있습니다.
