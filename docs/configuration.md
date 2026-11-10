# 설정 안내

모든 초기화·실행 명령은 저장소 루트를 기준으로 합니다. 기본 설정 예시는 `.env.example`이며 다음 명령으로 로컬 설정을 생성합니다.

필요 환경은 Python 3.12, uv, Node.js 24와 npm입니다. 프로젝트의 Python 버전 범위는 `pyproject.toml`에서 `>=3.12,<3.13`으로 고정되어 있습니다.

```bash
python3 scripts/init_env.py
```

초기화 스크립트는 `.data/`를 준비하고 개발 토큰과 DB 비밀번호가 포함된 `.env`를 생성합니다. 기존 유효값과 주석은 보존하고, 누락된 기본 필드와 빈 비밀값만 보충합니다. 잘못된 토큰 길이·실행 모드·필수값·포트·조회 간격은 필드명으로 진단하고 실패 코드로 종료하며 파일을 수정하지 않습니다. 비밀값을 출력하지 않습니다. Windows에서 `python3` 명령이 없으면 `py scripts/init_env.py`를 사용합니다.

## 개발 실행기

`make dev` 또는 `python3 scripts/dev.py`는 설정 초기화, uv 잠금 파일 설치, 유효 설정 검사, npm 설치, Alembic 적용과 프로세스 실행을 묶습니다. npm 설치는 설치 기록이 없거나 잠금 파일이 바뀌면 수행합니다. 런타임이 없거나 포트가 사용 중이면 원인을 표시하고 종료합니다.

| 옵션·명령                     | 동작                                |
| ----------------------------- | ----------------------------------- |
| `make dev`                    | API·단일 Worker·Vite 실행           |
| `make dev-ui` / `--no-worker` | API·Vite 실행; Worker 작업은 대기   |
| `--prepare-only`              | 설치·설정 검사·마이그레이션 후 종료 |
| `--api-port`, `--web-port`    | 기본 8000·5173 대신 지정 포트 사용  |

Ctrl+C 또는 종료 신호를 받으면 실행기가 시작한 프로세스와 하위 프로세스를 정리합니다. 같은 저장소의 실행기는 OS 파일 잠금으로 중복 실행을 막습니다. 별도로 시작한 API·Worker는 실행기가 관리하지 않으므로 함께 실행하지 않습니다. 개발 DB는 재실행해도 보존합니다.

`uv`가 PATH에 없고 로컬 `.tools/bin/uv`가 있으면 실행기가 해당 도구를 사용합니다. 실행 중 실제 서버 설정은 `scripts/check_env.py`가 검사하며 실행 환경 변수의 잘못된 값도 필드명으로 진단합니다.

## 환경 변수

| 변수                       | 기본값·초기값              | 적용 범위                                              |
| -------------------------- | -------------------------- | ------------------------------------------------------ |
| `APP_ENV`                  | `development`              | API·Worker; 현재 로컬·시연 실행 모드                   |
| `DEV_API_TOKEN`            | 초기화 시 생성             | 보호 API 인증; 최소 32자                               |
| `DATABASE_URL`             | `sqlite:///./.data/dev.db` | 로컬 API·Worker·Alembic의 저장소                       |
| `POSTGRES_DB`              | `threat_intel`             | Compose 데이터베이스 이름                              |
| `POSTGRES_USER`            | `threat_intel`             | Compose 데이터베이스 계정                              |
| `POSTGRES_PASSWORD`        | 초기화 시 생성             | Compose 데이터베이스 비밀번호                          |
| `WEB_PORT`                 | `8080`                     | Compose 웹의 호스트 포트                               |
| `WORKER_POLL_SECONDS`      | `2`                        | 대기 작업이 없을 때 재조회 간격; 0.1~60초              |
| `SUPPORTED_UBUNTU_RELEASE` | 빈 값                      | 향후 판정 범위 설정용; 현재 동작에 적용되지 않음       |
| `LLM_BASE_URL`             | 빈 값                      | 학교 API 주소; https://code.cu.ac.kr/llm/v1만 허용     |
| `LLM_MODEL`                | 빈 값                      | 학교 API에 요청할 모델 ID                              |
| `LLM_API_KEY`              | 빈 값                      | 학교 API 키. 백엔드 설정에서만 사용                    |
| `LLM_TIMEOUT_SECONDS`      | `45`                       | 총 요청 제한 시간, 5~60초                              |
| `LLM_MAX_TOKENS`           | `2200`                     | 최대 출력 토큰, 512~4096                               |
| `NVD_API_KEY`              | 빈 값                      | 선택 사항. NVD CVE API 인증; Worker에만 전송           |
| `SSH_ALLOWED_TARGETS`      | 빈 값                      | 허용 IP:포트 목록, 쉼표 구분; 없으면 SSH 비활성        |
| `SSH_KEY_DIRECTORY`        | `.data/ssh-keys`           | 백엔드 개인키 디렉터리; Compose에서는 읽기 전용 마운트 |
| `SSH_KEY_PASSWORD`         | 빈 값                      | 암호화된 개인키의 암호, 현재 모든 키에 공통 적용       |
| `SSH_TIMEOUT_SECONDS`      | `45`                       | SSH 연결·인증·조회 전체 제한, 5~60초                   |

