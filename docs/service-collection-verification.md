# 서비스 상태 수집·SSH 명령 제한 검증

## 구현 범위

`ubuntu-ssh/1.2`는 기존 OS·아키텍처·패키지·APT 조회에 Apache와 MySQL의
고정 `systemctl show` 조회를 추가합니다. 명령당 제한 시간은 5초입니다.
서비스 관찰은 기존 `collection_runs.evidence` JSON에 추가하므로 DB 마이그레이션은 없습니다.
API 스키마와 웹 타입은 생성 도구로 갱신했습니다.

- `OBSERVED`: 로드·활성·세부 상태·활성화 설정을 확인했습니다.
- `NOT_FOUND`: 요청한 systemd 유닛이 없습니다. 패키지 미설치를 뜻하지 않습니다.
- `UNKNOWN`: 명령 실패·제한 시간 초과·명령 거부·잘못된 출력으로 확인하지 못했습니다.

서비스만 확인하지 못한 경우 작업은 `PARTIAL`로 종료하지만 완전하게 읽은 패키지
인벤토리는 그대로 저장합니다. 서비스 상태로 판정 엔진의 취약/안전 결과를 변경하지 않습니다.
기존 근거에 서비스 필드가 없으면 빈 목록으로 읽으며 DB 원본을 수정하지 않습니다.
화면은 활성·중지·서비스 실패·유닛 없음·확인 불가와 과거 기록의 미수집 상태를 구분합니다.

`scripts/render_ssh_guard.py`는 서버 배포용 독립 Python 래퍼를 생성합니다.
Python `-I`, 정확한 명령 일치, 빈 실행 환경, 셸을 거치지 않는 `execve`를 사용합니다.
기본 허용 명령은 6개이며 `--include-file-verification`을 지정하면 기존 번들 파일 검사
프로그램 한 개만 추가합니다. 계정 생성·원격 설치·sudoers 변경은 수행하지 않습니다.
설치 절차와 버전 변경 시 주의점은 [SSH 수집 안내](ssh-collection.md)에 있습니다.

## 자동 검사 — 2026-11-11 KST

- 최종 전체 Python: 실제 Ubuntu 22.04 Apache·MySQL 및 PostgreSQL을 지정해
  **331 passed, 0 skipped**, 45.43초. 아래 초기 검사 후 추가한 Worker 복구 감사와
  실제 프로세스 강제 종료·재시작 시험도 포함합니다.
- 실제 Ubuntu 24.04 VM과 PostgreSQL 17.11·pgvector 0.8.7을 지정한 전체 Python:
  **329 passed, 0 skipped**, 42.14초. 기존 TestClient deprecation 경고 1건.
- 전체 검사 후 테스트 프로세스가 Windows의 기본 환경 변수도 보존하도록 테스트 코드만
  보완했고, 명령 제한 관련 16개 시험을 다시 통과했습니다. Windows 실기동 결과는 아닙니다.
- 서비스 파서·SSH·수집·공식 검증 관련 초기 표적 검사 56개 통과.
- 프론트엔드 자동시험 8개, TypeScript·Vite 빌드, Ruff 검사·포맷, Prettier 검사 통과.

자동 검사는 정상 활성·중지·failed·masked·not-found·전환 상태, 명령 실패·시간 초과,
출력 누락·중복·상충·다른 유닛 응답, 이전 정상 기록 보존, 과거 근거 호환성을 포함합니다.
구버전으로 대기 중인 작업은 원격 명령을 실행하지 않고 `COLLECTOR_CHANGED`로 종료합니다.
명령 제한 시험은 임의 명령·연결 명령·줄바꿈·변경된 서비스 인수·SFTP 거부와
실행 환경 분리, 파일 검사 프로그램의 명시적 허용을 확인합니다.

## 실제 Ubuntu 환경

두 VM 모두 이번 개발 과정에서 만든 arm64 Multipass VM입니다. 기존 사용자 VM이나
운영 DB를 사용하지 않았습니다. 브리지와 호스트 디렉터리 마운트는 없고,
MySQL은 VM의 `127.0.0.1:3306/33060`만 수신합니다.

- Ubuntu 24.04.5: 패키지 691개, MySQL 5개
  `8.0.46-0ubuntu0.24.04.4`. Apache 유닛 부재와 활성 MySQL을 실제 수집했습니다.
- Ubuntu 22.04.5 초기 상태: 패키지 629개, MySQL 5개
  `8.0.46-0ubuntu0.22.04.4`. 같은 인수 시험에서 SSH 수집과 CTI DB 복원을 통과했습니다.
