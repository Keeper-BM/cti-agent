# 웹 애플리케이션

React, TypeScript, Vite로 구성된 BlendedMeshup 웹 클라이언트입니다. 자산과 작업 화면은 API에 연결되어 있으며 취약점·질의응답·보고서 화면은 기능 상태를 안내하고 시험 예제 화면은 가상 입력·기대 결과와 인용을 표시합니다.

## 실행

저장소 루트에서 실행합니다.

```bash
make dev-ui
```

이 명령은 의존성·설정·DB를 준비하고 API와 웹을 실행합니다. Ctrl+C로 함께 종료합니다. 개발 주소는 `http://localhost:5173`입니다. `/api` 요청은 `127.0.0.1:8000`으로 전달하므로 실행기가 API 프로세스를 준비합니다. 웹만 수동 실행하려면 `npm --prefix frontend run dev`를 사용하고 API를 별도로 실행합니다. 전체 실행 순서는 [프로젝트 README](../README.md)를 참고합니다.

## 화면 경로

| 경로          | 화면        | 현재 동작                                   |
| ------------- | ----------- | ------------------------------------------- |
| `#/assets`    | 자산 현황   | 목록, 등록, 활성 상태 변경, 페이지 조회     |
| `#/jobs`      | 작업 내역   | 최근 작업 조회, Worker 연결 확인            |
| `#/findings`  | 취약점 분석 | 미구현 안내와 결과 표시 영역                |
| `#/questions` | AI 질의응답 | 미구현 안내와 질의·인용 표시 영역           |
| `#/example`   | 시험 예제   | 가상 패키지·기대 판정·근거·입출력 JSON 표시 |
| `#/reports`   | 대응 보고서 | 미구현 안내와 보고서 표시 영역              |

해시 경로는 새로고침과 브라우저 탐색을 지원합니다. 정의되지 않은 경로는 자산 화면으로 표시합니다.

## 소스 구성

| 경로                      | 기능                                     |
| ------------------------- | ---------------------------------------- |
| `src/App.tsx`             | 세션·레이아웃·페이지 조합                |
| `src/app/`                | 탐색, 레이아웃, 메모리 기반 개발 세션    |
| `src/shared/`             | 공통 컴포넌트, 조회·실행 상태, 시각 표시 |
| `src/api/client.ts`       | 인증 헤더, HTTP 요청, 공통 오류 처리     |
| `src/api/schema.d.ts`     | OpenAPI에서 생성한 TypeScript 타입       |
| `src/features/assets/`    | 자산 요청과 화면                         |
| `src/features/jobs/`      | 작업 요청과 화면                         |
| `src/features/findings/`  | 판정 조회 클라이언트와 화면 구조         |
| `src/features/questions/` | 질의 요청 클라이언트와 화면 구조         |
| `src/features/examples/`  | 시험 예제 요청과 화면                    |
| `src/features/reports/`   | 보고서 요청 클라이언트와 화면 구조       |

기능별 요청은 각 폴더의 `api.ts`에 위치합니다. 신규 페이지는 `src/app/navigation.ts`의 경로와 `src/App.tsx`의 페이지 선택에 등록합니다.

## 세션과 조회 상태

개발 토큰으로 `/api/v1/capabilities`를 확인한 후 HTTP 클라이언트를 생성합니다. 토큰은 브라우저 저장소에 기록하지 않으며 새로고침하면 연결 상태가 초기화됩니다.

자산·작업 화면은 요청 완료 후 5초 뒤 다시 조회합니다. 진행 중인 요청은 자동 갱신 때문에 취소되지 않습니다. 수동 갱신은 진행 중 요청 뒤 한 번 더 실행합니다. 시험 예제는 최초 연결과 수동 갱신에만 조회합니다. 공통 훅은 조회 결과·오류·갱신 상태를 관리하고 해제된 화면의 요청을 취소합니다. API 시각은 KST로 표시합니다.

## 명세 갱신과 검사

```bash
uv run python scripts/export_openapi.py
npm --prefix frontend run api:types
npm --prefix frontend run format:check
npm --prefix frontend test
npm --prefix frontend run build
```

`src/api/schema.d.ts`는 생성 파일이며 직접 편집하지 않습니다. 기능 연결 시 서버의 기능 플래그, 메뉴 상태, 실제 요청 처리를 함께 갱신합니다. 미구현 화면은 정상 분석 결과를 생성하거나 표시하지 않습니다.

Node.js 내장 테스트 실행기는 폴링의 느린 응답, 중복 갱신, 해제 시 취소와 오류 복구를 가상 타이머로 검사합니다. 별도 테스트 프레임워크 의존성은 없습니다.
