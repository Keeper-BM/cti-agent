# PostgreSQL·운영 파일 백업 정기 실행 준비

윤선빈 담당의 독립 운영 도구입니다. `scripts.backup_job`은 기존 PostgreSQL 백업과
운영 파일 암호화를 순서대로 호출합니다. 앱 API·DB 모델·판정·검색·LLM·보고서 코드는 수정하지 않습니다.
실제 외부 보관 위치나 운영 주기를 추정해서 설치하지 않으며, Ubuntu 예약 설정은 검토용 예제로 제공합니다.

## 한 번의 실행이 완료되는 조건

1. 설정 파일·환경 파일·복구키, 작업/보관 디렉터리의 소유자 전용 POSIX 권한을 확인합니다.
   모든 설정 경로는 절대 경로입니다. 보관 디렉터리는 미리 존재해야 하며
   `.cti-backup-destination`의 내용이 설정의 `destination_id`와 정확히 일치해야 합니다.
2. 작업 디렉터리의 `.cti-backup.lock`에 프로세스 파일 잠금을 얻습니다. 다른 실행이 잠금을
   잡고 있으면 즉시 실패합니다. 잠금 파일은 삭제하지 않으며 프로세스 종료 시 OS가 잠금을 해제합니다.
   모든 실행이 같은 작업 디렉터리를 써야 합니다. 여러 호스트 사이의 분산 잠금은 아닙니다.
3. `0700` 임시 작업 디렉터리에 선택한 근거를 복사하고 PostgreSQL 논리 덤프를 만듭니다.
   기존 도구가 임시 DB에 실제 복원해 테이블·시퀀스·확장·마이그레이션 정보를 검사합니다.
   DB 일관성은 덤프를 기준으로 하며 앱 요청을 중단하지 않습니다.
4. 보관 위치 식별자를 다시 확인하고 UTC 시각·무작위 ID로 새 실행 디렉터리를 만듭니다.
   덤프·manifest·환경 파일·SSH 파일·선택 근거를 `backup.ctiops`에 암호화합니다.
   **보관 디렉터리에 실제로 기록한 파일**을 복호화 인증·manifest 대조로 다시 검증합니다.
5. 평문 임시 작업 디렉터리를 삭제한 뒤 `completed.json`을 마지막으로 기록합니다.
   기록에는 실행 ID·시각·암호문 크기/해시·파일 수·스키마 revision·테이블 수만 넣습니다.
   키·토큰·비밀번호·환경 값·원시 자료는 로그나 완료 기록에 넣지 않습니다.

기존 회차는 덮어쓰거나 삭제하지 않습니다. 일반 오류·SIGTERM·Ctrl+C는 신규 출력과 평문 임시
파일을 정리하고 종료 코드 1을 반환합니다. 복구키를 새로 만들거나 원본 서비스를 재시작하지 않습니다.
완료 기록은 관측용이며 별도의 전자서명이 아닙니다. 복구 시 반드시 `operations_backup verify`로
암호문을 인증합니다. 완료 파일이 없거나 JSON이 불완전한 회차를 정상 백업으로 취급하지 않습니다.

## 설정과 수동 실행

`infra/backup/job.example.json`을 보호된 위치에 복사하고 실제 배포 경로로 수정합니다.

- `project_name`: 실행 중인 Compose 프로젝트. 기준 Compose 파일이 있는 저장소 루트에서 실행합니다.
- `env_file`: 해당 프로젝트의 환경 파일. 파일 내용은 변경하지 않습니다.
- `key_file`: 기존 운영 파일 복구키. 키 생성·암호화 범위는 [운영 파일 백업](operations-file-backup.md)을 따릅니다.
- `ssh_directory`: 백업할 키 디렉터리. 비어 있어도 됩니다.
- `work_directory`: 평문 덤프를 잠시 보관할 **로컬** 작업 디렉터리. `0700`으로 준비합니다.
- `destination_directory`: 암호화 결과를 보관할 디렉터리. `0700`으로 준비합니다.
  승인된 별도 디스크/마운트가 있다면 그 안에 생성합니다. 두 디렉터리는 겹치면 안 됩니다.
- `destination_id`: 1~64자의 영문·숫자·밑줄·하이픈 식별자.
- `database`: 선택 항목. 생략하면 컨테이너의 `POSTGRES_DB`를 사용합니다.
- `evidence_directory`: 선택 항목. 덤프 외 근거는 복원 시 `evidence/selected/` 아래에 배치됩니다.
- `timeout_seconds`: Docker/DB 명령별 제한, 기본 300초, 범위 1~3,600초. 전체 실행 제한은 별도입니다.

