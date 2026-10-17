# 시험 예제

시험 예제는 외부 수집·DB·Worker·GPU 없이 입력과 출력 계약을 확인하는 개발 자료입니다. 모든 패키지·CVE·공지는 가상이며 판정과 설명은 고정된 기대 값입니다. 버전 비교, 실제 취약점 분석, 문서 검색과 LLM 생성은 수행하지 않습니다.

## 실행

```bash
make dev-ui
```

웹에서 개발 토큰으로 연결한 뒤 **시험 예제**를 선택합니다. 가상 패키지 두 개가 같은 CVE에 대해 서로 다른 기대 결과를 갖는 사례, 설치·수정 버전과 인용을 확인할 수 있습니다. **예제 데이터**에서 각 계약의 전체 JSON을 펼쳐 볼 수 있습니다.

API 서버 없이 참조 일관성을 검사할 수도 있습니다.

```bash
make example
uv run python -m backend.examples --json
```

이 명령은 저장·외부 연결을 수행하지 않습니다. 모델 검증이 실패하거나 참조가 일치하지 않으면 실패로 종료합니다. 기대 판정의 보안 정확도를 검증하는 명령은 아닙니다.

## 파일과 연결

| 파일                                   | 내용                                      |
| -------------------------------------- | ----------------------------------------- |
| `backend/examples/data/inventory.json` | Ubuntu 형식의 가상 OS와 설치 패키지 두 개 |
| `backend/examples/data/feed.json`      | 가상 공지와 패키지·릴리스·수정 버전 조건  |
| `backend/examples/data/expected.json`  | 기대 판정 두 개와 인용을 포함한 기대 설명 |
| `backend/examples/assessment.py`       | 파일 적재와 계약·참조 검증                |
| `backend/api/routes/examples.py`       | 인증된 읽기 전용 예제 API                 |
| `frontend/src/features/examples/`      | 예제 요청, 결과·근거·JSON 표시            |

자료는 애플리케이션 패키지에 포함됩니다. 테스트와 API가 같은 파일을 읽으므로 별도의 수동 적재가 필요하지 않습니다. 예제 ID는 고정되어 있으며 요청할 때마다 같은 결과를 반환합니다. 실제 자산·작업·판정 테이블에 예제를 저장하지 않습니다.

```text
InventorySnapshot.packages[].package_id
  → Finding.package_ref
FeedSnapshot.advisories[].rules[].rule_id
  → Finding.matched_rule_id
NormalizedAdvisory.evidence_refs
  → Finding.evidence_refs → Answer.citations
```

판정에는 설치 버전과 비교 기준이 포함됩니다. `BINARY`는 바이너리명·버전을, `SOURCE`는 소스명·버전을 참조합니다. 수정 공지의 `FIX_RELEASED`는 공지 상태이며 설치 패키지가 수정됐다는 판정 자체가 아닙니다. 실제 엔진이 전체 Debian 버전·릴리스·출처·조건을 대조해야 합니다.

가상 CVE는 `CVE-2099-0001`, 근거 주소는 `.invalid` 도메인을 사용합니다. 화면은 주소를 시험 메타데이터로 표시하며 해당 주소로 자료를 요청하지 않습니다. 예제의 Ubuntu 릴리스는 실제 지원 범위를 확정하지 않습니다.

## 작은 변경 예시

표시만 변경하려면 `ExamplePage.tsx`의 표·근거 영역을 수정하고 `make dev-ui`로 확인합니다. 다음 명령으로 조회 동작, 타입과 빌드를 검사합니다.

```bash
npm --prefix frontend test
npm --prefix frontend run build
```

입력·자료·기대 결과를 변경하려면 연결된 패키지 ID, 규칙 ID, 자료 기준본과 근거를 함께 유지합니다. 다음 검사로 끊어진 참조와 잘못된 상태 조합을 확인합니다.

```bash
make example
uv run pytest tests/unit/test_example_contracts.py tests/integration/test_examples.py
```

계약 자체를 변경한 경우 OpenAPI와 생성 타입을 갱신합니다.

```bash
make api-types
```

## 실제 기능과의 경계

`GET /api/v1/examples/assessment`는 개발 토큰을 요구하며 `is_synthetic=true`를 반환합니다. `capabilities.features.development_examples`는 `true`, 실제 `assessment`는 `false`입니다. `/analyses`, `/findings`, `/questions`, `/reports`는 실제 구현 전까지 기존 미구현 응답을 유지합니다.

실제 수집·판정의 구현체는 공통 도메인 계약을 사용할 수 있습니다. 예제 적재 코드를 운영 판정 엔진으로 연결하거나 고정 결과를 실제 분석 결과로 저장하지 않습니다. 실제 기준 사례에는 공식 출처와 환경을 별도로 기록합니다.
