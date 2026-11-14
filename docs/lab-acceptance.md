# MySQL 시험 환경 수집·복원과 PostgreSQL 인수 시험

## 검증 결과 — 2026-11-11 KST

macOS에서 새로 만든 Multipass VM과 일회용 Docker 컨테이너로 실행했습니다.
기존 Windows VM의 검증 기록을 재사용한 결과가 아닙니다.

- Ubuntu 24.04.5 LTS arm64, VM 2 CPU·4 GiB RAM·16 GiB 디스크.
- MySQL `8.0.46-0ubuntu0.24.04.4`, Ubuntu noble-updates/noble-security APT 캐시 확인.
- `mysql-server`, `mysql-server-8.0`, `mysql-server-core-8.0`,
  `mysql-client-8.0`, `mysql-client-core-8.0` 5개를 포함한 실제 패키지 691개 수집.
- PostgreSQL 17.11 arm64, pgvector 0.8.7, Alembic `0011`.
- MySQL 단독 인수 시험 1개와 PostgreSQL 단독 통합 시험 1개 통과.
- VM 복원 후 두 실환경을 모두 지정한 전체 Python 시험 **287 passed, 0 skipped**,
  34.93초. Starlette TestClient의 기존 httpx deprecation 경고 1건.

Ubuntu 이미지 식별 해시는
`50e24e1fb79e89116e939d90aa7738f7af48c442fa1bc2510131e0b39c50348e`입니다.
PostgreSQL은 Compose·CI와 같은 `pgvector/pgvector:0.8.7-pg17-bookworm`을 사용했고,
pull 결과 digest는
`sha256:7d0a41464797aeb9862dfdc0bbf1526b82cfd324cdd8036df19e3545f4a9ccb8`입니다.

## 실제로 확인한 경로

`tests/integration/test_mysql_lab.py`는 FastAPI TestClient → 실제 Worker 함수 →
실제 OpenSSH VM → SQLite 저장 경로를 실행합니다. 원격 응답을 fixture로 대체하지 않습니다.

정상 수집의 패키지 목록 완전성, MySQL 설치 상태·버전·소스 패키지·아키텍처,
호스트 키 지문, 고정 명령의 성공과 저장된 출력 해시를 검사합니다.
`ubuntu-ssh/1.2` 이후에는 서비스 조회 두 개를 포함한 여섯 명령과 서비스 관찰값도 검사합니다.
잘못된 지문으로 두 번째 수집을 실행해 `SSH_HOST_KEY_MISMATCH`와 인벤토리 미생성,
이전 정상 스냅샷 보존을 확인합니다. 이 DB를 백업·검증·별도 파일로 복원한 뒤,
새 앱과 DB 연결에서 정상 인벤토리·수집 근거·실패 이력이 API 응답 단위로 동일한지 검사합니다.

VM은 브리지·호스트 폴더 마운트 없이 만들었습니다. MySQL은 VM의
`127.0.0.1:3306/33060`에서만 수신합니다. `collector`는 sudo 그룹에 속하지 않으며,
공개키에 `restrict,command="/usr/local/libexec/cti-readonly"`를 적용했습니다.
root 소유 래퍼는 `backend.collectors.ssh_protocol.COMMANDS`와 정확히 일치하는
명령만 실행합니다. 별도로 SSH `id`의 종료 코드 126과 `sudo -n true` 거부를 확인했습니다.
호스트 공개키는 SSH 최초 접속 결과가 아닌 Multipass 관리 채널로 가져왔습니다.

## 세 가지 복원 검증

1. **CTI 수집 DB:** 위 자동시험에서 실제 수집 결과와 실패 이력을 별도 SQLite로 복원했습니다.
2. **Ubuntu VM:** `mysql-baseline` 정지 스냅샷을 만든 뒤 시험용 행을 수정하고,
   MySQL 설정에 주석을 추가하고, 서비스를 중지·비활성화했습니다. 스냅샷 복원 후
   원래 행, 서비스 `active/enabled`, 실행 파일·설정 파일 해시를 확인했습니다.
   다시 실행한 인수 시험의 OS·패키지 목록·버전·명령 출력 SHA-256도 복원 전과 같았습니다.
3. **DB 논리 백업:** MySQL `mysqldump --single-transaction --no-tablespaces` 결과를
   다른 DB로 복원해 시험용 행 일치를 확인했습니다. PostgreSQL은 `pg_dump -Fc`와
   `pg_restore --exit-on-error --no-owner`로 별도 DB에 복원한 뒤 public 테이블 24개의
   행 수와 정렬한 JSON 행 SHA-256을 전부 비교했습니다. 복원한 PostgreSQL에서도
   전체 시험 중 기존 통합 시험이 통과했습니다.

