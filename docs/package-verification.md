# 공식 Ubuntu 패키지 파일 검증

SSH 수집 기록을 선택한 뒤 **공식 파일 검증**을 요청합니다. Worker는 동일 서버·호스트 키로 현재 OS·패키지를 다시 확인하고, 공식 배포본의 설치 파일과 SHA-256·메타데이터·심볼릭 링크를 대조합니다. 결과는 새로운 인벤토리와 검증 이력으로 저장합니다.

## 범위와 신뢰 연결

지원 릴리스는 Ubuntu 22.04(jammy)·24.04(noble), OS 아키텍처는 amd64입니다. 검증 대상은 apache2, apache2-bin, apache2-data, apache2-utils, mysql-server, mysql-server-8.0, mysql-server-core-8.0, mysql-client-8.0, mysql-client-core-8.0, libmysqlclient21입니다. 해당 릴리스의 main 저장소에서 **설치된 정확한 버전·아키텍처**를 찾습니다.

1. HTTPS `archive.ubuntu.com/ubuntu`의 security·updates·base InRelease를 가져옵니다.
2. 번들 Ubuntu Archive 2018 공개키 지문 `F6ECB3762474EDA9D21B7022871920D1991BC93C`로 GnuPG 서명을 확인합니다.
3. Release의 릴리스·발행 시각·유효기간(있는 경우)·Packages.xz SHA-256을 검사합니다.
4. 서명된 목록의 `.deb` 크기·SHA-256, 내부 패키지명·소스 대응·전체 버전을 확인합니다.
5. `.deb`를 설치·실행·파일시스템에 풀지 않고 파일 목록·해시를 읽습니다.
6. 고정된 원격 Python 검사기가 허용 경로의 파일을 읽고, 해시·권한·소유자·링크를 비교합니다. 검사 전후 dpkg 목록이 달라지면 실패합니다.

공식 키의 근거는 [Ubuntu archive verification](https://documentation.ubuntu.com/security/software-integrity/archive-verification/)입니다. 신뢰키 교체는 코드·문서 검토가 필요하며 네트워크에서 임의의 키를 받아 신뢰하지 않습니다.

## 결과 해석

| 결과                    | 의미                                                                 |
| ----------------------- | -------------------------------------------------------------------- |
| MATCH                   | 확인한 비설정 파일·메타데이터가 공식 패키지와 일치                   |
| DIFFERENT               | 파일 내용·종류·메타데이터·링크 또는 존재 여부에 차이                 |
| UNAVAILABLE             | 정확한 공식 버전 부재, 읽기 실패 또는 지원하지 않는 파일             |
| CONFIGURATION           | 패키지의 설정 파일. 차이를 표시하되 패키지 일치 판정에서 제외        |
| VERIFICATION_STALE 오류 | 선택 기록과 현재 OS·패키지가 다르거나 검사 중 변경됨. 다시 수집 필요 |

MATCH인 패키지만 새 인벤토리의 `OFFICIAL_MATCH` 출처 상태를 받습니다. 나머지는 UNKNOWN을 유지합니다. 차이는 변조·침해의 확정 증거가 아닙니다. 일치도 서버 전체의 안전, 과거 설치 경로, 실행 중인 코드·커널, 런타임 설정을 증명하지 않습니다. 오래된 패키지가 현재 공식 목록에서 사라졌다면 임의의 미러를 신뢰하지 않고 확인 불가로 표시합니다.

새 검증 인벤토리를 선택해 분석해야 판단에 반영됩니다. 이전 분석·보고서는 바뀌지 않습니다. 새 보고서에는 검증 요약·서명·해시·파일별 확인 근거가 포함됩니다.

## 설정과 제한

백엔드에 GnuPG가 필요합니다. Windows는 PATH, `GPG_BINARY`, Git for Windows의 GnuPG를 지원합니다. Compose 이미지에는 GnuPG를 설치합니다. 일반 파일 검증은 원격 표준 Python 3와 일반 수집 계정으로 수행합니다. 선택적인 Apache 실행 조건 관측은 아래의 고정 명령 한 개에만 제한된 sudo가 필요합니다.

`PACKAGE_CACHE_DIRECTORY`를 여유 있는 드라이브에 설정합니다. 기본 용량 제한은 `PACKAGE_CACHE_MIB=768`이며 캐시가 찼을 때 이력을 자동 삭제하지 않습니다. 캐시를 옮길 때 API·Worker를 중지하고 경로를 바꾸세요. 기존 검증 근거는 DB에 남지만 오래된 패키지의 재검증에는 보관된 파일이 필요할 수 있습니다.

공식 자료 조회 전체 300초, 응답 크기·패키지 수·압축 해제 크기·원격 입력·출력·읽기 크기를 제한합니다. 링크를 따라 임의 파일을 읽지 않으며 설정·패키지를 변경하지 않습니다.

## API

- `POST /api/v1/assets/{asset_id}/verifications`: `{"inventory_id":"UUID"}`, Idempotency-Key 필수, 202
- `GET /api/v1/assets/{asset_id}/verifications`: 이력과 작업 상태
- `GET /api/v1/assets/{asset_id}/verifications/{id}`: 고정된 검증 근거와 새 인벤토리 ID

JSON·CSV·가상 입력으로 검증된 출처를 주장할 수 없습니다. 실제 SSH 수집 또는 그 검증 이력으로 연결되는 기록만 받습니다.

## 선택적 Apache 실행 조건 관측

`ubuntu-files/1.1`은 root 소유이며 배포된 코드 해시와 일치하는 `apache_observer.py`가 있을 때 Apache 프로세스·공식 실행 파일·모듈·루프백 HTTP/2 응답을 추가 관측합니다. 임의의 sudo·셸·URL은 허용하지 않습니다. 관측 결과는 `apache_http2`로 새 인벤토리와 검증 이력에 연결되며, 없으면 null과 확인 불가 안내를 저장합니다. 원본 수집·파일 검증·과거 이력은 계속 사용할 수 있습니다. 보고서 템플릿 `assessment-report/1.1`은 이 근거도 출력합니다. [허용한 사례와 제한](affected-demo.md).
