# PostgreSQL 백업·복원 자동화

저장소 루트에서 `scripts.postgres_backup`을 실행합니다. 호스트에는 프로젝트 Python
의존성과 Docker Compose가 필요하며 PostgreSQL 클라이언트를 별도로 설치하지 않습니다.
`db` 컨테이너의 서버와 같은 버전인 `pg_dump`·`pg_restore`를 사용합니다.
이 도구는 기준 Compose의 로컬 소켓 인증과 DB 생성 권한을 전제로 합니다.
외부 관리형 DB, 제한된 운영 계정, 다른 서비스 이름은 별도 연결 구현이 필요합니다.

## 실행

```bash
uv run python -m scripts.postgres_backup create .data/backups/cti-20261112.dump \
  --project-name blended-threat-intel --env-file .env
uv run python -m scripts.postgres_backup verify .data/backups/cti-20261112.dump
uv run python -m scripts.postgres_backup restore .data/backups/cti-20261112.dump \
  --project-name blended-threat-intel --env-file .env --target-db cti_restore_20261112
```

기존 파일과 기존 DB를 덮어쓰지 않습니다. 성공한 복원 DB는 남겨 두며 API·Worker의
접속 대상은 자동 변경하지 않습니다. `--database`는 기본 `POSTGRES_DB` 대신 사용할
원본 DB 이름입니다. `--timeout`은 개별 Docker 명령의 제한 시간이며 기본 300초입니다.
전체 작업의 제한 시간이 아니므로 큰 DB에는 별도의 실행 시간·디스크 감시가 필요합니다.
추가 Compose 파일을 사용했다면 실행 시에도 같은 `COMPOSE_FILE`을 지정합니다.
예약 실행기는 이 명령을 호출할 수 있으나 주기·보존 기간·외부 저장소 전송은 설정하지 않습니다.

## 성공 조건

1. `pg_dump -Fc --no-owner --no-acl`의 custom archive를 처음부터 `0600`으로 생성합니다.
2. 무작위 이름의 새 DB에 `pg_restore --exit-on-error --single-transaction`으로 시험 복원합니다.
3. 복원본의 Alembic revision, 모든 사용자 테이블의 행 수·행 내용 해시,
   시퀀스의 `last_value/is_called`, 확장 모듈 버전을 수집하고 임시 DB를 삭제합니다.
4. 덤프 크기·SHA-256·생성 시각·서버 major와 위 검증 정보를 `.dump.json`에 기록합니다.
5. 별도 `restore`에서도 SHA-256을 먼저 검증하고 새 DB에 복원한 뒤 동일 정보를 대조합니다.
   불일치하면 이번 실행이 만든 대상 DB만 삭제합니다. 이미 존재하는 DB는 삭제하지 않습니다.

행 해시는 PostgreSQL에서 JSON 표현의 SHA-256을 정렬해 계산합니다. 원시 행을 터미널에
출력하지 않고 중복 행까지 비교합니다. 메타데이터는 실행 중 계속 바뀔 수 있는 원본 DB가
아닌 덤프의 시험 복원본에서 만들므로 하나의 덤프 시점을 검증합니다.
`verify`만 실행하면 파일 무결성을 확인하며 DB 복원 시험을 다시 수행하지 않습니다.
Python 오류 출력에는 비밀번호·DB 행·PostgreSQL stderr를 포함하지 않습니다.

## 범위와 운영 복구

이 방식은 단일 DB의 논리 백업입니다. DB 안의 수집 근거·공식 자료 원문·분석·보고서·
감사 이력·계정·세션도 포함됩니다. 파일 시스템의 SSH 키, `.env`, 패키지 캐시, 외부 파일,
클러스터 전체 역할·비밀번호·소유권·ACL은 포함하지 않습니다. 역할은 대상 환경에서 준비하며
복원 개체는 실행 DB 계정 소유가 됩니다. PITR/WAL 및 PostgreSQL major 업그레이드는
이 도구의 범위가 아닙니다. 자동 검증은 동일 major를 요구하며 현재 실기동 기준은 17입니다.
테이블 내용 대조는 모든 인덱스·제약·함수 정의에 대한 독립적인 스키마 비교를 뜻하지 않습니다.

