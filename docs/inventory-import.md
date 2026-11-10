# 패키지 정보 입력·저장·조회

자산에 Ubuntu 패키지 정보를 JSON 파일로 입력하고, 입력 시점별 기록을 조회합니다. 이 기능은 파일 입력과 저장을 수행하며 SSH 접속이나 취약점 판정은 실행하지 않습니다.

SSH로 직접 가져온 패키지도 같은 기록 목록에서 조회합니다. 접속 설정과 수집은 별도 [SSH 패키지 수집](ssh-collection.md) 기능을 이용하세요. 화면은 파일 입력값과 SSH 조회값을 구분합니다.

## 화면 사용 순서

1. 서비스에 연결하고 **자산 현황**에서 자산을 등록하거나 기존 자산 이름을 선택합니다.
2. 아래 **패키지 정보** 영역에서 **입력 예제 다운로드**를 누릅니다.
3. 파일 내용을 수정한 뒤 JSON 파일을 선택하고 **선택한 파일 저장**을 누릅니다.
4. 운영체제, 패키지 목록, 정보 확인 시각과 서버의 저장 시각을 확인합니다.
5. **입력 이력**을 펼쳐 이전 기록을 선택합니다. 패키지가 많으면 이름·아키텍처 검색과 페이지 이동을 사용합니다.

새 저장은 항상 새 기록을 생성합니다. 같은 파일을 다시 저장해도 기존 기록을 덮어쓰지 않습니다. 실패한 입력은 기록을 만들지 않습니다. 계정 모드에서는 세션이 유지되며, 개발 토큰 모드는 새로고침 후 재연결합니다.

## 입력 파일

[다운로드 가능한 예제](../frontend/public/examples/inventory.sample.json)는 **형식 확인용 가상 입력**입니다. 서버에서 수집한 자료나 실제 취약점 검증 결과가 아닙니다.

| 필드                                       | 의미·제약                                                                                |
| ------------------------------------------ | ---------------------------------------------------------------------------------------- |
| `schema_version`                           | `1.0`, 생략하면 기본값 적용                                                              |
| `collected_at`                             | 정보를 확인한 시각. `2026-11-09T09:00:00+09:00`처럼 시간대가 있는 문자열 필수            |
| `os.id`                                    | 현재 파일 입력은 `ubuntu`만 허용                                                         |
| `os.version_id`                            | `22.04`처럼 `숫자 2자리.숫자 2자리` 형식. 입력 허용이 취약점 분석 지원을 의미하지는 않음 |
| `os.codename`, `os.architecture`           | 선택. 모르면 `null` 또는 생략                                                            |
| `packages`                                 | 설치된 패키지 1~5,000개                                                                  |
| `packages[].binary_name`                   | 패키지 이름 필수. 같은 이름·아키텍처 조합은 중복 불가                                    |
| `packages[].binary_version`                | 전체 설치 버전 문자열. 모르면 `null` 또는 생략                                           |
| `packages[].source_name`, `source_version` | 소스 패키지 정보. 소스 버전만 입력하는 것은 허용하지 않음                                |
| `packages[].architecture`                  | 해당 패키지의 아키텍처. OS의 아키텍처를 자동 대입하지 않음                               |
| `packages[].origin`                        | 설치 출처에 대한 사용자 설명, 최대 500자. 모르면 `null` 또는 생략                        |
| `package_list_complete`                    | 사용자가 전체 설치 목록임을 표시하는 불리언. 기본 `false`                                |
| `is_synthetic`                             | 가상 입력 여부. 배포 예제는 `true`, 실제 자료 입력은 `false`                             |

파일은 UTF-8 JSON이며 최대 **2 MiB**입니다. BOM이 있는 UTF-8도 허용합니다. 잘못된 JSON 문법, 중복 JSON 필드, 알 수 없는 필드, 형식 오류, 비정상 숫자, 제한을 넘는 입력은 거부합니다. 버전 문자열은 이 단계에서 기본 문자 형식만 확인하며 실제 Debian 버전 비교는 수행하지 않습니다.

`asset_id`, `inventory_id`, `package_id`, `ingested_at`, `origin_status`는 파일에서 지정할 수 없습니다. 대상 자산은 URL에서 선택하며 ID와 저장 시각은 서버가 생성합니다.

## 저장 의미

