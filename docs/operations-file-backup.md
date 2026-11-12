# 운영 파일 암호화 백업·복원

윤선빈 담당의 배포 설정·SSH 인증정보·선택한 근거 파일 복구 도구입니다.
`scripts/operations_backup.py`는 지정한 환경 파일, SSH 키 디렉터리, 선택한 근거 디렉터리를
암호화하고 새 디렉터리로만 복원합니다. 기존 앱·DB 스키마·판정·검색·LLM 코드는 변경하지 않습니다.

## 범위와 보관 원칙

- 환경 파일은 `config/app.env`, SSH 파일은 `ssh/`, 선택한 근거는 `evidence/`로 복원합니다.
  빈 디렉터리는 보관하지 않지만 Compose 마운트용 `ssh/`는 비어 있어도 생성합니다.
- DB는 기존 [PostgreSQL 백업 도구](postgres-backup.md)로 검증된 논리 덤프와 그 manifest를
  먼저 만듭니다. 실행 중인 PostgreSQL 데이터 볼륨을 파일 도구로 복사하지 않습니다.
- 한 백업의 평문 tar 크기는 메타데이터·패딩 포함 **64 MiB 이하**, 파일 수는 **2,000개 이하**입니다.
  디렉터리별 입력 탐색도 전체 항목 2,000개로 제한합니다. 경로는 512자·20개 구성 요소까지입니다.
  더 큰 덤프는 이 도구에 넣지 말고 기존 DB 도구와 별도의 승인된 대용량 암호화 보관 절차를 사용합니다.
