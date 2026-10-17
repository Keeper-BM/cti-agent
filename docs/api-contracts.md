# API 및 데이터 계약

HTTP API의 기준 명세는 코드에서 생성한 [OpenAPI](openapi.json)입니다. 실행 중인 서버는 `/api/openapi.json`과 `/api/docs`를 제공합니다. API 기본 경로는 `/api/v1`입니다.

## 인증

`health`와 `readiness`를 제외한 모든 경로는 다음 헤더를 요구합니다.

```http
Authorization: Bearer <DEV_API_TOKEN>
```

현재 인증은 개발용 공통 토큰을 비교하는 방식입니다. 사용자 계정, 세션 만료, 자산별 접근 권한은 구현되지 않았습니다. 토큰은 최소 32자이며 `.env` 또는 실행 환경에 설정합니다.

## 구현된 경로

| 메서드 | 경로                   | 동작                                                      | 정상 상태 |
| ------ | ---------------------- | --------------------------------------------------------- | --------- |
| GET    | `/health`              | 프로세스 응답과 API 버전 확인                             | 200       |
| GET    | `/readiness`           | DB 연결, 마이그레이션 이력, 자산·작업 테이블 접근 확인    | 200       |
| GET    | `/examples/assessment` | 연결된 가상 입력·기대 판정·설명 조회; 저장·외부 연결 없음 | 200       |
| GET    | `/capabilities`        | 실행 모드와 기능 플래그 조회                              | 200       |
| GET    | `/assets`              | 자산 목록·전체 개수 조회                                  | 200       |
| POST   | `/assets`              | 수동 자산 등록                                            | 201       |
| GET    | `/assets/{asset_id}`   | 자산 상세 조회                                            | 200       |
| PATCH  | `/assets/{asset_id}`   | 활성 상태 변경                                            | 200       |
| POST   | `/jobs/system-checks`  | 연결 확인 작업 접수                                       | 202       |
| GET    | `/jobs`                | 작업 목록·전체 개수 조회                                  | 200       |
| GET    | `/jobs/{job_id}`       | 작업 결과·오류·시각 조회                                  | 200       |

표의 경로는 `/api/v1` 기준 상대 경로입니다. 목록 응답은 `items`와 `total`을 포함하며 `limit`은 1~100, `offset`은 0 이상입니다. 기본 `limit`은 자산 50건, 작업 20건입니다. 두 목록은 생성 시각 내림차순으로 조회합니다.

`capabilities.features`에서 `assets`, `worker_system_check`, `development_examples`가 `true`입니다. `ssh_collection`, `security_feeds`, `assessment`, `rag`, `reports`, `user_accounts`는 `false`입니다.

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

등록 스키마는 정의되지 않은 필드를 거부합니다. PATCH 요청은 `{"is_active": false}` 또는 `{"is_active": true}`만 처리합니다. 이름·주소 등 일반 수정, 삭제, 파일 입력은 아직 제공하지 않습니다.

## 작업 접수와 상태

`POST /jobs/system-checks`는 `Idempotency-Key` 헤더를 요구합니다. 키는 영문·숫자·`_`·`-`로 구성된 1~100자 문자열입니다.

동일한 키를 다시 전송하면 기존 작업을 반환합니다. 기존 작업의 성공·실패 상태와 무관하게 중복 실행하지 않습니다. 새 실행에는 새로운 키가 필요합니다. 접수 응답은 작업 ID와 상태를 포함하며 처리 결과는 작업 조회 API에서 확인합니다.

현재 처리 흐름은 `QUEUED → RUNNING → SUCCEEDED/FAILED`입니다. Worker 연결 확인은 데이터베이스 접근만 검증하며 서버 접속이나 모델 추론을 수행하지 않습니다.

## 미구현 경로

다음 경로는 인증 및 입력 검증 후 `501 FEATURE_NOT_IMPLEMENTED`를 반환합니다. 분석 결과·작업·파일은 생성하지 않습니다. 형식이 잘못된 요청은 먼저 422를 반환할 수 있습니다.

