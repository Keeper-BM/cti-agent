# CTI Agent

Ubuntu 서버의 패키지와 공식 보안 자료를 대조하고, 판단 근거·조치 안내·AI 설명·보고서를 제공하는 프로젝트입니다. Python 3.12, FastAPI, SQLAlchemy, React, TypeScript, Node.js 24를 사용합니다.

## 구현한 기능

- 자산 등록·수정·비활성화, JSON·CSV 입력과 불변 인벤토리 이력
- 허용 IP·호스트 키·고정 읽기 명령을 사용하는 SSH 수집
- Ubuntu 서명 → 패키지 목록 해시 → `.deb` 해시 → 설치 파일 검증
- Ubuntu·NVD·CISA KEV·Apache·Oracle의 공식 자료 수집과 원문·해시 보존
- Ubuntu 패키지 버전 비교, CVSS·KEV, 판단 제한, 근거별 대응 안내
- 같은 보안 자료 기준으로 이전·이후 패키지와 판단 비교
- 한 CVE의 학교 API 설명, 선택한 분석의 근거 검색·질문·인용·답변 이력
- 분석·설명·검증 근거를 고정한 보고서와 Markdown 다운로드
- 계정 로그인, 관리자·담당자·조회자 역할, 자산 접근 권한과 감사 기록
- 단일 Worker, 작업 상태·오류, SQLite 백업·검증·별도 파일 복원

현재 분석 범위는 **Ubuntu 22.04·24.04 / apache2·mysql-8.0 소스 패키지**입니다. 공식 파일 검증은 amd64와 지정된 Apache2·MySQL 바이너리만 지원합니다. 설정 파일과 실행 중인 코드, 과거 설치 경로까지 증명하지 않습니다. 모든 패키지·운영체제·실제 공격 가능성을 포괄하는 제품은 아닙니다. 정확한 실행 결과와 한계는 [검증 기록](docs/verification.md)을 확인하세요.

## 실행

저장소 루트에서 실행합니다.

```bash
python scripts/init_env.py
uv sync --frozen
uv run alembic upgrade head
uv run python -m scripts.manage_users admin
```

마지막 명령에서 초기 관리자 비밀번호를 입력합니다. `.env`의 `AUTH_MODE=accounts`를 지정한 뒤 실행하세요.

```bash
uv run python scripts/dev.py
```

웹은 `http://127.0.0.1:5173`, API 문서는 `http://127.0.0.1:8000/api/docs`입니다. `AUTH_MODE=token`을 선택하면 기존 개발용 토큰 연결도 사용할 수 있습니다. 비밀키는 `.env`와 서버의 키 디렉터리에만 둡니다. [상세 설정](docs/configuration.md), [계정과 복원](docs/operations.md).

Docker가 있는 Linux에서는 `docker compose up --build -d`로 PostgreSQL·API·Worker·웹을 시작합니다. 기본 웹 주소는 `http://127.0.0.1:8080`입니다. SQLite와 Compose 데이터는 서로 독립적입니다. 학교 API나 SSH 설정이 없어도 파일 입력·분석·이력·보고서는 사용할 수 있습니다.

## 시연 순서

1. 로그인 → **자산 현황**에서 서버 선택
2. **서버 패키지 가져오기** 또는 JSON·CSV 입력
3. SSH 기록에서 **공식 파일 검증**, 완료 후 새 패키지 기록 선택
4. **보안 자료**에서 필요한 릴리스·패키지의 자료 수집
5. **취약점 분석** 실행 → 설치 버전·수정 기준·판단 이유·조치 안내 확인
6. 같은 분석의 **전후 비교**, **AI 설명**, **취약점 인사이트**에서 근거 확인
7. **대응 보고서** 생성 → Markdown 다운로드

`FIXED`는 그 CVE의 패키지 수정 조건을 충족했다는 뜻입니다. `NEEDS_REVIEW`는 취약 확정과 다릅니다. JSON·CSV의 출처 주장으로 확정 판정을 만들지 않으며, 자료 부재·부분 수집·설정 미확인을 구분합니다. 학교 API가 실패해도 기존 분석·근거·답변·보고서는 유지합니다.

## 검증 명령

```bash
uv run ruff check backend tests scripts
uv run ruff format --check backend tests scripts
uv run pytest
uv run python -m scripts.export_openapi
npm --prefix frontend run api:types
npm --prefix frontend test
npm --prefix frontend run build
```

`TEST_POSTGRES_URL`이 지정되면 일회용 PostgreSQL 시험도 수행합니다. 실제 운영 DB를 테스트 URL로 지정하지 마세요. 실제 학교 키는 자동 시험에서 사용하지 않습니다.

## 문서

[문서 목록](docs/README.md) · [기능 명세](docs/specification.md) · [아키텍처](docs/architecture.md) · [API](docs/api-contracts.md) · [완료·인수 계획](docs/completion-plan.md)

[파일 입력](docs/inventory-import.md) · [SSH](docs/ssh-collection.md) · [공식 패키지 검증](docs/package-verification.md) · [보안 자료](docs/security-sources.md) · [분석](docs/assessment.md) · [질문·비교](docs/insights-comparisons.md) · [보고서](docs/reports.md)

자동 패치, 설정 변경, 서비스 재시작, 공격·무단 스캔은 애플리케이션 기능에 포함하지 않습니다. 실제 CVE와 별도로 제공하는 **시험 예제**는 가상 자료입니다.
