# HTTPS 배포·계정 인수

윤선빈 담당의 배포 설정과 독립 인수 시험입니다. 최신 main의 인증·자산 권한·검색·LLM·보고서
로직은 변경하지 않습니다. 기존 `compose.yaml` 위에 `compose.https.yaml`을 추가 적용합니다.
기본 HTTP 개발 구성은 그대로 사용할 수 있습니다.

## 배포 설정

- Web의 호스트 공개 포트는 HTTPS 하나로 교체됩니다. 단순 추가가 아닌 `ports: !override`이므로
  [Docker Compose 2.24.4 이상](https://docs.docker.com/reference/compose-file/merge/)이 필요합니다.
- 기본 공개 주소는 `127.0.0.1:8443`입니다. API·Worker·DB 포트는 공개하지 않습니다.
  `HTTPS_BIND_ADDRESS`·`HTTPS_PORT`를 실제 허가된 인터페이스·포트로 설정합니다.
- API·Worker의 `AUTH_MODE=accounts`, `SESSION_COOKIE_SECURE=true`를 강제합니다.
  환경 파일이 token/false여도 HTTPS overlay가 우선합니다. 기본 개발 토큰은 계정 접근을 우회하지 못합니다.
- Nginx는 TLS 1.2·1.3만 허용합니다. HSTS는 우선 1일이며 `includeSubDomains`·preload는
  설정하지 않습니다. 인증서 갱신·복구 절차를 검증한 후 서비스 정책에 따라 기간을 조정합니다.
  설정 근거는 [Nginx HTTPS 문서](https://nginx.org/en/docs/http/configuring_https_servers.html)입니다.
- API 요청의 Host와 포트를 보존하며, Origin이 있으면 현재 HTTPS Origin과 정확히 일치해야 합니다.
  같은 Host의 `http://` Origin도 거부합니다. Origin 없는 CLI 요청은 허용하지만 기존 앱의
  세션 쓰기에는 CSRF 토큰이 계속 필요합니다. Web에서 외부가 준 전달 주소를 그대로 신뢰하지 않습니다.
- 내부 8080은 `/api/v1/readiness` 전용입니다. 나머지 경로는 404이며 호스트에는 공개하지 않습니다.
  HTTP에서 HTTPS로 자동 리디렉션하는 별도 공개 포트는 만들지 않습니다. HTTPS URL로 접속합니다.
- 기존 healthcheck는 내부 readiness를 확인합니다. 외부 TLS 인증서의 신뢰·만료·DNS까지 확인하는
  것은 아니므로 아래 HTTPS 확인과 외부 모니터링을 따로 수행합니다.

## 인증서와 계정 준비

1. 서비스 DNS 이름을 확정하고 해당 이름이 SAN에 포함된 유효한 서버 인증서와 체인을 준비합니다.
   사설 CA를 사용할 때는 접근 클라이언트에 승인된 CA 신뢰를 배포합니다. 테스트 인증서를 운영에 쓰지 않습니다.
2. 전용 TLS 디렉터리에 `fullchain.pem`과 `privkey.pem`을 배치합니다. 다른 인증정보를 같은 디렉터리에
   넣지 않습니다. 컨테이너에는 이 디렉터리를 읽기 전용으로 마운트합니다. 없는 경로를 자동 생성하지 않습니다.
3. 키는 소유자와 전용 TLS 읽기 그룹만 접근하도록 `0640`, 디렉터리는 `0750`으로 제한하고
   `TLS_READ_GID`에 그 그룹의 숫자 GID를 지정합니다. Web에만 해당 보조 그룹을 추가합니다.
   `fullchain.pem`도 `0640`으로 둘 수 있습니다. 키를 world-readable로 만들지 않습니다.
4. 인증서 관리 도구가 만든 외부 경로의 심볼릭 링크를 그대로 마운트하지 않습니다. 승인된 갱신 hook에서
   체인과 키의 실제 파일을 전용 디렉터리에 배치하고 권한을 유지합니다.
5. 기존 배포 환경 파일에 아래 설정을 추가합니다. 환경 파일과 SSH 키의 기존 보호·백업 절차를 유지합니다.

```dotenv
# 실제 승인된 경로·전용 그룹으로 변경
TLS_DIRECTORY=/srv/cti/tls
TLS_READ_GID=2001
HTTPS_BIND_ADDRESS=127.0.0.1
HTTPS_PORT=8443
```

공유·외부 인터페이스로 공개하기 전에 계정 초기화를 끝내고 방화벽·허가 대상·도메인을 확인합니다.
운영 호스트에서 다른 Compose override를 추가한다면 최종 적용 순서를 다시 검토합니다.

## 기동과 확인

저장소 루트에서 실행합니다. 아래 명령은 기존 DB 볼륨을 사용하므로 먼저 검증된 백업을 확보합니다.
환경 파일·인증정보가 출력되는 `docker compose config` 전체 출력은 공유하지 않습니다.

```bash
docker compose --env-file .env -f compose.yaml -f compose.https.yaml config --quiet
docker compose --env-file .env -f compose.yaml -f compose.https.yaml up --build -d --wait

# 첫 관리자: 기존 명령의 숨김 비밀번호 입력 사용
docker compose --env-file .env -f compose.yaml -f compose.https.yaml exec api \
  python -m scripts.manage_users admin
```

관리자가 이미 있다면 새로 만들 필요가 없습니다. HTTPS 전환 시 기존 HTTP 세션을 재사용하려 하지 말고
브라우저에서 로그아웃 후 재로그인해 Secure 쿠키를 발급받습니다. 예시 주소 `cti.example.org`는
실제 인증서 이름으로 바꿉니다.

```bash
# 공인 CA 인증서
curl --fail https://cti.example.org:8443/api/v1/readiness
# 사설 CA 인증서: 승인된 CA 파일 지정
curl --fail --cacert /secure/cti-ca.pem https://cti.example.org:8443/api/v1/readiness
```

인증서 오류를 피하려고 `curl -k`나 클라이언트 검증 해제를 운영 절차에 넣지 않습니다.
실제 브라우저에서 인증서 경고 없이 로그인 → 페이지 새로고침 → 부여된 자산/보고서 조회 →
로그아웃을 확인합니다. 운영자·조회자가 다른 자산과 관리자 기능에 접근할 수 없는지도 확인합니다.
Secure·HttpOnly·SameSite=Strict·Path=/api 쿠키와 CSRF 차단을 점검합니다.

이 overlay는 인증서 자동 발급/갱신, DNS, 방화벽, 비밀 저장소를 구성하지 않습니다. 내부 네트워크의
Nginx→API→DB 전 구간 암호화나 다중 조직·접속 제한 정책을 추가한 구성도 아닙니다.
기존 APP_ENV 및 모델 실행 설정은 유지합니다. BGE·GPU 배포는 별도 담당 인터페이스를 따릅니다.
로그인 실패 제한도 기존 정책을 사용합니다. API가 프록시 주소로 요청을 집계할 수 있으므로,
이번 시험을 사용자별 실제 접속 IP 전달·분산 속도 제한 검증으로 해석하지 않습니다.

## 인증서 갱신과 장애 처리

새 키·체인을 검증한 뒤 마운트된 디렉터리에 두 파일을 모두 배치합니다. 디렉터리를 통째로
교체하기보다 그 안의 파일을 갱신해 bind mount가 새 파일을 보도록 합니다. 현재 파일을 별도로
보존하고, 두 파일 갱신이 끝나기 전에는 reload하지 않습니다.

```bash
docker compose --env-file .env -f compose.yaml -f compose.https.yaml exec web nginx -t
# 위 명령 성공 시에만 실행
docker compose --env-file .env -f compose.yaml -f compose.https.yaml exec web nginx -s reload
```

`nginx -t` 실패 시 reload하지 않습니다. 기존 워커는 메모리에 로드한 인증서로 계속 서비스할 수 있지만
컨테이너가 재시작하면 잘못된 파일 때문에 기동하지 못하므로 즉시 파일·권한을 복구합니다.
성공 후 새 TLS 연결로 인증서 일련번호/유효기간과 기존 로그인 세션을 확인합니다.
인증서 내용이 유효한지 검사하는 `nginx -t`만으로 공인 신뢰·호스트명·만료 검증이 끝나는 것은 아닙니다.

API를 재생성한 뒤에는 Nginx의 Docker DNS 갱신과 기존 세션·조회 결과 보존을 확인합니다.
전환을 되돌릴 때는 공개 접근부터 차단하고 이전 설정·인증서로 복구합니다. HTTPS 실패를 피하려고
공유 네트워크에 HTTP/token 모드를 공개하지 않습니다. HSTS를 이미 받은 브라우저는 설정 기간 동안
HTTP로 되돌릴 수 없다는 점도 전환 계획에 포함합니다.

## 자동 인수 시험

전용 시험은 임의 프로젝트 이름·새 DB 볼륨·루프백 임의 HTTPS 포트를 사용합니다. 기본 `.env`의
외부 LLM/SSH 인증정보를 사용하지 않고, 임시 환경 파일에서 해당 설정을 비웁니다. 새 관리자 비밀번호는
생성해 표준 입력으로 전달하며 로그에 출력하지 않습니다. 각 실행은 전용 CA와 서버 키를 만듭니다.

```bash
uv sync --frozen
# 별도 시험 가상환경에서 설치 권장; 애플리케이션 의존성 파일은 바뀌지 않음
uv pip install --python .venv/bin/python playwright==1.58.0
.venv/bin/python -m playwright install chromium
TEST_HTTPS_DEPLOYMENT=1 .venv/bin/python -m pytest tests/integration/test_https_deployment.py -v
```

Linux에서 브라우저 OS 라이브러리가 없으면 Playwright의 `install --with-deps chromium` 준비가 필요합니다.
새 `.github/workflows/https-acceptance.yml`은 Linux에서 별도 실행하며 다른 팀원의 CI 단계를 변경하지 않습니다.
명시적으로 시험을 켜지 않으면 3개 시험은 skip입니다. 이 시험을 운영 프로젝트 대상으로 실행하는 옵션은 없습니다.

- HTTPS 포트만 공개되고 token/false 설정이 계정/Secure 설정으로 덮어써지는지 검사합니다.
- 신뢰하지 않는 CA·틀린 호스트명 거부, TLS 1.2/1.3 연결, 평문 HTTP 거부를 실제 TLS 소켓으로 확인합니다.
- 계정 3개 역할, 자산·작업·보고서 접근, CSRF·잘못된 Origin, 만료·비활성 세션, 로그아웃 후 재사용,
  로그인 실패 제한과 보고서 해시를 실제 Nginx/API/Worker/PostgreSQL 경로로 검사합니다.
- 실제 Chromium에서 로그인·새로고침·로그아웃과 쿠키 속성·JS 접근 불가를 확인합니다.
  이 브라우저 프로세스에는 **이번 시험 서버 키의 SPKI만** 예외로 지정합니다. OS 신뢰 저장소는
  변경하지 않으며 전체 인증서 검증 해제나 `ignore_https_errors`는 사용하지 않습니다.
  공인 인증서의 실제 브라우저 신뢰 검증을 대체하지 않습니다. CA/호스트 검증은 별도 Python TLS
  클라이언트에서 엄격하게 수행합니다.
- 인증서 누락 시 preflight 실패와 기존 연결 유지, 새 인증서 reload, API 재생성 후 세션·데이터 보존을 검사합니다.
- 종료 시 전용 컨테이너·볼륨·네트워크와 임시 인증서/환경 파일을 정리합니다. 강제 종료 시 남은
  `cti-https-<12자리 hex>` 프로젝트는 생성 경위를 확인해 정리합니다. 다른 프로젝트에는 적용하지 않습니다.

## 실검증 — 2026-11-19 KST

- 최신 main `f7f0db9`에서 분기한 `feat/https-account-acceptance`에서 검증했습니다.
- macOS arm64 Docker Compose 5.1.0에서 실제 HTTPS 인수와 기존 계정 회귀는 **8 passed,
  0 skipped / 57.33초**였습니다. 기존 Starlette deprecation 경고 1건입니다.
- 이후 HttpOnly 확인을 `/api` 경로의 일반 쿠키와 대조하도록 강화했습니다. 이 최종 브라우저
  시험은 **1 passed / 34.92초**이며 앞선 브라우저 시험과 중복이므로 단순 합산하지 않습니다.
- Chromium 145에서 로그인·쿠키 속성·새로고침·로그아웃을 검증했습니다. 임시 키 SPKI 예외를
  사용한 시험으로, 공인 인증서·외부 도메인에 대한 배포 완료를 뜻하지 않습니다.
- TLS 1.2/1.3, CA/호스트명 오류 거부, 평문 HTTP 거부, 계정 권한·보고서 해시, 인증서
  누락 preflight 실패·새 인증서 반영·API 재생성 후 세션 보존을 확인했습니다.
- Ruff 검사·포맷을 통과했고 시험 컨테이너·볼륨·네트워크 잔여가 없는 것을 확인했습니다.
  Git 제외 `.data/https-acceptance-20261119/`에 JUnit·검증 요약·정리 결과만 기록합니다.
- 실제 서비스 DNS·인증서 발급/갱신 계정·공개 인터페이스·외부 접속 검증은 배포 환경 확정 후 수행합니다.