복구 전에는 API·Worker 쓰기를 중지하고 최종 백업을 보존합니다. 새 DB로 복원·검증한 뒤
배포 설정의 DB 이름을 변경하고 기존 스키마와 앱 버전을 맞춰 재시작합니다. 준비 상태와
기존 자산·수집 이력·보고서를 확인합니다. 이전 DB는 검증 종료 전까지 유지합니다.
복원 이후 새 쓰기가 발생했다면 이전 DB로 단순 전환하면 해당 쓰기가 누락될 수 있습니다.

POSIX 파일 권한은 `0600`, 새 백업 디렉터리는 `0700`입니다. 기존 디렉터리 권한은
변경하지 않으며 Windows에서는 디렉터리 ACL을 별도로 제한합니다. 백업에는 세션과
계정 해시가 있으므로 덤프와 manifest를 함께 보호된 저장소에 보관합니다.
SHA-256은 우발적 손상 검출이며 악의적으로 함께 바뀐 덤프·manifest의 진위를 보증하지
않습니다. PostgreSQL 덤프 복원은 SQL을 실행하므로 직접 관리하는 신뢰된 백업만 사용합니다.

비정상 프로세스 종료나 Docker 연결 단절로 정리에 실패하면 `cti_backup_verify_*` DB가
남을 수 있습니다. 실행 중인 다른 백업이 없는지와 생성 경위를 확인해 수동 정리합니다.
자동화는 기존 DB를 추측하여 삭제하지 않습니다. 실패한 백업 경로의 잔여 파일도 확인한 뒤
새 이름으로 재실행합니다. `docker compose down`은 볼륨을 유지하며 `down -v`는
시험 데이터 폐기 시에만 사용합니다.

## 검증

```bash
uv run pytest tests/unit/test_postgres_backup_tool.py
TEST_POSTGRES_COMPOSE_PROJECT=blended-threat-intel \
TEST_POSTGRES_COMPOSE_ENV_FILE=.env \
uv run pytest tests/integration/test_postgres_backup.py -v
```

통합 시험은 명시한 **폐기 가능한 시험 DB**에 임시 테이블을 만들고 제거합니다.
CI의 Compose smoke 단계에서도 실행합니다. 미지정 시 skip하며 실행한 것으로 기록하지 않습니다.
원본의 백업 후 변경, 한글 JSON, 따옴표 포함 식별자, SERIAL 시퀀스, 기존 DB 보호,
복원 불일치 정리, 덤프 변조 검출을 실제 PostgreSQL에서 검사합니다.

설계 근거: [PostgreSQL 17 pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html),
[PostgreSQL 17 pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html).

## 계정 데이터가 있는 복원 인수

계정·권한·세션·감사·보고서를 실제 API로 생성해 백업하고 새 DB/API에서 접근 제한과
다운로드 내용이 유지되는지 확인하는 [계정 복원 인수 시험](accounts-recovery-verification.md)을
추가했습니다. 백업 이후의 권한 회수나 세션 취소가 자동 재적용되는 것은 아니므로 운영 전환 전
세션 취소·최신 권한 재적용 절차를 따릅니다. 이 시험은 검색·LLM·보고서 구현을 변경하지 않습니다.

## 환경 파일·SSH 키와 함께 보관

[운영 파일 암호화 백업](operations-file-backup.md)은 `.env`, SSH 키, 선택한 근거 파일을
별도 복구키로 암호화합니다. 이 도구로 생성한 덤프와 manifest도 평문 tar 총 64 MiB 한도 안에서
함께 넣을 수 있습니다. 복원된 덤프를 본 도구에 전달해 새 DB로 복원하고, 환경 파일의 복구 대상
경로를 검토한 후 서비스를 연결합니다. 복구키는 백업과 분리 보관하며 외부 복제·보관 정책은 별도입니다.
