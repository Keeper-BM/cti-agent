# Compose 배포·재생성·계정 인수 검증

## 실제 실행 범위 — 2026-11-11 KST

macOS arm64의 Docker Desktop에서 작업 전용 프로젝트 `cti-acceptance-20261111`을
만들어 Web·API·Worker·DB 이미지를 빌드하고 마이그레이션을 적용했습니다.
시험용 비밀값과 빈 SSH 키 디렉터리를 사용했고 웹은 `127.0.0.1:18080`에만 공개했습니다.
기존 사용자 DB·SSH 키·학교 LLM 인증정보는 복제하지 않았습니다.

- PostgreSQL 17.11·pgvector 0.8.7, Nginx 1.28.2에서 실행했습니다.
- 웹 프록시를 통한 준비 상태·자산 조회·작업 접수 → 별도 Worker 처리 → 성공 조회를 확인했습니다.
- 시험 자산과 완료 작업을 저장한 후 `down`으로 컨테이너만 제거하고 같은 볼륨으로 다시
  기동했습니다. 기존 자산·작업 API 응답이 같았고 새로운 작업도 성공했습니다.
- API·Worker는 `appuser`로 실행하고 SSH 키 경로는 읽기 전용 마운트였습니다.
  DB·API·Worker에는 호스트 공개 포트가 없었습니다.
- 최종 Web·API·DB healthcheck는 모두 healthy였습니다. Worker는 healthcheck 대신
  실제 작업 완료로 동작을 확인했습니다.
- 계정 시험까지 포함한 최종 `pg_dump`를 새 DB에 복원하고 public 테이블 24개의
  행 수·정렬한 행 내용의 SHA-256이 원본과 모두 같은지 확인했습니다. 복원 DB는 제거했습니다.

## 발견한 API 재생성 후 502와 수정

계정 모드 전환으로 API를 재생성하자 API 자체는 healthy인데 웹 요청은 502였습니다.
Nginx가 재생성 전 API의 컨테이너 IP를 계속 사용했습니다.

`infra/nginx.conf`에 공유 메모리 영역을 사용하는 upstream을 만들고 Docker DNS
`127.0.0.11`과 `resolve`, `valid=5s`를 설정했습니다. 현재 이미지의 Nginx 1.28은
이 구성을 지원하며 `nginx -t`를 통과했습니다. 런타임 주소 갱신의 조건은
[Nginx 공식 upstream 문서](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#resolve)를
따릅니다. 이 설정은 현재 Docker Compose 네트워크를 대상으로 합니다.

`scripts/smoke_compose_recreate.py`는 API를 제거한 뒤 이전 IP를 시험용 컨테이너가
잠시 점유하게 합니다. 새 API가 다른 IP를 받았는지 확인하고, 기존 Web의 ID·시작 시각이
변하지 않은 상태에서 준비 상태 요청이 복구되는지 검사합니다. 단순 재시작에서 같은 IP를
받아 문제를 놓치는 경우를 막습니다. 실제 시험을 통과했고 CI의 Compose 검사에도 추가했습니다.
원격 GitHub Actions 실행 결과는 아직 없습니다.

Web healthcheck도 정적 파일 대신 `/api/v1/readiness`를 프록시하도록 추가했습니다.
이제 `docker compose up --wait`가 웹 → API → DB 준비 상태까지 확인합니다.
이는 진행 중 HTTP 요청의 무중단 처리를 보장하지 않으며 재생성 동안 일시 오류가 가능합니다.

다음 명령은 **중단해도 되는 시험 프로젝트에서만** 실행합니다. API를 실제 교체하며,
인수에 지정한 프로젝트·환경 파일을 사용합니다. 중간 실패 시 API 재기동을 시도하고
시험용 IP 점유 컨테이너를 제거합니다.

```bash
uv run python scripts/smoke_compose_recreate.py \
  --project-name my-disposable-cti \
  --env-file .data/my-disposable-cti.env \
  --base-url http://127.0.0.1:18080
```

## 계정 모드의 실제 HTTP 검증

공식 `scripts.manage_users` 명령으로 시험 관리자를 만들고 `AUTH_MODE=accounts`로
API·Worker를 재생성했습니다. 비밀번호는 stdin으로 전달했으며 명령 인수나 로그에 넣지 않았습니다.
수정된 Nginx 경로에서 다음을 확인했습니다.

- 개발 Bearer 토큰으로 계정 인증을 우회하면 401.
- 로그인 성공, `HttpOnly`·`SameSite=strict`·`Path=/api` 쿠키, 내 계정 조회 성공.
- CSRF 토큰 없는 쓰기와 다른 Origin의 쓰기는 403, 올바른 Origin·토큰은 자산 생성 201.
- 로그아웃 직후 같은 클라이언트의 세션 조회는 401.
- 잘못된 비밀번호를 반복하면 401 이후 429. 시험 과정의 앞선 실패도 제한 횟수에 포함됩니다.

루프백 HTTP 시험이므로 HTTPS 및 Secure 쿠키 배포 검증은 포함하지 않습니다.
실제 VM SSH 수집은 [별도 검증](service-collection-verification.md)에서 수행했습니다.
이번 Compose 시험에서 GPU·학교 LLM·운영 네트워크 연결은 시험하지 않았습니다.

## 증거 보관과 정리

Git 제외 경로 `.data/compose-acceptance-20261111/`에 기동·재기동 로그,
`persistence.json`, `accounts-http.json`, `isolation-final.json`, `dns-recreate.log`,
`web-health.log`, `restore-final.json`, PostgreSQL 논리 백업을 보관합니다. 최종 백업에는 시험 계정·세션 정보가
있으므로 디렉터리 0700·파일 0600으로 제한합니다. 임시 로그인 입력 파일은 제거했습니다.
시험 완료 후 이 프로젝트의 컨테이너·볼륨만 제거하고 백업·증거는 보존합니다.
