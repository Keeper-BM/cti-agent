# SSH 패키지 수집

자산별 SSH 연결 설정을 저장하고 **패키지 정보 가져오기**를 누르면 Worker가 Ubuntu 서버의 설치 패키지를 읽어 기존 인벤토리 형식으로 저장합니다. JSON 입력 기록, 분석, AI 설명, 보고서는 그대로 보존합니다. 저장한 연결 설정만으로 접속하지 않으며, 수집 완료 후 분석은 별도로 요청합니다.

## 지원 범위

- Ubuntu 22.04·24.04, 명시적인 IPv4/IPv6 주소와 포트, 공개키 인증을 지원합니다.
- OS·아키텍처·dpkg 바이너리/소스 패키지명·전체 버전·설치 상태를 조회합니다. 설치가 중단된 패키지도 상태와 함께 남기며, 삭제 후 설정만 남은 패키지는 제외합니다.
- 패키지 목록은 최대 5,000개입니다. 이후 취약점 분석 대상은 기존과 동일하게 Apache2·MySQL Ubuntu 패키지입니다.
- Apache2·MySQL 관련 `apt-cache policy` 출력은 참고 근거로 보관합니다. 네트워크 자료 갱신, 패키지 설치·수정, sudo, 서비스 재시작은 실행하지 않습니다.
- 호스트명·비밀번호 로그인·임의 명령 입력·점프 호스트·자동 주기 수집은 지원하지 않습니다.

## 연결 준비

1. 사용할 Ubuntu 서버에 SSH 공개키 인증으로 접속 가능한 계정을 준비합니다. `/etc/os-release`, dpkg 패키지 DB와 APT 캐시를 읽을 수 있어야 합니다. 관리자 권한은 요구하지 않습니다.
2. 백엔드 컴퓨터의 `.data/ssh-keys/`에 이 계정용 개인키 파일을 둡니다. 예: `.data/ssh-keys/lab_ed25519`. 웹에는 파일 내용이나 절대 경로를 입력하지 않고 등록된 파일 이름만 선택합니다. 키 이름은 영문·숫자로 시작하며 영문·숫자·`_`·`-`·`.`만 최대 80자 허용합니다.
3. `.env`에 허용할 서버의 IP·포트를 지정합니다. 아래 주소는 문서용 예시이므로 실제 서버 값으로 바꾸세요.

```dotenv
SSH_ALLOWED_TARGETS=192.0.2.10:22
SSH_KEY_DIRECTORY=.data/ssh-keys
SSH_KEY_PASSWORD=
SSH_TIMEOUT_SECONDS=45
```

여러 대상은 쉼표로 구분합니다. IPv6 예시는 `[2001:db8::10]:22`입니다. 지정한 IP·포트만 접속하며 DNS 조회를 하지 않습니다. 링크 로컬·멀티캐스트·미지정 주소는 거부합니다. 대상은 요청 접수 시와 실제 작업 시작 시 모두 검사합니다.

암호화된 개인키는 `SSH_KEY_PASSWORD`에 키 암호를 설정합니다. 현재 모든 등록 키에 동일한 암호 설정을 사용합니다. 이 값과 개인키는 브라우저·DB·API 응답에 저장하지 않습니다. Linux에서는 키 파일의 그룹·기타 사용자 접근 권한을 제거해야 합니다(예: 소유자만 읽는 `0600`). Windows에서는 운영체제의 파일 ACL로 접근을 제한하며, 앱이 ACL 적절성을 자동 판정하지는 않습니다. 심볼릭 링크와 키 디렉터리 밖의 파일은 거부합니다.

4. **서버 관리자에게 별도 경로로 확인한 SSH 호스트 키 지문**을 받습니다. 서버 콘솔에서 ED25519 호스트 공개키가 존재하는 경우 다음 명령으로 확인할 수 있습니다. 호스트 키 지문과 로그인용 개인키는 서로 다른 정보입니다.

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

출력의 `SHA256:...` 부분만 사용합니다. 서버가 실제 SSH 협상에서 제공하는 호스트 키와 일치해야 합니다. 최초 접속에서 받은 키를 자동으로 신뢰하거나 저장하지 않습니다. 지문이 다르면 인증키를 사용한 로그인 전에 중단합니다.

5. API와 Worker를 다시 시작합니다. 설정을 같은 값으로 읽어야 하며, 개발 실행기는 `make dev` 또는 `python scripts/dev.py`를 사용합니다. `make dev-ui`는 Worker가 없으므로 수집이 대기 상태에 머뭅니다.