- 업로드마다 `InventorySnapshot`을 `inventory_snapshots` 테이블에 저장합니다. 수정·삭제 API는 제공하지 않습니다.
- `collection_method=JSON`입니다. 설치 출처 설명이 있으면 `USER_DECLARED`, 없으면 `UNKNOWN`입니다. 공식 출처 검증 상태로 승격하지 않습니다.
- 원래 버전 문자열, `null`, 소스 정보, 패키지 순서를 보존합니다. 출처 설명은 앞뒤 공백만 제거합니다.
- `collected_at`과 `ingested_at`은 UTC로 저장하고 화면에서는 연도를 포함한 한국 시간으로 표시합니다.
- 전체 목록이라고 입력하면 `COMPLETE`, 아니면 `PARTIAL`입니다. 이는 **파일의 목록 범위 주장**이며 모든 필드가 확인됐거나 서버가 안전하다는 뜻이 아닙니다.
- 생략된 버전·소스·아키텍처·출처는 `coverage.missing_fields`에 남깁니다. 입력 누락을 추측하여 채우지 않습니다.
- 자산의 예상 Ubuntu와 파일의 버전이 다르면 화면에서 확인 안내를 표시합니다. 기존 등록 정보를 자동 변경하지 않습니다.
- 비활성 자산은 이전 기록 조회만 가능하며 신규 입력은 409로 거부합니다.

## API

모든 경로에는 개발용 Bearer 토큰이 필요합니다. 기준 경로는 `/api/v1`입니다.

| 메서드 | 경로                                            | 동작                                                                                               |
| ------ | ----------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| POST   | `/assets/{asset_id}/inventories`                | 파일의 JSON 본문을 `application/json`으로 전송. 검증·저장 후 201과 `InventorySnapshot` 반환        |
| GET    | `/assets/{asset_id}/inventories`                | `items`, `total`을 포함한 기록 요약. 저장 시각 내림차순, 기본 20개, `limit` 1~100, `offset` 0 이상 |
| GET    | `/assets/{asset_id}/inventories/{inventory_id}` | 해당 자산에 속하는 기록과 전체 패키지 목록. 다른 자산의 기록 ID이면 404                            |

HTTP 본문 크기는 `Content-Length` 유무와 관계없이 API에서 제한합니다. 413은 크기 초과, 422는 파일 형식 오류입니다. 잘못된 파일이 기존 기록을 변경하지 않습니다. 데이터베이스 반영이 끝난 뒤에만 성공 응답을 반환합니다.

기존 DB에는 `uv run alembic upgrade head`로 `0002` 마이그레이션을 적용합니다. 자산·작업 테이블은 그대로 보존됩니다. 로컬 실행기 역시 시작할 때 마이그레이션을 적용합니다.

## 검증

```bash
uv run pytest tests/integration/test_inventories.py tests/integration/test_migrations.py
npm --prefix frontend test
npm --prefix frontend run build
```

새 앱 세션에서 데이터 재조회, 과거 기록 보존, 자산 구분, 비활성 자산, 미확인 출처·누락 필드, 잘못된 입력의 비저장, UTF-8·중복 필드·본문 크기 제한을 검사합니다. SQLite 검증과 별개로 PostgreSQL 실환경 검증은 해당 환경이 필요합니다.

## CSV 입력

화면에서 `.csv` 파일을 선택하거나 CSV 예제를 내려받을 수 있습니다. UTF-8과 BOM을 지원합니다. 필수 열은 `os_release,collected_at,binary_name`, 선택 열은 `os_architecture,package_list_complete,is_synthetic,binary_version,source_name,source_version,architecture,origin`입니다.

같은 파일의 OS·수집 시각·완전성·가상 여부는 모든 행이 같아야 합니다. 날짜는 시간대를 포함하고 참/거짓은 true·false를 씁니다. package_list_complete 기본값은 false입니다. origin은 사용자 입력/미확인만 허용합니다. 알 수 없는 열, 중복 열·패키지, 열 개수 불일치·잘못된 값은 전체 입력을 거부합니다. 최대 5,000행이며 HTTP 요청 전체 크기는 JSON 입력과 같이 2 MiB 이내입니다. CSV 문자열의 JSON 포장 때문에 실제 파일 허용량은 조금 작아질 수 있습니다.

CSV도 입력 출처를 검증된 공식 패키지로 취급하지 않습니다. `POST /assets/{asset_id}/inventories/csv`에 `{"csv_text":"..."}`로 보내며 결과는 기존 InventorySnapshot과 같습니다.