설정 파일·환경 파일·키·마커는 `0600`으로 제한합니다. 입력 디렉터리에는 출력·작업 디렉터리와
복구키를 포함하지 않습니다. 작업/출력 디렉터리 안에도 환경 파일이나 복구키를 두지 않습니다.
운영 자료의 소유권을 일괄 변경하지 말고 기존 배포 계정과 접근 권한을 먼저 확인합니다.

보관 위치를 확인한 뒤 **최초 한 번**, 마커에 `destination_id`와 줄바꿈을 기록합니다.
예시 설정을 사용할 때 아래 명령은 기존 파일을 덮어쓰지 않습니다.

```bash
uv run python -c "from pathlib import Path; from scripts.operations_backup import write_new; write_new(Path('/srv/cti-backups/.cti-backup-destination'), b'cti-approved-backup-volume\n')"
uv run python -m scripts.backup_job --config /etc/cti-backup/job.json
```

마커는 저장장치 인증 수단이 아닙니다. 올바른 볼륨에만 배치하고 마운트가 해제된 하부 디렉터리에는
복사하지 않습니다. 위치가 없거나 마커가 다르면 자동 생성·다른 위치로 우회하지 않고 실패합니다.
실행 중 마운트/부모 경로를 교체하는 환경은 지원하지 않습니다. 신뢰할 수 있는 관리 경로를 사용합니다.
원격 공유 저장소의 파일 권한·가용성은 환경별로 확인해야 하며 이번 구현이 원격 전송을 수행하지 않습니다.

## Ubuntu systemd 예제

`infra/backup/cti-backup.service`와 `cti-backup.timer`를 실제 경로·계정·주기로 수정합니다.
서비스의 `User`, `Group`, `WorkingDirectory`, `ExecStart`, `ReadWritePaths`, `RequiresMountsFor`를
함께 맞춥니다. 잠긴 의존성으로 만든 `.venv`를 사용하고 예시 경로에 임의 심볼릭 링크를 만들지 않습니다.
기본 예시는 rootful Docker의 로컬 데몬과 `docker` 그룹을 전제로 합니다. Docker 소켓 접근자는
호스트를 제어할 수 있으므로 `NoNewPrivileges` 등의 단위 설정만으로 권한이 격리된다고 보지 않습니다.
복구키·환경 파일·SSH 키를 읽을 수 있는 승인된 배포 계정으로 실행합니다.

