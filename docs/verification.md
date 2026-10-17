# 검증 기록

## 개발 실행·시험 예제 검증

확인일: 2026-10-11 (KST). macOS에서 새 실행기와 시험 예제를 검증했습니다. 시험용 소스 복사본에는 실제 접속 정보와 기존 DB를 포함하지 않았습니다.

| 항목             | 결과                                                              |
| ---------------- | ----------------------------------------------------------------- |
| 전체 품질 검사   | `make check` 통과; Ruff·포맷·pytest·프론트 테스트·타입·빌드       |
| Python 테스트    | 57 passed, 1 skipped; 상위 의존성 경고 1건                        |
| 프론트 동작 회귀 | 4 passed; 6초 응답 완료, 중복 갱신, 취소, 오류 복구               |
| 환경 초기화      | 빈 예제 파일 보충, 유효값 보존, 잘못된 설정의 실패 종료·값 비노출 |
| 오류 진단        | 500 일반 응답, 요청 ID·예외 유형·파일 위치 로그, 비밀값 비노출    |
| 예제 계약        | 패키지·버전·규칙·자료·인용 연결과 잘못된 참조 거부                |
| 독립 소스 복사본 | 설치·초기화·SQLite 마이그레이션·API·웹·Worker 처리 성공           |
| 개발 실행기      | 사용자 지정 포트의 프록시 연결, 같은 저장소의 중복 실행 차단      |
| 실행기 종료      | Ctrl+C 종료 후 API·웹 포트 해제 확인                              |
| Worker 생략      | 예제·자산 조회 성공, DB 유지, 새 Worker 작업은 대기               |
| HTTP 검증        | 웹 프록시에서 예제 조회와 연결 확인 작업 완료                     |
| 브라우저         | 예제 인증·수동 갱신·패키지별 기대 판정·인용·입력 JSON 펼침 확인   |
| 브라우저 콘솔    | 해당 시험 예제 검증 중 오류·경고 없음                             |
| 의존성           | 잠금 파일 확인 통과; 새로운 런타임·테스트 의존성 추가 없음        |

독립 복사본은 동일한 macOS의 런타임과 의존성 캐시를 사용했습니다. 시험 DB·복사본·프로세스는 제거했고 기존 로컬 DB는 변경하지 않았습니다. 이 결과는 다른 PC·운영체제, 실제 Debian 버전 비교나 공식 CVE 정확성의 검증을 대신하지 않습니다. Docker·PostgreSQL·원격 CI의 미검증 범위는 아래에 명시합니다.

## 이전 애플리케이션 검증

확인일: 2026-10-10 (KST). 아래 기록은 로컬 개발 환경에서 수행한 검사 결과입니다. 미구현 기능의 분석 정확도나 운영 환경의 안정성을 검증한 결과는 포함하지 않습니다.

| 항목                     | 환경·결과                                                      |
| ------------------------ | -------------------------------------------------------------- |
| Python 의존성            | Python 3.12.15, 잠금 파일 기반 설치 성공                       |
| 프론트엔드 의존성        | Node.js 24.16.0, npm 설치 성공                                 |
| Python 정적 검사·포맷    | Ruff 통과                                                      |
| Python 테스트            | 35 passed, 1 skipped                                           |
| 기능 API 경계            | 미인증 401, 미구현 501, 잘못된 질문 422, 미구현 작업 생성 없음 |
| SQLite 마이그레이션      | 적용·복원·재적용과 모델 일치 확인                              |
| TypeScript·프로덕션 빌드 | `npm run build` 통과                                           |
| 프론트엔드 포맷          | `npm run format:check` 통과                                    |
| API 생성 파일            | OpenAPI와 TypeScript 생성 결과 일치                            |
| HTTP 연동                | Vite → FastAPI → SQLite → 별도 Worker → 상태 조회 성공         |
| 브라우저 기능            | 토큰 인증, 자산 등록·비활성화, 연결 확인 작업 접수·완료        |
| 브라우저 탐색            | 5개 페이지 이동, 뒤로 가기, 새로고침 시 경로 유지·토큰 재입력  |
| 브라우저 콘솔            | 해당 검증 중 오류·경고 없음                                    |