Compose는 설정한 키 디렉터리를 `/run/cti-ssh-keys`에 읽기 전용으로 마운트합니다. 컨테이너 실행 사용자 UID `10001`이 해당 개인키를 읽을 수 있어야 합니다. 호스트의 소유권·권한을 해당 배포 환경에 맞추세요. 이번 단계에서는 Compose 실기동을 검증하지 않았습니다.

## 화면 사용 순서

1. **자산 현황 → 자산 이름**을 선택합니다.
2. **서버 패키지 가져오기**에서 IP, 포트, 계정, 등록 인증키, 호스트 키 지문을 입력하고 **연결 설정 저장**을 누릅니다.
3. **패키지 정보 가져오기**를 누릅니다. 대기·수집 중·완료·일부 수집·실패 상태를 확인합니다.
4. 완료되면 아래 패키지 목록에 새 기록이 표시됩니다. 수집 이력에서 과거 조회 대상과 결과를 다시 볼 수 있습니다.
5. **수집 근거와 확인하지 못한 정보**에서 명령별 출력·종료 코드·지문·확인 시각·해시를 확인합니다. 긴 출력은 화면에서 앞 20,000자만 보여주고 전체는 API에 보관합니다.
6. **취약점 분석**에서 이 기록을 선택해 분석합니다. 완료된 분석에서 AI 설명과 보고서를 만들 수 있습니다.

서버에서 직접 읽었더라도 `origin_status=UNKNOWN`입니다. APT 캐시는 저장소의 현재/캐시 정보이며 실제 설치 출처, 서명과 파일 무결성을 증명하지 않습니다. 같은 버전이라고 해서 공식 Ubuntu 패키지로 간주하거나 안전하다고 확정하지 않습니다.

## 고정 조회와 저장

`backend/collectors/ssh_protocol.py`의 고정 명령 네 개만 실행합니다. 요청의 IP·사용자명·키 이름을 셸 명령에 끼워 넣지 않습니다. 원격 환경 변수는 비우고 고정 PATH·C 로캘을 사용합니다. `/etc/os-release`는 텍스트로 파싱하며 셸에서 source하지 않습니다.

| 명령                                          | 저장 의미                                                           |
| --------------------------------------------- | ------------------------------------------------------------------- |
| `/usr/bin/cat /etc/os-release`                | Ubuntu 식별값과 릴리스                                              |
| `/usr/bin/dpkg --print-architecture`          | OS 기본 아키텍처                                                    |
| `/usr/bin/dpkg-query --show --showformat=...` | 바이너리/소스 이름·버전·아키텍처·설치/오류 상태                     |
| `/usr/bin/apt-cache ... policy ...`           | 고정 Apache2·MySQL 패키지의 캐시 참고 정보; 캐시 쓰기 경로 비활성화 |

SSH 출력은 stdout·stderr 합계 2 MiB, 연결·인증·명령 실행 전체는 기본 45초(5~60초)로 제한합니다. stderr 본문은 저장하지 않고 존재 여부만 남깁니다. 출력 URL의 사용자명·비밀번호 영역은 가린 후 저장하며, 해시는 가린 `CommandResult` JSON들을 줄바꿈으로 연결한 UTF-8 바이트의 SHA-256입니다.

OS 조회 실패·미지원 OS·읽을 수 있는 패키지 없음·접속/인증 오류·출력 한도 초과는 새 인벤토리를 저장하지 않습니다. 일부 패키지 행만 읽으면 `PARTIAL`과 불완전 목록으로 저장합니다. 아키텍처 또는 APT 참고 조회만 실패해도 작업은 `PARTIAL`이지만, dpkg 전체 목록 조회가 성공했다면 인벤토리의 목록 완전성은 유지합니다. 누락 정보·비정상 설치 상태는 별도로 표시합니다.

`ssh_profiles`에는 수정할 때마다 새 연결 설정을 추가합니다. 작업은 요청 당시 설정 ID를 고정합니다. `collection_runs`는 프로필·작업·인벤토리·조회 근거를 연결하고, 인벤토리와 작업 완료 상태를 한 트랜잭션으로 저장합니다. 같은 자산에 동시 수집은 한 건만 허용합니다. 실패 시 이전 인벤토리·분석·보고서는 그대로 유지하며 Worker 재시작 시 중단된 수집을 자동 재실행하지 않습니다.

## API

모든 경로는 `/api/v1` 아래이며 개발용 Bearer 인증이 필요합니다.