[AI 설명 사용 방법과 오류 처리](ai-explanations.md)를 참고하세요. 설정이 없어도 기존 분석과 저장 설명은 조회할 수 있으며, 시작·조회 시 외부 LLM을 호출하지 않습니다.

[SSH 접속 준비·호스트 키 확인·권한 설정](ssh-collection.md)을 참고하세요. SSH 설정이 없어도 JSON 입력·분석·보고서는 사용할 수 있습니다. 초기화 스크립트는 빈 `.data/ssh-keys/` 디렉터리도 준비합니다.

API·Worker 설정은 실행 환경 변수와 `.env`에서 읽으며, 실행 환경 변수 값이 우선합니다. 설정은 프로세스에서 캐시하므로 변경 후 API와 Worker를 다시 시작합니다.

Compose의 API·Worker는 `POSTGRES_*` 값으로 구성한 내부 DB URL을 사용합니다. `.env`의 로컬 `DATABASE_URL` 값을 그대로 사용하지 않습니다. `APP_ENV`도 Compose에서 `development`로 지정합니다.

## 포트와 주소

| 실행 방식      | 웹               | API                  | 데이터베이스         |
| -------------- | ---------------- | -------------------- | -------------------- |
| Compose 기본값 | `127.0.0.1:8080` | 컨테이너 내부 `8000` | 컨테이너 내부 `5432` |
| 로컬 기본값    | `127.0.0.1:5173` | `127.0.0.1:8000`     | `.data/dev.db`       |

Vite의 기본 포트는 `5173`이며 지정 포트가 이미 사용 중이면 종료합니다. 개발 실행기의 포트 옵션을 사용하면 API와 Vite를 함께 변경할 수 있습니다. 수동 Vite 실행의 `DEV_API_PROXY`는 프록시 대상 URL을 지정하며 기본값은 `http://127.0.0.1:8000`입니다. `WEB_PORT`는 Vite 설정을 변경하지 않습니다. 두 실행 방식 모두 웹의 `/api` 요청을 API에 전달합니다.

## 데이터 보관

로컬 기본 DB는 SQLite 파일이며 Compose는 `db-data` 이름의 볼륨을 사용합니다. 두 저장소의 자산과 작업 이력은 서로 독립적입니다.

`docker compose down`은 컨테이너를 종료하고 기본 DB 볼륨은 보존합니다. `.env`의 DB 비밀번호 변경은 이미 초기화된 PostgreSQL 계정의 비밀번호를 자동으로 변경하지 않습니다. 기존 DB 자격 증명을 변경할 때에는 DB 계정과 연결 설정을 함께 갱신해야 합니다.

스키마 변경 이력은 `backend/migrations/`에 있습니다. 로컬에서는 API·Worker 실행 전에 다음 명령으로 적용합니다. Compose는 `migrate` 서비스에서 자동으로 적용합니다.

```bash
uv run alembic upgrade head
```

## 계정 인증과 검증 캐시

