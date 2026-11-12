# Compose → 실제 Ubuntu SSH 통합 검증

## 범위와 실제 결과 — 2026-11-12 KST

전용 Docker 프로젝트 `cti-ssh-acceptance-20261112`와 기존 시험 VM
`cti-jammy-20261111`을 연결했습니다. 웹은 호스트의 `127.0.0.1:18081`에만 공개하고
실제 VM IP·SSH 포트 한 쌍만 허용했습니다. 기존 사용자 DB·운영 서버를 사용하지 않았습니다.

검증 경로는 브라우저/Nginx → API → PostgreSQL → 별도 Worker → 실제 Ubuntu SSH
→ PostgreSQL → API/화면입니다. TestClient에서 Worker 함수를 직접 호출하거나
원격 응답을 fixture로 대체하지 않았습니다.

- Ubuntu 22.04.5 arm64에서 패키지 642개를 수집했습니다.
  Apache `2.4.52-1ubuntu4.26`, MySQL `8.0.46-0ubuntu0.22.04.4`가 포함됩니다.
- Apache·MySQL의 `active/running/enabled`를 확인했습니다. 수집기는 고정 읽기 명령만 실행합니다.
- 실제 브라우저의 수집 버튼으로 작업을 접수하고 수집 완료·서비스 상태·패키지 목록을 확인했습니다.
- 같은 Idempotency-Key로 두 번 접수해도 같은 수집 ID가 반환됐습니다.
- 틀린 호스트 키는 `SSH_HOST_KEY_MISMATCH`로 실패하고 새 인벤토리를 만들지 않았습니다.
- 시험 VM의 서비스 조회 두 명령만 임시로 거부했을 때 작업은 `PARTIAL`, 서비스는 `UNKNOWN`이었고
  완전하게 읽은 패키지 642개는 `COMPLETE` 인벤토리로 보존됐습니다. 화면에서도 구분했습니다.
- 잘못된 키 파일 권한(0644)과 미허가 IP는 API에서 각각 `SSH_KEY_UNAVAILABLE`,
  `SSH_TARGET_NOT_ALLOWED`로 거부됐습니다. 키는 0600으로 복구했습니다.

API·Worker는 UID 10001의 비루트 계정으로 실행했고 SSH 키는 읽기 전용 마운트였습니다.
Docker Desktop에서 호스트 chmod가 컨테이너 stat에 반영된 것을 확인한 뒤 권한 거부를
검사했습니다. Linux 배포에서는 바인드 마운트의 UID·접근 권한을 별도로 맞춰야 하며,
이 결과를 모든 호스트의 파일 소유권 매핑 검증으로 확대하지 않습니다.

## 재기동과 장애 복구

Compose를 `down`으로 종료하고 볼륨을 유지해 다시 기동했습니다.
정상·부분·실패 수집 및 인벤토리의 저장된 API 응답을 전부 대조해 일치를 확인했습니다.
브라우저도 새로고침·재연결한 뒤 기존 이력과 서비스 상태를 조회했습니다.
추가로 API 주소 변경 검사도 통과했습니다.

시험 VM의 읽기 응답을 잠시 지연시켜 작업이 `RUNNING`일 때 **실제 Compose Worker를
SIGKILL**했습니다. Worker 재기동 후 작업은 `FAILED/WORKER_RESTARTED`, 인벤토리는
미생성 상태였고 `job.interrupted` 감사 이벤트는 1건이었습니다. 기존 정상·부분 이력은
바뀌지 않았고 새 수집이 성공해 동시 실행 슬롯의 해제도 확인했습니다.

래퍼 변경은 시험 관리 채널에서 수행했습니다. stdin 전달이 대기한 첫 시도는 종료하고
원본을 복구했으며, 실제 시험에서는 제한 시간을 둔 파일 전송·설치와 `finally` 복구를
사용했습니다. 수집 도구가 서비스나 원격 권한을 변경하는 기능을 추가한 것은 아닙니다.

## 재실행 도구

`scripts/smoke_ssh_http.py`는 실행 중인 **토큰 모드 전용 시험 스택**에 새 자산·프로필·
수집 이력을 만듭니다. Apache와 MySQL이 설치되고 활성인 Ubuntu VM을 대상으로 합니다.
Compose를 띄우거나 VM·래퍼·서비스를 변경하지 않습니다. 비밀값은 `DEV_API_TOKEN` 환경
변수 또는 로컬 `.env`에서 읽고, 접속 프로필은 [기존 SSH 인수 형식](lab-acceptance.md)을 씁니다.
Compose의 `--env-file`만 지정해도 이 Python 명령에 환경 변수가 자동 전달되는 것은 아닙니다.

```bash
uv run python -m scripts.smoke_ssh_http collect \
  --base-url http://127.0.0.1:18081 \
  --profile .data/lab/profile.json \
  --evidence .data/lab/normal.json

# 별도 재기동 전후 같은 저장 응답을 비교합니다.
uv run python -m scripts.smoke_ssh_http verify \
  --base-url http://127.0.0.1:18081 \
  --evidence .data/lab/normal.json
```

관리자가 시험 래퍼에서 서비스 조회를 거부하도록 준비했다면 `collect --expect-partial`을
사용합니다. 정상 수집과 별도 증거 파일을 지정해야 합니다. 도구는 호스트 키 실패 검증 뒤
유효한 프로필을 다시 저장하여 시험 자산의 최신 연결 설정을 복구합니다.

증거는 새 파일에만 0600으로 저장합니다. 이미 있는 파일을 덮어쓰지 않고, `verify`는
허용된 자산별 수집·인벤토리 경로만 요청해 변조된 증거의 외부 URL로 토큰을 보내지 않습니다.
이 보호와 응답 변경 감지에 대한 단위 시험 3개가 통과했습니다.

## CI 보완과 검증 경계

첫 원격 PR CI에서 Backend·Frontend는 통과했으나, API 주소 변경 검사의
`docker run --ip` 단계가 종료 코드 125로 실패했습니다. 기존 코드는 stderr를 숨겨
세부 Docker 오류를 남기지 못했습니다. stderr를 보존하도록 수정하고 CI 전용
`.github/compose-smoke.yaml`에 명시적 IPAM 서브넷을 추가했습니다.
일반 Compose의 네트워크는 변경하지 않습니다. 같은 override를 적용한 로컬 실제
주소 변경 검사와 수정 커밋 `dd6bf9b`의
[원격 CI #10](https://github.com/Keeper-BM/cti-agent/actions/runs/43142429093)에서
Backend·Frontend·Compose 세 작업이 모두 통과했습니다.

이번 변경은 통합 인수 도구와 CI 수정입니다. 판정 엔진·LLM·보고서 생성 로직을 수정하지
않았습니다. SSH 수집의 설치 출처·파일 무결성은 여전히 미검증이며, 서비스 활성 상태로
취약 여부를 확정하지 않습니다. HTTPS·GPU/LLM·MySQL 취약/수정 버전 쌍 검증은 별도입니다.

Git 제외 경로 `.data/compose-ssh-acceptance-20261112/`에 정상·부분·실패·중단 복구
응답, 브라우저 화면, 재기동 로그와 시험 DB 백업을 보관합니다. 키·토큰·원시 증거를
커밋하지 않습니다. 시험 종료 시 이 프로젝트의 컨테이너·볼륨을 제거하고 VM은 정지합니다.