| 메서드 | 경로                                  | 동작                                                      |
| ------ | ------------------------------------- | --------------------------------------------------------- |
| GET    | `/collections/settings`               | 허용 대상, 등록 키 이름, 제한 시간; 개인키·키 암호 미반환 |
| GET    | `/assets/{asset_id}/ssh-profile`      | 마지막 저장 설정 또는 `profile: null`                     |
| PUT    | `/assets/{asset_id}/ssh-profile`      | 새 불변 설정 저장; 접속하지 않음                          |
| POST   | `/assets/{asset_id}/collections`      | `{"profile_id":"UUID"}` + `Idempotency-Key`, 202          |
| GET    | `/assets/{asset_id}/collections`      | 이력; `limit` 1~100, `offset` 지원; 큰 근거 출력 제외     |
| GET    | `/assets/{asset_id}/collections/{id}` | 작업·고정 프로필·인벤토리 ID·근거 상세                    |

설정 입력은 `host`, 정수 `port`, `username`, `key_alias`, `host_fingerprint`입니다. `private_key`, `password`, 임의 명령 등의 추가 필드는 거부합니다. 같은 요청 키·프로필의 재요청은 기존 작업을 반환하고 다른 요청과의 키 충돌은 409입니다.

| 작업 오류 코드                                                  | 확인 사항                                    |
| --------------------------------------------------------------- | -------------------------------------------- |
| `SSH_TARGET_NOT_ALLOWED`                                        | API와 Worker의 허용 IP·포트 설정             |
| `SSH_KEY_UNAVAILABLE` / `SSH_KEY_INVALID`                       | 파일·권한·키 형식·암호                       |
| `SSH_HOST_KEY_MISMATCH`                                         | 관리자가 확인한 서버 호스트 키와 입력 지문   |
| `SSH_AUTH_FAILED`                                               | 계정, 해당 계정의 공개키 등록, SSH 접근 허용 |
| `SSH_TIMEOUT` / `SSH_CONNECTION_FAILED` / `SSH_CONNECTION_LOST` | 서버 실행, 네트워크, 포트, 제한 시간         |
| `SSH_OS_UNSUPPORTED` / `SSH_OS_READ_FAILED`                     | Ubuntu 지원 릴리스와 파일 읽기 권한          |
| `SSH_OUTPUT_INVALID` / `SSH_PACKAGE_READ_FAILED`                | 조회 출력 형식·패키지 DB 접근                |
| `SSH_OUTPUT_LIMIT` / `SSH_PACKAGE_LIMIT`                        | 출력 2 MiB·패키지 5,000개 제한               |

## 검증 범위

로컬 임시 SSH 서버와 실제 SSH 프로토콜로 인증·호스트 키 확인·고정 명령·시간/출력 제한을 시험합니다. 서버 응답은 가상 Ubuntu 데이터입니다. API → Worker → SSH → 패키지 저장 → 분석 → 보고서와 이력 보존을 통합 시험합니다. 시험은 임시 DB만 사용하며 실제 학교 API 키·원격 서버에 접근하지 않습니다.

2026-11-10 VirtualBox의 Ubuntu Server 24.04 가상 서버에서 SSH 공개키 인증과 고정 명령 네 개를 실행했습니다. 설치 패키지 674개와 Apache2 패키지 네 개를 읽고 API·Worker·분석·보고서 저장을 확인했습니다. 입력은 가상이 아닌 해당 시험 VM의 실제 패키지 DB입니다. 설치 출처 검증은 수행하지 않아 `UNKNOWN`을 유지합니다. [상세 검증 기록](verification.md).

2026-11-11에는 같은 Ubuntu 24.04 VM에 MySQL을 설치해 Apache·MySQL의 실제 수집·공식 파일 검증·분석·보고서를 확인했습니다. 다른 물리 서버·원격 네트워크, Ubuntu 22.04의 실수집과 실제 공격 가능성의 정확성은 검증하지 않았습니다. 브라우저 제어 도구 초기화 오류로 새 화면의 실제 클릭·레이아웃 검증도 남아 있습니다. TypeScript 검사·웹 빌드와 HTTP/통합 시험을 화면 검증으로 간주하지 않습니다.

구현 참고: [Paramiko SSHClient](https://docs.paramiko.org/en/stable/api/client.html), [SSH 채널 API](https://docs.paramiko.org/en/stable/api/channel.html), [Ubuntu dpkg-query](https://manpages.ubuntu.com/manpages/noble/en/man1/dpkg-query.1.html), [Ubuntu apt-cache](https://manpages.ubuntu.com/manpages/noble/en/man8/apt-cache.8.html).

2026-11-11 수집기 `ubuntu-ssh/1.1`은 APT 참고 조회에 12초 제한을 적용합니다. 필수 패키지 조회가 완전하면 참고 조회 실패와 구분해 보존합니다. 별도 **공식 파일 검증**으로 일치한 패키지의 새로운 인벤토리에 OFFICIAL_MATCH를 부여할 수 있습니다. [검증 사용 방법](package-verification.md), [시연 순서](demo-guide.md).
