# 계정·운영·복원

## 계정 연결

마이그레이션을 적용한 뒤 첫 관리자를 생성합니다. 비밀번호는 명령 인수에 넣지 않고 숨김 입력으로 받습니다.

```bash
uv run python -m scripts.manage_users admin
```

`.env`에 `AUTH_MODE=accounts`를 설정하고 API·Worker를 재시작합니다. 웹에서 계정으로 로그인합니다. Compose에서는 `docker compose exec api python -m scripts.manage_users admin`을 사용합니다. 로컬 관리자는 DB 파일·설정 접근 권한을 갖고 있으므로 이 명령을 실행하는 OS 계정도 보호해야 합니다.

| 역할            | 허용 범위                                                           |
| --------------- | ------------------------------------------------------------------- |
| 관리자 ADMIN    | 전체 자산, 신규 자산·계정·권한·SSH 프로필, 공식 자료 갱신·감사 조회 |
| 담당자 OPERATOR | 부여된 자산 조회·수정·입력·수집·검증·분석·질문·보고서               |
| 조회자 VIEWER   | 부여된 자산과 저장된 결과 조회                                      |

**계정·권한**에서 사용자 생성·역할·활성 상태·자산별 부여와 회수를 관리합니다. 마지막 활성 관리자의 권한 제거는 차단합니다. 비활성 계정·역할 변경은 기존 세션을 취소합니다. 권한 회수는 다음 요청과 Worker 실행 검사에 반영됩니다. 각 사용자는 자신의 비밀번호를 바꿀 수 있고 변경 시 모든 세션이 만료됩니다.

비밀번호를 잊으면 로컬 DB 관리 권한으로 다음 명령을 실행합니다. 이 작업은 감사 기록을 남기고 세션을 취소하며 역할·활성 상태를 바꾸지 않습니다.

```bash
uv run python -m scripts.manage_users admin --reset-password
```

`AUTH_MODE=token`은 기존 개발 연결을 위한 모드이며 DEV_API_TOKEN 하나가 관리자 권한을 가집니다. accounts 모드에서는 이 토큰으로 로그인이나 자산 접근을 우회할 수 없습니다.

## 세션·프록시

세션은 기본 8시간(`SESSION_HOURS=1~24`)입니다. 쿠키는 HttpOnly·SameSite=Strict·`/api` 경로를 사용합니다. HTTPS로 제공할 때 `SESSION_COOKIE_SECURE=true`를 설정합니다. 로컬 HTTP 시연은 false를 사용합니다. 로그인 속도 제한은 사용자별 5분 10회, 접속 주소별 30회입니다. 프록시 뒤에서는 동일 프록시 주소로 집계될 수 있습니다.

변경 요청은 `/auth/me` 또는 로그인 응답의 CSRF 토큰을 `X-CSRF-Token`으로 보냅니다. 브라우저 UI가 이를 처리합니다. Vite·Nginx는 Host의 포트를 보존해야 하며 임의의 외부 Origin을 허용하지 않습니다. 토큰·비밀번호·API 키는 URL이나 로그에 넣지 않습니다.

## 감사 기록과 이력 보관

**운영 기록**에서 자산 생성·수정, 파일 입력, SSH 프로필, 로그인·로그아웃·실패, 계정·권한 변경, 작업 접수·종료·거절 기록을 확인합니다. 실제 비밀번호·개인키·학교 API 키·질문 원문은 감사 상세에 기록하지 않습니다. 관리자 전용 조회와 페이지 이동을 제공합니다.

자산·계정은 비활성화하고 과거 수집·분석·답변·보고서는 보존합니다. 자동 보관 기간·물리 삭제·다중 조직 운영은 이 버전의 범위가 아닙니다. 데이터가 쌓이면 DB·공식 패키지 캐시 용량을 확인하고 보호된 저장소로 백업합니다.

## SQLite 백업과 별도 복원

```bash
uv run python -m scripts.database_backup create D:/cti-backups/cti-20261110.db
uv run python -m scripts.database_backup verify D:/cti-backups/cti-20261110.db
uv run python -m scripts.database_backup restore D:/cti-backups/cti-20261110.db D:/cti-backups/restored.db
```

백업은 SQLite online backup API를 사용하며 DB 무결성·외래키·마이그레이션 버전을 검사합니다. SHA-256·크기·시각·스키마 버전이 담긴 `.db.json`을 함께 보관합니다. 복원은 새 파일에만 가능하며 기존 DB를 덮어쓰지 않습니다. 원본 DB와 해시가 다른 백업은 거부합니다.

복원 확인 후 API·Worker를 종료하고 `.env`의 DATABASE_URL을 새 파일로 지정합니다. `alembic upgrade head`와 준비 상태·기존 기록을 확인한 뒤 실행하세요. 기존 파일은 확인이 끝날 때까지 보존합니다. 백업에는 계정 해시와 세션·자산 정보가 있으므로 접근 권한을 제한합니다. `.env`와 SSH 개인키는 DB 백업에 포함되지 않아 별도로 보호·보관해야 합니다.

## PostgreSQL 백업·복원

Compose의 DB 볼륨을 직접 복사하는 대신 pg_dump를 사용합니다. 아래 명령은 Linux 셸 기준이며 비밀번호를 인수로 전달하지 않습니다.

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/cti-backup.dump'
docker compose cp db:/tmp/cti-backup.dump ./cti-backup.dump
```

시험 복원은 기존 DB와 다른 이름으로 수행합니다.

```bash
docker compose cp ./cti-backup.dump db:/tmp/cti-restore.dump
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" cti_restore'
docker compose exec -T db sh -c 'pg_restore --no-owner -U "$POSTGRES_USER" -d cti_restore /tmp/cti-restore.dump'
```

DB가 이미 존재하면 createdb가 실패하므로 그대로 덮어쓰지 않습니다. 복원본의 스키마·행 수·대표 보고서를 확인한 뒤 접속 대상을 바꾸세요. `docker compose down`은 볼륨을 보존합니다. `down -v`는 데이터 볼륨을 삭제하므로 일반 종료 명령으로 사용하지 않습니다.

## 작업 복구

SQLite OS 파일 잠금과 PostgreSQL advisory lock으로 중복 Worker를 차단합니다. Worker를 재시작하면 중간 RUNNING 작업은 WORKER_RESTARTED로 실패하고 기존 결과는 유지합니다. QUEUED 작업은 계속 처리합니다. 실패 이력을 확인한 뒤 새 요청으로 다시 실행하세요. 학교 API 장애 시 분석이나 원문 조회를 다시 실행할 필요는 없습니다.

WSL은 필수 구성 요소가 아닙니다. VirtualBox의 Ubuntu와 D 드라이브의 가상 디스크로 시험할 수 있습니다. 호스트 가상화 설정·호스트 재부팅은 애플리케이션 기능이 수행하지 않습니다.