`AUTH_MODE=accounts`를 사용하면 발급 계정으로 로그인하고 역할·자산 권한을 적용합니다. 첫 관리자는 마이그레이션 후 `uv run python -m scripts.manage_users admin`으로 생성합니다. `AUTH_MODE=token`은 기존 DEV_API_TOKEN 개발 관리자 연결입니다. accounts 모드에서 개발 토큰은 사용하지 않습니다.

| 변수                    | 기본값              | 의미                                              |
| ----------------------- | ------------------- | ------------------------------------------------- |
| AUTH_MODE               | token               | token 또는 accounts                               |
| SESSION_HOURS           | 8                   | 세션 만료 시간, 1~24시간                          |
| SESSION_COOKIE_SECURE   | false               | HTTPS 제공 시 true                                |
| PACKAGE_CACHE_DIRECTORY | .data/package-cache | 공식 패키지·목록 캐시; 여유 있는 드라이브 권장    |
| PACKAGE_CACHE_MIB       | 768                 | 캐시 용량 상한, 256~4096 MiB                      |
| GPG_BINARY              | 빈 값               | GnuPG 경로; PATH 또는 Windows Git GnuPG 자동 선택 |

Compose 검증 캐시는 package-cache 볼륨에 둡니다. Windows 시험 환경의 Python·다운로드 캐시와 VM 디스크는 D 드라이브에 둘 수 있습니다. SSH APT 참고 조회는 별도 12초 제한을 두고, 이 조회만 실패하면 필수 패키지 기록을 보존하며 부분 상태를 표시합니다. 현재 시험 환경은 SSH_TIMEOUT_SECONDS=60입니다.

[계정·세션·감사·백업·복원](operations.md), [공식 파일 검증](package-verification.md)을 참고하세요. `.env`·키·캐시·DB·VM 이미지는 Git에서 제외합니다. 설정 변경 후 API·Worker를 재시작합니다.

## 오류 진단

예상하지 못한 API 예외는 일반화한 오류 응답과 요청 ID를 반환합니다. 서버 로그에는 같은 요청 ID, 예외 유형과 `파일:줄:함수` 위치를 남깁니다. 예외 메시지·소스 코드 줄·지역 변수는 기록하지 않습니다. Worker 오류는 작업 ID와 같은 형식의 위치를 남깁니다.

목록 자동 조회는 이전 요청이 끝난 뒤 5초 후 다시 실행합니다. 수동 갱신이 요청 중 발생하면 완료 뒤 한 번 더 조회합니다. 화면 전환·연결 해제는 진행 중인 요청을 취소합니다.

## 실행 상태 확인

```bash
# Compose
curl --fail http://127.0.0.1:8080/api/v1/health
curl --fail http://127.0.0.1:8080/api/v1/readiness

# 로컬 API
curl --fail http://127.0.0.1:8000/api/v1/readiness
```

`health`는 프로세스 응답을, `readiness`는 데이터베이스 접근과 초기 테이블을 확인합니다. Worker의 동작은 웹의 **작업 내역 → Worker 연결 확인** 또는 [HTTP 검증 명령](verification.md)으로 확인합니다.

| 현상                                      | 확인 항목                                                        |
| ----------------------------------------- | ---------------------------------------------------------------- |
| 초기화가 실패함                           | 출력된 필드명과 `.env` 형식·값 확인; 비밀값을 출력·공유하지 않음 |
| 개발 실행기가 시작되지 않음               | uv·Node.js 24·npm, 포트 사용 여부, 같은 저장소의 기존 실행기     |
| API가 시작되지 않음                       | 토큰 길이, `APP_ENV`, 현재 작업 디렉터리, DB URL                 |
| API가 401 반환                            | 웹 입력값과 API 프로세스의 개발 토큰 일치 여부                   |
| 준비 상태가 503 반환                      | DB 연결, Alembic 마이그레이션, 초기 테이블                       |
| 작업이 계속 `QUEUED`                      | Worker 실행 여부, API와 Worker의 DB 일치 여부                    |
| PostgreSQL Worker가 중복 실행 오류로 종료 | 기존 Worker 프로세스 실행 여부                                   |
| 자산 목록이 실행 방식마다 다름            | SQLite와 Compose PostgreSQL의 저장소 분리                        |
| 403 또는 CSRF 오류                        | 로그인 상태·자산 권한·같은 서비스 주소와 포트 확인               |