- Ubuntu 22.04.5 최종 상태: Apache `2.4.52-1ubuntu4.26` 패키지 4개를 추가한
  패키지 642개 환경에서 두 서비스의 `active/running`을 실제 수집했습니다.
  Apache 설치 중 자동 시작을 막고 `127.0.0.1:80`으로 제한한 뒤 시작했으며
  루프백 HEAD 요청의 HTTP 200 응답을 확인했습니다.

구형 4개 명령 래퍼에서 새 서비스 조회 두 개가 종료 코드 126으로 거절되는 상황도
실제 확인했습니다. 패키지 전체 목록은 유지되고 서비스는 확인 불가였습니다.
새 생성 도구의 래퍼를 설치한 뒤 같은 VM에서 수집을 통과했습니다.

Ubuntu 22.04에서는 기본 래퍼가 파일 검증 프로그램을 거절하는지 확인한 뒤,
옵션 래퍼를 설치해 정확한 번들 프로그램으로 `/usr/sbin/mysqld`를 읽었습니다.
독립 관리 채널에서 구한 SHA-256과 일치했고 패키지 목록은 읽기 전후 같았습니다.
특권 Apache 관측기는 설치하지 않았으며 결과는 `UNAVAILABLE`입니다.
이 확인은 SSH 명령 제한과 파일 읽기의 통합 검증이며 공식 저장소 서명 대조 결과가 아닙니다.

## HTTP·화면 확인

별도 시험 SQLite DB를 사용해 Vite(15173) → API(18600) → 별도 Worker → 실제 SSH
경로로 수집했습니다. 시험 VM의 MySQL을 관리 채널로 잠시 중지한 뒤 수집하여
`inactive/dead`를 확인했고, 수집 후에도 서비스가 중지 상태였음을 확인했습니다.
검증 스크립트의 `finally`에서 서비스를 다시 시작했습니다.

실제 브라우저에서 토큰 연결, 자산 상세, 수집 이력 선택과 새로고침을 실행했습니다.
Apache ‘서비스 유닛 없음’, MySQL ‘활성’과 과거 수집의 ‘중지’ 표시를 확인했습니다.
좁은 화면에서 결과가 줄바꿈되며 내용을 읽을 수 있었고 관찰된 콘솔 오류·경고는 없습니다.
전체 페이지·브라우저·기기 조합을 검증한 결과는 아닙니다.

## Worker 재시작과 감사 이력

기존 `WORKER_RESTARTED` 처리에 `job.interrupted` 감사 이벤트를 연결했습니다.
작업 실패 처리와 감사 기록은 같은 트랜잭션이며, 이미 처리한 작업은 다시 기록하지 않습니다.
작업 종류·오류 코드·작업/자산/요청자 ID만 저장합니다.

`tests/integration/test_worker_process.py`는 임시 DB·루프백 SSH 서버를 사용해
실제 `python -m backend.worker` 자식 프로세스를 실행합니다. 정상 수집을 먼저 보존한 뒤
느린 수집 중 프로세스를 강제 종료하고 새 Worker를 시작합니다. 중복 Worker 거절,
중단 작업의 실패 처리·감사 이벤트 1건, 정상 스냅샷 불변, 동시 수집 슬롯 해제와
새 요청의 성공을 확인합니다. 원격 출력은 가상 fixture이며 실제 Ubuntu 시험과 구분합니다.
감사 저장 실패 시 작업 상태도 롤백되는 검증을 포함해 관련 5개 시험이 통과했습니다.

## 근거와 보관

Git 제외 디렉터리 `.data/service-acceptance-20261111/`에 다음을 보관합니다.

- `final-suite.xml`, `full-suite.xml`, `noble-active.xml`, `jammy-active.xml`,
  `jammy-apache-mysql.xml`: 시험 결과와 수집 메타데이터.
- `worker-recovery.xml`, `worker-process/`: 프로세스 재시작 검사와 임시 DB·로그.
- `old-wrapper.json`: 구형 명령 제한으로 서비스 확인이 거부된 실제 응답.
- `http-stopped-collection.json`, `ui.db`: 별도 프로세스 HTTP 수집과 과거 이력.
- `guard-default-verifier-denied.json`, `guard-file-verification.json`: 선택적 검증 명령의 거부·허용 근거.
- `services-mobile.jpg`: 실제 중지 상태를 표시한 브라우저 화면.

인증키·내부 IP·원시 응답·DB는 소스 저장소에 포함하지 않습니다.
시험 전용 프로세스와 컨테이너는 결과 저장 후 종료·제거하고, VM은 정지 스냅샷으로 보관합니다.
두 VM의 최신 스냅샷 이름은 `services-baseline`입니다. 24.04의 이전 `mysql-baseline`은
구형 4개 명령 래퍼 상태이므로 서비스 수집 재시험에는 최신 스냅샷을 사용합니다.