서비스는 `Type=oneshot`, 전체 시작 제한 30분, 종료 정리 여유 120초입니다. 예시 타이머는
한국 시간 매일 03시부터 최대 5분 지연 후 실행합니다. `Persistent=true`는 비활성 기간에 놓친
예약이 있으면 활성화 후 한 번 실행하게 하며 모든 누락 회차를 재생하지 않습니다.
의미는 [Ubuntu 24.04 systemd.timer 문서](https://manpages.ubuntu.com/manpages/noble/man5/systemd.timer.5.html)를
기준으로 합니다. 이는 제안 주기이며 사용자 장비의 타이머를 자동 활성화하지 않습니다.

설치 전에 다음 순서로 확인합니다.

1. 설정·키 분리 보관·실제 보관 볼륨·용량을 확인합니다. 같은 서비스 계정으로 수동 백업을 실행합니다.
2. `operations_backup verify`와 새 디렉터리 복원, 새 PostgreSQL DB 복원을 수행합니다.
   [계정 복원 인수](accounts-recovery-verification.md)에 따라 접근 통제와 결과를 확인합니다.
3. 검토된 서비스/타이머를 `/etc/systemd/system/`에 설치하고 `systemd-analyze verify`로 검사합니다.
4. `systemctl daemon-reload` 후 서비스를 한 번 수동 시작해 journal과 완료 기록을 확인합니다.
5. 운영 주기를 확정한 뒤 `systemctl enable --now cti-backup.timer`로 활성화합니다.
   `systemctl list-timers cti-backup.timer`와 다음 실행 후의 완료 시각을 확인합니다.
6. 중지 시 `systemctl disable --now cti-backup.timer`를 사용합니다. 타이머 중지는 이미 실행 중인
   서비스를 중단하지 않습니다. 실행 중 백업을 중단할 때는 해당 서비스도 별도로 stop합니다.

## 장애 대응과 한계

- 최근 `completed.json`의 완료 시각이 합의된 백업 주기를 넘으면 장애로 처리합니다.
  `systemctl status cti-backup.service`와 `journalctl -u cti-backup.service`로 성공/실패를 확인합니다.
  도구는 예외 상세를 숨기므로 별도 점검 시 키·환경 값·원시 DB 응답을 공유 로그에 출력하지 않습니다.
- SIGKILL·정전·정리 권한 상실 시 `cti-backup-*` 평문 작업 디렉터리나 미완료 출력, PostgreSQL의
  `cti_backup_verify_*` DB가 남을 수 있습니다. 실행 프로세스와 생성 경위를 확인한 뒤 관리자가 정리합니다.
  자동으로 다른 실행의 파일·DB나 오래된 정상 백업을 지우지 않습니다.
- 평문 tar 64 MiB·파일 2,000개 제한은 그대로입니다. 큰 DB는 덤프 생성 이후 암호화 한도에서
  실패할 수 있으므로 작업 공간 용량도 확보합니다. 큰 덤프의 스트리밍 암호화는 별도 과제입니다.
- DB와 외부 파일의 같은 시점 스냅샷은 보장하지 않습니다. 실행 중 설정·키·선택 근거를 변경하지 않습니다.
  복원 경로는 `config/app.env`, `ssh/`, `evidence/database.dump`, `evidence/database.dump.json`,
  선택 시 `evidence/selected/`입니다.
- 외부 복제, 보관 기간별 삭제, 실패 알림 전송, 다른 호스트 재해 복구, 운영 타이머 활성화는 별도입니다.
  완료 기록을 만든 것과 외부 보관·재해 복구를 검증한 것을 구분합니다.

## 시험

```bash
uv run pytest tests/unit/test_backup_job.py
TEST_POSTGRES_COMPOSE_PROJECT=blended-threat-intel \
TEST_POSTGRES_COMPOSE_ENV_FILE=.env \
uv run pytest tests/integration/test_backup_job_compose.py
```

Compose 시험은 전용 프로젝트에서 임시 원본/복원 DB를 만들고 CLI를 실제 실행합니다.
한글 데이터·계정이 든 DB를 백업 후 수정하고, 복원 DB의 백업 시점 내용과 전체 manifest를 대조합니다.
다음 회차가 이전 백업을 유지하는지, 잘못된 보관 마커가 성공 기록을 만들지 않는지 검사합니다.
CI의 기존 Compose 복원 단계에도 포함합니다. 운영 DB에서 시험하지 않습니다.

## 실검증 — 2026-11-12 KST

- PostgreSQL 17.11·pgvector 0.8.7에서 새 CLI 인수와 기존 백업·암호화·계정 복원 회귀를 함께
  실행해 **86 passed, 0 skipped**, 48.60초를 기록했습니다. 이후 실제 SIGTERM 종료 검사를
  추가한 최신 백업 실행 단위 시험은 **28 passed**, 1.54초입니다. 중복된 시험 수를 합산하지 않습니다.
- 새 CLI 시험은 스키마 24개 테이블과 시험 테이블 1개, 파일 5개를 보관·복원했고 두 번째
  실행도 이전 백업을 보존했습니다. 잘못된 보관 마커는 새 완료 기록 없이 실패했습니다.
- 기존 계정 복원 인수도 테이블 24개·사용자 4개·보고서 4개·세션 4개·감사 기록 66개,
  저장 응답 13개의 보존을 확인했습니다. 기존 Starlette deprecation 경고 1건입니다.
- Ubuntu 24.04 arm64에서 `systemd-analyze verify`와 `systemd-analyze calendar`를 실행했습니다.
  시험 VM에 Docker와 `/opt/cti-agent/.venv`가 없어 원본 단위의 배포 의존성 검사는 실패했습니다.
  `/tmp` 검사 사본에만 Python 실행 경로를 `/usr/bin/python3`로 바꾸고 Docker 의존성 stub을
  제공한 **구문 검사**는 통과했습니다. 예약 실행의 실제 서비스 인수나 운영 설치 완료를 뜻하지 않습니다.
  다음 실행 시각은 `2026-11-13 03:00:00 KST`로 해석됐습니다. 예약은 활성화하지 않았습니다.
- Git 제외 `.data/backup-job-20261112/`에 JUnit 결과와 `validation-summary.json`을
  소유자 전용으로 보관합니다. 별도 보관 서버·운영 계정·주기 확정 후 배포 인수를 수행해야 합니다.