VM 복원 전후의 고정 명령 출력 해시:
`4ae0e6486491d7cf21b427586af06861fbeb358701b798ec19d3b399ac0f6db0`.

MySQL 실행 파일 `/usr/sbin/mysqld` 해시:
`3bc577a5948c24ee6bf5341575ec365e12b80530ffc665e6f3300ce9b4938d75`.

설정 파일 `/etc/mysql/mysql.conf.d/mysqld.cnf` 해시:
`1568865c11250920efff06c2132e5e9e4a9bd6e8683d484d7e7cf1a37c5027fd`.

## 자동시험 재실행

MySQL 시험에는 Ubuntu 22.04 또는 24.04의 실제 MySQL 8.0 설치 서버와 고정 읽기
명령이 허용된 SSH 계정이 필요합니다. 개인키는 소유자 전용 권한으로 별도 디렉터리에
두고, 공개키 지문은 서버 관리 채널에서 확인합니다. 다음 JSON은 형식 예시입니다.
문서용 IP·지문을 실제 시험 VM 값으로 교체합니다.

```json
{
  "host": "192.0.2.10",
  "port": 22,
  "username": "collector",
  "key_alias": "collector_key",
  "host_fingerprint": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```

```bash
TEST_MYSQL_SSH_PROFILE=/absolute/path/mysql-profile.json \
TEST_MYSQL_KEY_DIRECTORY=/absolute/path/keys \
uv run pytest tests/integration/test_mysql_lab.py -ra \
  -o junit_family=legacy --junitxml=.data/mysql-lab.xml
```

프로필을 지정하지 않으면 이 시험은 skip합니다. 지정한 프로필이나 키가 잘못되면
skip 대신 실패합니다. 실제 서버에서 패키지 설치·서비스 변경·스냅샷 복원은 수행하지 않고,
고정 SSH 읽기 명령과 임시 CTI DB만 사용합니다. `--basetemp`를 지정한다면 기존 자료가
없는 새 시험 디렉터리를 사용하세요. pytest가 해당 디렉터리를 정리할 수 있습니다.
MySQL 서비스의 기본 기대 상태는 `active`입니다. 관리자가 별도로 서비스를 중지한
경우 `TEST_MYSQL_SERVICE_STATE=inactive`로 기대값을 지정할 수 있습니다.
Apache도 설치한 환경은 `TEST_APACHE_SERVICE_STATE=active`를 지정하면
Apache 바이너리 패키지 설치와 활성 상태까지 함께 검사합니다.

PostgreSQL에는 pgvector가 설치된 **시험 전용 DB**를 준비하고 `TEST_POSTGRES_URL`을
설정한 후 실행합니다. 기존 애플리케이션 DB를 지정하지 않습니다.

```bash
uv run pytest tests/integration/test_postgres.py -ra
```

이 시험은 마이그레이션 적용·모델 일치·pgvector 설치·readiness·API 작업 접수·Worker
완료와 중복 Worker 차단을 확인합니다. 두 환경 변수를 모두 설정한 뒤 `uv run pytest -ra`를
실행하면 이번처럼 두 실환경을 전체 회귀 검사에 포함할 수 있습니다.

## 남긴 자료와 검증 경계

로컬 `.data/acceptance-20261111/`에 JUnit XML, VM 명세, 수집 전·변경 후·복원 후
기록, MySQL·PostgreSQL 덤프와 SQLite 백업, 전용 SSH 프로필·키를 보관합니다.
이 디렉터리는 Git 제외 대상이며 소유자만 접근하도록 설정합니다. 개인키·접속 설정·덤프는
커밋하지 않습니다. VM `cti-acceptance-20261111`과 `mysql-baseline` 스냅샷은 정지 상태로
남겨 재사용할 수 있게 하고, 일회용 PostgreSQL 컨테이너는 결과 보관 후 제거합니다.

위 초기 검증의 MySQL 서비스 상태·파일 해시는 **관리 채널에서 별도로 관찰**한 결과입니다.
이후 `ubuntu-ssh/1.2`부터는 서비스 상태를 수집 근거 API에도 저장합니다.
추가 개발과 실환경·화면 검증은 [서비스 수집 검증 기록](service-collection-verification.md)에 정리합니다.
SSH 인벤토리의 설치 출처는 `UNKNOWN`을 유지합니다. 공식 패키지 서명·파일 일치,
취약/수정 버전 전후 판정, Ubuntu 22.04·amd64, 브라우저 클릭, 별도 API/Worker 프로세스,
GPU·LLM 연결 및 운영 규모의 부하·장애 시험은 이번 결과에 포함하지 않습니다.