Starlette TestClient의 httpx 사용에 대한 상위 의존성 deprecation 경고 1건이 기록되었습니다. 테스트 실패는 발생하지 않았습니다.

## 이전 구성 및 문서 검사

확인일: 2026-10-10 (KST). 문서와 모듈 설명 정리에 대해 다음 검사를 수행했습니다.

| 항목             | 결과                                         |
| ---------------- | -------------------------------------------- |
| Markdown         | 13개 파일의 코드 블록과 내부 링크 39개 확인  |
| 문서 형식        | Prettier 검사 통과                           |
| 구성 파일        | Compose·CI·이슈 템플릿 YAML 파싱 통과        |
| API 문서         | 문서의 메서드·경로와 생성 OpenAPI 일치       |
| 생성 파일        | 코드에서 OpenAPI·TypeScript 타입 재생성      |
| 의존성           | `uv lock --check --offline` 통과             |
| 소스 정적 검사   | Ruff 검사·포맷 확인 통과                     |
| 설명 변경 범위   | 모듈 설명 수정 전후 실행 코드 동일성 확인    |
| 저장소 포함 범위 | 로컬 보관 자료와 실행 산출물의 Git 제외 확인 |

이 검사에서는 문서·주석·설명 메타데이터를 변경했습니다. 위 애플리케이션 검증 결과는 이전 실행 기록이며, 전체 기능 테스트를 다시 수행한 결과로 표시하지 않습니다.

## 미검증 범위

- Docker CLI·런타임이 없는 로컬 환경에서 검사했으므로 Compose 이미지 빌드·전체 기동은 미검증입니다.
- PostgreSQL·pgvector 전용 테스트 1건은 로컬에서 건너뛰었습니다. 별도의 시험용 DB로 실행해야 합니다.
- GitHub Actions 설정은 존재하지만 원격 실행 결과는 기록되지 않았습니다.
- 실제 Ubuntu 수집, 공식 CVE 판정, GPU 모델, RAG, 계정 인증과 보고서는 구현·인수 시험 대상입니다.

## 자동화 검사 재현

```bash
uv run ruff check backend scripts tests
uv run ruff format --check backend scripts tests
uv run pytest
npm --prefix frontend run format:check
npm --prefix frontend test
npm --prefix frontend run build
```

PostgreSQL 전용 검사는 `TEST_POSTGRES_URL`에 별도의 시험용 PostgreSQL·pgvector DB를 지정하여 실행합니다. 이 테스트는 마이그레이션과 작업 처리를 수행하므로 애플리케이션 데이터가 있는 DB와 분리합니다.

```bash
uv run pytest tests/integration/test_postgres.py
```

## HTTP 연동 검사

API·Worker·웹이 실행된 상태에서 다음 중 해당 실행 방식의 명령을 사용합니다. 연결 확인 작업 한 건이 생성됩니다.

```bash
# Compose 기본 웹 포트
uv run python scripts/smoke_http.py

# 로컬 API·Worker·Vite
SMOKE_BASE_URL=http://127.0.0.1:5173 uv run python scripts/smoke_http.py
```

브라우저 시험에는 문서용 주소를 사용했으며 해당 주소로 서버 연결을 수행하지 않았습니다. 로컬 시험 DB와 화면 캡처는 `.data/`에 저장되며 Git 업로드 대상이 아닙니다.

## CI 구성

| 작업            | 검사 범위                                                         |
| --------------- | ----------------------------------------------------------------- |
| `backend`       | 의존성 설치, Ruff, pytest, PostgreSQL·pgvector, OpenAPI 변경 확인 |
| `frontend`      | npm 설치, 포맷, 폴링 회귀 검사, 생성 타입·TypeScript·Vite 빌드    |
| `compose-smoke` | 환경 생성, Compose 설정·빌드·기동, 예제 조회·HTTP 작업 완료 확인  |

통합 기능의 수용 조건은 [인수 시험 명세](../tests/acceptance/README.md)에 정의합니다.
