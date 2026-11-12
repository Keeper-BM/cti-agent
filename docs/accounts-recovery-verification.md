# 계정·권한·보고서 PostgreSQL 복원 인수

## 담당 범위

윤선빈 담당의 접근 통제·운영·백업 복원 인수 시험입니다. 기존 계정 API와 별도 Worker를
실제로 실행해 검증하며 계정·판정·검색·LLM·보고서의 애플리케이션 코드는 수정하지 않습니다.
다른 기능 브랜치를 병합하지 않습니다. 변경 대상은 새 시험 파일, 기존 PostgreSQL 복원 CI
단계, 이 운영 검증 안내입니다.

`tests/fixtures/compose_accounts.py`는 실행 중인 시험 Compose의 DB와 앱 이미지를 이용해
무작위 이름의 원본/복원 DB 및 별도 API·Worker 컨테이너를 만듭니다. 기존 Compose의
애플리케이션 DB·계정·설정은 바꾸지 않습니다. 추가 API 포트는 호스트의 임의 루프백 포트만
사용합니다. 초기 관리자 비밀번호는 실행 때 생성해 표준 입력으로 전달하며 명령 인수·로그에
출력하지 않습니다. 정상 종료와 시험 예외 시 이번 시험이 만든 컨테이너·DB를 정리합니다.
프로세스 강제 종료 시에는 무작위 `cti-account-check-*` 컨테이너와 `cti_accounts_*` /
`cti_restored_*` DB가 남을 수 있으므로 생성 경위를 확인해 정리합니다.

## 검증 흐름

1. 새 DB에 현재 Alembic 스키마를 적용하고 관리자 1명을 준비합니다. 나머지 담당자·조회자·
   비활성화용 계정은 관리자 HTTP API로 만듭니다. DB의 비밀번호 해시 검증과 응답의 비밀번호
   필드 미노출을 확인합니다.
2. 가상 입력임을 표시한 자산 2개에 JSON 인벤토리를 등록합니다. 기존 분석·보고서 API와
   별도 Worker로 실제 저장된 분석·Markdown 보고서를 만듭니다. 외부 공식 자료·LLM 호출은
   하지 않으며 취약점 정확도나 AI 설명 품질 시험으로 확대하지 않습니다.
3. 담당자·조회자는 부여된 자산만 목록/상세로 조회합니다. 다른 자산의 인벤토리·분석·보고서·
   Markdown 다운로드·작업은 404, 관리자 API·감사 로그는 403이어야 합니다.
   조회자의 쓰기와 담당자의 관리자 작업도 거부해야 합니다.
4. 개발 토큰의 계정 인증 우회, CSRF 누락, 다른 Origin의 쓰기를 차단합니다.
   HttpOnly·SameSite 쿠키, 로그아웃, 만료 세션, 비활성 계정의 세션 거부,
   로그인 실패 제한을 검사합니다.
5. Worker를 정지한 상태에서 담당자의 보고서 작업을 접수한 뒤 자산 권한을 회수합니다.
   Worker 재시작 후 `JOB_ACCESS_REVOKED`로 실패하고 해당 사용자는 작업도 조회할 수 없어야 합니다.
6. 진행 작업이 없는 상태에서 Worker를 멈추고 `scripts.postgres_backup`으로 백업·시험 복원·
   새 DB 복원을 수행합니다. 사용자 4개, 보고서 4개(성공 3개·권한 회수 실패 1개),
   세션·로그인 제한·감사 기록을 포함한 전체 테이블이 검증 대상입니다.
7. 복원 DB에 새 API 프로세스를 연결해 기존 유효 세션, 계정/감사 목록, 자산·인벤토리·분석·
   보고서·작업 응답과 Markdown SHA-256을 대조합니다. 로그아웃/만료/비활성 세션은 거부되고
   로그인 시도 제한도 유지돼야 합니다. 복원된 비밀번호로 새 로그인·로그아웃을 확인합니다.
8. 복원 DB에서 권한을 회수하면 즉시 접근이 차단되고 원본 DB의 권한은 그대로여야 합니다.

## 재실행

저장소 루트에서 전용 시험 Compose를 먼저 기동합니다. 이 시험은 DB 생성 권한과 해당
프로젝트의 `db`, `api`, `worker` 서비스 이미지를 사용합니다. 운영 프로젝트에는 실행하지 않습니다.

```bash
TEST_POSTGRES_COMPOSE_PROJECT=blended-threat-intel \
TEST_POSTGRES_COMPOSE_ENV_FILE=.env \
uv run pytest tests/integration/test_postgres_backup.py \
  tests/integration/test_account_restore_compose.py -v --junitxml=.data/account-restore.xml
```

`TEST_POSTGRES_COMPOSE_PROJECT`를 지정하지 않으면 skip입니다. CI의 Compose 작업에서는
기존 파일 무결성·복원 거부 시험과 새 계정 복원 시험을 함께 실행합니다. 원격 VM·GPU·학교
LLM 없이 재현할 수 있습니다. JUnit 결과에는 테이블/계정/보고서/세션/감사 기록 수와
저장 응답 수·덤프 SHA-256만 추가하며 비밀번호·쿠키·토큰은 기록하지 않습니다.

## 운영 복구 시 주의할 상태

복원은 백업 시점으로 돌아갑니다. 백업 **이후** 회수한 권한이나 취소한 세션까지 보존하는 것은
아닙니다. 이 시험은 백업 전에 회수·취소한 상태의 보존과 백업 당시 유효 세션의 복원을 확인합니다.
운영 전환 시에는 접근을 열기 전에 복원 DB의 세션을 모두 취소해 재로그인을 요구하고,
백업 이후 계정 비활성화·권한 회수 내용을 다시 적용해야 합니다. 관리자 접근을 먼저 확인한 뒤
사용자 접근을 허용합니다. 현재 백업 도구는 이 정책을 자동 실행하지 않습니다.

이번 시험은 루프백 HTTP API·별도 Worker·PostgreSQL 경로입니다. HTTPS/Secure 쿠키,
Nginx 경유 브라우저 조작, 다른 호스트의 재해 복구, GPU/LLM 연결, 외부 파일 복구는 별도 인수입니다.
DB와 환경 파일·SSH 키의 보관 범위는 [PostgreSQL 백업 안내](postgres-backup.md)를 참조합니다.

## 실검증 — 2026-11-12 KST

- Docker Compose의 PostgreSQL 17.11·pgvector 0.8.7·Alembic `0011`에서 실행했습니다.
- 기존 계정 API, 기존 PostgreSQL 복원, 새 계정 복원, 백업 단위 시험을 함께 실행해
  **22 passed, 0 skipped**, 31.84초를 기록했습니다. 기존 Starlette deprecation 경고 1건입니다.
- 백업 대상: 테이블 24개, 사용자 4개, 보고서 4개, 세션 4개, 감사 기록 66개.
  복원 API의 저장 응답 13개와 보고서 다운로드 SHA-256이 일치했습니다.
- Ruff 검사·포맷과 diff 공백 검사를 통과했습니다. 임시 DB와 임시 계정 API/Worker
  컨테이너가 남지 않은 것을 별도 조회로 확인했습니다.
- Git 제외 `.data/accounts-recovery-20261112/`에 `targeted-suite.xml`,
  `validation-summary.json`, `cleanup-verification.json`을 소유자 전용 권한으로 저장합니다.
  시험 덤프는 pytest 임시 디렉터리에 생성되며 운영 백업으로 사용하지 않습니다.
