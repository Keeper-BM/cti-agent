# MySQL 기준 미달·수정 버전 비교 시험

## 비교 기준

Ubuntu 24.04의 `mysql-8.0`과 CVE-2024-20994를 사용합니다.
[Ubuntu 공식 CVE 페이지](https://ubuntu.com/security/CVE-2024-20994)의 수정 기준은
`8.0.37-0ubuntu0.24.04.1`입니다. 시험 버전은 기준 미달 `8.0.36-2ubuntu3`와
수정 기준 이상 `8.0.46-0ubuntu0.24.04.5`입니다. 버전은 재실행 시 `apt-cache policy`로
가용성을 확인합니다. 지정 버전이 없으면 중단하며 다른 버전으로 자동 대체하지 않습니다.
현재 저장소의 패키지가 미래에도 제공됨을 보장하지 않으므로 스냅샷과 `.deb`를 보관합니다.

실제 공격을 재현하거나 모든 MySQL CVE에 대한 안전을 인증하는 시험은 아닙니다.
수집·버전 전후 비교·업그레이드 데이터 보존·VM 복원을 확인합니다. SSH 패키지 관찰은
`origin_status=UNKNOWN`이며 `BELOW_FIX`에서 `MEETS_FIX`로 바뀌어도 최종 판정은
`NEEDS_REVIEW`입니다. 공식 파일 검증의 기존 amd64 제한과 판정 엔진은 변경하지 않습니다.

## 전용 VM 준비

새 Ubuntu 24.04 VM을 만듭니다. 기존 운영 VM이나 MySQL 데이터 디렉터리에 적용하지 않습니다.
예시 이름은 이번 시험에 사용한 이름이며 이미 존재하면 재사용하지 말고 새 이름을 지정합니다.

```bash
multipass launch 24.04 --name cti-mysql-pair-20261112 --cpus 2 --memory 3G --disk 14G
multipass transfer infra/mysql-version-lab.sh cti-mysql-pair-20261112:/home/ubuntu/mysql-version-lab.sh
multipass exec cti-mysql-pair-20261112 -- sudo bash /home/ubuntu/mysql-version-lab.sh baseline 8.0.36-2ubuntu3
```

`baseline`은 기존 MySQL과 설치 정책 파일이 없는 새 VM만 허용합니다. APT 자동 갱신 타이머를
중지하고 MySQL 패키지 5종을 지정 버전으로 설치합니다. 설치 중 자동 서비스 시작을 막고
`3306/33060`을 `127.0.0.1`에 바인딩한 뒤 시작합니다. `cti_lab.restore_probe`에 고정
검증 행을 만듭니다. 브리지 네트워크와 호스트 디렉터리 마운트는 사용하지 않습니다.
호스트와 VM 사이의 수집 연결은 명시한 SSH 대상만 허용합니다.

[SSH 수집 안내](ssh-collection.md)에 따라 전용 무 sudo 계정, root 소유 강제 명령 래퍼,
`restrict` 공개키, 관리 채널로 확인한 호스트 키 지문을 준비합니다. API·Worker 양쪽에
동일한 허용 IP:포트와 읽기 전용 키 디렉터리를 설정하고 시험 Compose를 기동합니다.
프로필 JSON은 `host`, `port`, `username`, `key_alias`, `host_fingerprint` 형식입니다.
비밀키·토큰·프로필·DB 덤프는 Git에 추가하지 않습니다.

## 수집·업그레이드·복원 순서

HTTP 시험기는 `.env` 또는 환경 변수의 `DEV_API_TOKEN`을 사용합니다. 토큰을 CLI 인수로
전달하지 않습니다. 별도 env 파일로 Compose를 띄웠다면 로컬 Python 실행에도 같은 토큰을
보호된 실행 환경으로 전달합니다. 기본 URL은 `http://127.0.0.1:8080`이고 `--base-url`로 변경합니다.
모든 evidence 경로는 새 파일이어야 합니다.

```bash
uv run python -m scripts.smoke_mysql_pair baseline \
  --profile .data/mysql-pair/profile.json --evidence .data/mysql-pair/baseline.json
multipass stop cti-mysql-pair-20261112
multipass snapshot cti-mysql-pair-20261112 --name mysql-before-fix
multipass start cti-mysql-pair-20261112
multipass exec cti-mysql-pair-20261112 -- sudo bash /home/ubuntu/mysql-version-lab.sh upgrade 8.0.46-0ubuntu0.24.04.5
uv run python -m scripts.smoke_mysql_pair upgraded \
  --profile .data/mysql-pair/profile.json --baseline .data/mysql-pair/baseline.json \
  --evidence .data/mysql-pair/upgraded.json
multipass stop cti-mysql-pair-20261112
multipass snapshot cti-mysql-pair-20261112 --name mysql-fixed
multipass restore -d cti-mysql-pair-20261112.mysql-before-fix
multipass start cti-mysql-pair-20261112
uv run python -m scripts.smoke_mysql_pair restored \
  --profile .data/mysql-pair/profile.json --baseline .data/mysql-pair/baseline.json \
  --evidence .data/mysql-pair/restored.json
```

VM 스냅샷 복원은 해당 VM의 이후 변경을 버립니다. **이번 시험에서 만든 전용 VM에만**
실행하며 패키지 다운그레이드로 데이터 디렉터리를 재사용하지 않습니다. 복원 후 SSH IP가
바뀌면 관리 채널로 확인해 API·Worker 허용 대상과 프로필을 갱신합니다. 지문을 자동 수락하지 않습니다.
`SELECT id,payload FROM cti_lab.restore_probe ORDER BY id`의 결과를 기준 기록과 대조하고
MySQL 실제 서버 버전·수신 주소도 확인합니다. 마친 뒤 정지하고 `mysql-fixed` 스냅샷으로
원복하여 정지 상태로 보관합니다.

기준 단계는 실제 Ubuntu 자료를 `/sources/ubuntu/sync`로 가져와 분석합니다. 수정 단계는
같은 자산에 새 수집을 만들고 기존 비교 API에 기준 분석을 지정합니다. 따라서 두 입력은
같은 자료 기준본으로 비교되며, 이전 수집·인벤토리 응답이 바뀌지 않았는지도 확인합니다.
복원 단계에서는 같은 CVE가 다시 `BELOW_FIX`이며 패키지 내용이 기준 상태와 일치해야 합니다.
수집별 패키지 ID·근거 ID·수집 시각이 새로 생기는 것은 정상입니다. 복원 비교는 이 ID를 제외한
패키지 버전·아키텍처·설치 상태·출처 상태 등 실제 관측 필드를 대조합니다.

## 보관 항목

VM의 `/var/lib/cti-mysql-lab/{baseline,upgrade}/`에 패키지 5종 `.deb`와 SHA256SUMS,
APT policy·sources·InRelease, OS·아키텍처·패키지 버전·서버 버전·수신 주소·검증 행을 저장합니다.
이 파일들과 VM 스냅샷은 로컬 시험 근거이며 SSH 수집기의 공식 출처 검증 결과로 승격하지 않습니다.
설치 실패 시 낮은 버전 설치를 자동 재시도하지 말고 새 VM에서 시작하거나 관리자가 원인을 확인합니다.
원격 관리자 작업과 읽기 전용 수집 작업은 별개입니다.

CTI PostgreSQL의 수집·자료·분석·비교 이력은
[검증된 PostgreSQL 백업 도구](postgres-backup.md)로 따로 보관합니다.
VM 스냅샷은 CTI DB 백업을 대체하지 않습니다.