- 기존 잠금 의존성의 `cryptography.Fernet`을 사용합니다. 인증된 암호문 안에 경로·크기·SHA-256
  manifest도 넣습니다. 평문 tar 임시 파일은 만들지 않으며 메모리 사용량은 여러 복사본 때문에
  64 MiB를 초과할 수 있습니다. [Fernet 문서](https://cryptography.io/en/latest/fernet/)의
  전체 메시지 메모리 처리 제약에 맞춰 입력을 제한합니다.
- 복구키를 잃으면 복호화할 수 없습니다. 키 소유자는 복호화와 유효한 백업 생성 모두 가능하므로
  키를 백업과 다른 접근 통제 저장소에 보관합니다. 암호문 크기·Fernet 생성 시각은 숨겨지지 않습니다.
  암호화는 오래된 정상 백업으로의 교체까지 탐지하지 않으므로 보관 목록에서 원하는 시점을 확인합니다.
- 출력·복구키는 입력 SSH/근거 디렉터리 밖에 둡니다. 키 파일 자체나 그 하드 링크가 입력에
  포함되면 거부합니다. 별도 복사한 키 내용까지 자동 탐지하는 기능은 없습니다.
- 소유자가 관리하는 신뢰할 수 있는 부모 디렉터리에서 실행합니다. 입력 파일/디렉터리의
  심볼릭 링크와 특수 파일은 거부하지만 악의적인 다른 프로세스의 부모 경로 교체를 지원하지 않습니다.
  파일 읽기 전후 변경은 검사하며, 여러 파일의 동일 시점 스냅샷은 보장하지 않습니다.
  백업 중 설정·키 교체를 멈추고 DB 백업 시점과 변경 이력을 함께 기록합니다.

## 백업

저장소 루트에서 실행합니다. 경로는 실제 승인된 저장 위치로 바꾸되 키·환경 파일 내용을
터미널이나 Git에 출력하지 않습니다. 아래 `/secure/...`는 예시이며 자동으로 외부 저장소를 만들지 않습니다.

```bash
umask 077
# 최초 한 번: 이미 존재하는 키를 덮어쓰지 않습니다.
uv run python -m scripts.operations_backup keygen /secure/recovery-keys/cti.key

# selected-evidence에는 이번 회차의 검증된 .dump와 .dump.json 및 필요한 근거만 배치합니다.
uv run python -m scripts.operations_backup create /secure/backups/cti-20261112.ctiops \
  --key-file /secure/recovery-keys/cti.key \
  --env-file .env --ssh-directory .data/ssh-keys \
  --evidence-directory /secure/selected-evidence

uv run python -m scripts.operations_backup verify /secure/backups/cti-20261112.ctiops \
  --key-file /secure/recovery-keys/cti.key
```

`--evidence-directory`는 생략할 수 있습니다. SSH 입력 디렉터리는 반드시 있어야 하며 비어 있어도 됩니다.
기존 출력은 덮어쓰지 않으므로 회차마다 새 파일명을 사용합니다. 정상 종료 시 파일 수만 출력하며
키·환경 값·파일 내용은 출력하지 않습니다. 실패 종료 코드는 1입니다. 생성 도중 일반적인 I/O 오류가
발생하면 신규 출력만 삭제합니다. 강제 종료나 정전 후 남은 출력은 성공으로 취급하지 말고 `verify`로
검사합니다. SHA-256만 확인하는 것이 아니라 복구키로 암호문 인증과 내부 manifest를 모두 검증합니다.

이 도구는 로컬 파일 생성까지만 수행합니다. 보관 위치로 복사한 **실제 백업 사본**을 다시 verify하고,
키를 분리 보관한 뒤 정기 복원 훈련을 수행해야 합니다. 외부 복제·스케줄·보관 기간·자동 삭제는
별도 운영 결정이며 이번 구현이 자동 설정하지 않습니다.

## 복원과 서비스 전환

```bash
uv run python -m scripts.operations_backup restore /secure/backups/cti-20261112.ctiops \
  --key-file /secure/recovery-keys/cti.key \
  --destination /secure/restore-20261112
```

1. 복원 부모 디렉터리는 미리 준비합니다. 대상 자체는 없어야 합니다. 빈 디렉터리나 링크도
   기존 대상으로 취급해 거부합니다. 전체 암호문·manifest·경로를 검증한 후에만 대상을 생성합니다.
2. 새 파일은 `0600`, 새 디렉터리는 `0700`입니다. 기존 부모의 권한은 변경하지 않습니다.
   macOS/Linux POSIX 권한 기준이며 Windows ACL 검증은 수행하지 않았습니다.
3. 복원본의 `config/app.env`에서 `SSH_KEY_DIRECTORY`를 복원한 `ssh/`의 절대 경로로 조정합니다.
   DB 이름·주소·허가된 SSH 대상·LLM 주소도 복구 환경에 맞춰 검토합니다. 도구는 값을 자동으로
   바꾸거나 서비스를 시작하지 않습니다. 컨테이너 실행 계정이 키를 읽을 수 있는 소유권/UID를
   확인하되 키를 world-readable로 완화하지 않습니다.
4. 검증한 `.dump`와 `.dump.json`을 기존 PostgreSQL 도구에 전달해 **새 DB**로 복원합니다.
   기존 DB 덮어쓰기는 지원하지 않습니다. [계정 복원 인수](accounts-recovery-verification.md)의
   세션 취소·백업 이후 권한 회수 재적용 절차를 수행한 뒤 새 DB로 전환합니다.
5. 저장된 SSH 호스트 지문을 유지해 수집을 검증합니다. 실패를 피하려고 자동 신뢰로 변경하지 않습니다.
   API readiness, 로그인·접근 통제·보고서 다운로드, Worker 작업 완료까지 확인합니다.
6. 검증 실패 시 원본 환경을 유지합니다. 복원 도중 오류가 나면 이번에 생성한 복원 디렉터리만
   제거합니다. 운영 원본·기존 백업을 삭제하지 않습니다. 검증이 끝난 평문 복원본은 별도 보관 정책에
   따라 관리하고, 복구키와 함께 Git에 추가하지 않습니다.

## 재현 가능한 시험

```bash
uv run pytest tests/unit/test_operations_backup.py

TEST_POSTGRES_COMPOSE_PROJECT=blended-threat-intel \
TEST_POSTGRES_COMPOSE_ENV_FILE=.env \
uv run pytest tests/integration/test_account_restore_compose.py

TEST_MYSQL_SSH_PROFILE=/secure/restore-20261112/evidence/profile.json \
TEST_MYSQL_KEY_DIRECTORY=/secure/restore-20261112/ssh \
uv run pytest tests/integration/test_mysql_lab.py
```

Compose 시험은 전용 시험 프로젝트만 대상으로 합니다. 실제 덤프·manifest·Compose 환경 파일과
생성한 SSH 키를 암호화/복원하고, 복원된 환경 파일로 새 API를 실행해 계정·보고서를 확인합니다.
생성한 SSH 키는 서명 검증까지 검사하며 이 시험 자체가 원격 SSH 접속을 수행하지는 않습니다.
마지막 명령은 별도로 준비한 허가된 Ubuntu/MySQL VM에 복원한 실제 키로 고정 읽기 명령만 실행합니다.
SSH 접속 정보가 없으면 VM 시험은 skip입니다. CI는 VM 없이 단위·Compose 복구를 실행합니다.

## 실검증 — 2026-11-12 KST

- 새 보안·복구 단위 시험 41개와 기존 PostgreSQL 도구/Compose 복원 시험을 합쳐
  **58 passed, 0 skipped**, 30.77초였습니다. 기존 Starlette deprecation 경고 1건입니다.
- PostgreSQL 17.11·pgvector 0.8.7·Alembic `0011`에서 암호화한 파일 4개를 복원했습니다.
  새 DB/API의 테이블 24개, 계정 4개, 보고서 4개, 세션 4개, 감사 기록 66개를 확인했고
  저장 API 응답 13개와 보고서 SHA-256이 일치했습니다.
- 기존 MySQL 시험의 환경 파일·실제 SSH 키/공개키·프로필·DB 덤프/manifest 6개를 별도로
  암호화·복원했습니다. Ubuntu 24.04 arm64 VM에 복원된 키와 저장된 호스트 지문으로 접속한
  인수 시험은 **1 passed, 0 skipped**, 2.40초였습니다. 패키지 691개와 실행 중인
  MySQL `8.0.46-0ubuntu0.24.04.5`를 수집하고 호스트 키 불일치 실패 및 SQLite 이력 복구를
  확인했습니다. 이 별도 SSH 시험의 이력 복원은 SQLite이며 PostgreSQL 복원 결과와 구분합니다.
- Ruff 검사·포맷을 통과했습니다. Git 제외 `.data/operations-recovery-20261112/`에
  `targeted-suite.xml`, `restored-ssh.xml`, `validation-summary.json`을 소유자 전용으로 보관합니다.
  이번 확인은 같은 호스트의 복구 훈련이며 외부 저장소 복제·다른 호스트 재해 복구를 검증한 것은 아닙니다.