| 메서드                | 경로                                               | 정의된 계약                                                     |
| --------------------- | -------------------------------------------------- | --------------------------------------------------------------- |
| POST                  | `/assets/{asset_id}/collections`                   | 기존 자산의 수집 요청; 자산이 없으면 404                        |
| GET                   | `/sources/status`                                  | 공식 자료 상태 조회 위치                                        |
| POST                  | `/sources/{source_id}/sync`                        | 공식 자료 갱신 요청 위치                                        |
| POST                  | `/analyses`                                        | `inventory_id`, `feed_snapshot_id`                              |
| GET                   | `/findings`                                        | 자산·판정 필터, 페이지 조회; `FindingList` 응답 스키마          |
| GET                   | `/findings/{finding_id}`                           | `FeedSnapshot`                                                  | 고정된 자료 기준본, 정규화 공지·패키지 규칙·근거, 가상 여부 | 정규화 → 판정 |
| `FeedSnapshot`        | 자료 기준본·정규화 공지·패키지 규칙·근거·가상 여부 | 정규화 → 판정                                                   |
| `Finding` 응답 스키마 |
| POST                  | `/questions`                                       | `requested_asset_ids` 1~20개, 공백 제거 후 `question` 1~2,000자 |
| POST                  | `/reports`                                         | `analysis_ids` 1~20개                                           |
| GET                   | `/reports/{report_id}`                             | 보고서 조회 위치                                                |
| GET                   | `/reports/{report_id}/markdown`                    | Markdown 출력 위치                                              |

`GET /findings`의 필터는 `asset_id`와 `verdict`이며, 기본 `limit`은 20입니다. 응답 스키마의 존재는 해당 경로에서 성공 결과가 제공된다는 의미가 아닙니다. 분석·질의·보고서 요청의 `schema_version` 기본값은 `1.0`입니다.

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
| 401  | 개발 토큰 누락 또는 불일치       |
| 404  | 자산·작업·경로를 찾을 수 없음    |
| 409  | 중복 자산 이름                   |
| 422  | 요청 필드·형식 검증 실패         |
| 500  | 내부 처리 오류                   |
| 501  | 미구현 기능                      |
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

이 검증은 데이터 구조의 일관성에 관한 것입니다. 실제 공식 출처의 신뢰성, 자산 접근 권한, 판정 알고리즘과 인용의 정확성은 후속 구현 대상입니다.

## 정규화와 패키지 참조

`InstalledPackage.package_id`는 스냅샷 안의 패키지를 식별합니다. `Finding.package_ref`는 해당 ID를 참조하며 `installed_version`과 `comparison_basis`에 실제 대조한 버전과 `BINARY` 또는 `SOURCE`를 기록합니다. `matched_rule_id`는 자료 기준본 안의 규칙을 식별합니다.

`FeedSnapshot`은 기준본 ID·수집 시점·정규화 버전·공지 목록을 포함합니다. 공지는 CVE·근거와 `AdvisoryPackageRule` 목록으로 구성됩니다. 규칙은 패키지 종류·이름, OS·릴리스·선택적 아키텍처, 공지 상태, 전체 수정 버전과 `DEBIAN` 비교 방식을 보존합니다. 공지 상태는 `AFFECTED`, `FIX_RELEASED`, `NOT_AFFECTED`, `UNKNOWN`이며 설치 자산의 판정값과 구분합니다. 해결되지 않은 조건은 `limitations`에 기록합니다.

판정 인터페이스는 `assess(inventory, feed)`로 두 개의 고정 입력을 받습니다. 실제 출처별 정규화와 버전·조건 대조 구현은 미구현입니다. [시험 예제](development-example.md)는 이 계약을 연결한 가상 JSON과 기대 출력을 제공합니다.

## 개발용 예제 응답

`GET /examples/assessment`의 `AssessmentExample`에는 `is_synthetic=true`, `inventory`, `feed`, `expected_findings`, `expected_answer`가 포함됩니다. 패키지·버전·자료·규칙·인용 참조를 적재 시 검증합니다. 실제 판정·설명 실행 응답을 대신하지 않으며 자산·작업 테이블을 변경하지 않습니다.

## 명세 생성

```bash
uv run python scripts/export_openapi.py
npm --prefix frontend run api:types
```

`docs/openapi.json`과 `frontend/src/api/schema.d.ts`는 생성 파일입니다. 원본 HTTP 스키마는 `backend/api/schemas/`에, 기능별 클라이언트 호출은 `frontend/src/features/*/api.ts`에 있습니다.
