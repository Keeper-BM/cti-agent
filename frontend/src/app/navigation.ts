import { useSyncExternalStore } from "react";

export const routes = [
  {
    id: "workspace",
    title: "분석 실행",
    description:
      "Ubuntu 22.04·24.04의 Apache2와 MySQL을 공식 보안 자료와 대조하고 대응 보고서를 만듭니다.",
  },
  {
    id: "assets",
    title: "자산",
    description: "서버를 등록하고 연결 설정과 패키지 수집 기록을 관리합니다.",
  },
  {
    id: "schedules",
    title: "분석 예약",
    description: "등록한 자산을 정기 분석하고 지난 점검 이후 달라진 판정을 확인합니다.",
  },
  {
    id: "findings",
    title: "분석 이력",
    description: "자산별로 저장된 판정과 당시 사용한 근거를 확인합니다.",
  },
  {
    id: "reports",
    title: "보고서",
    description: "분석별 대응 보고서를 열거나 파일로 내려받습니다.",
  },
  {
    id: "sources",
    title: "보안 자료",
    description: "공식 출처별 수집 범위와 자료 갱신 이력을 확인합니다.",
  },
  {
    id: "questions",
    title: "AI 질문",
    description: "선택한 분석 결과와 공식 근거를 바탕으로 질문합니다.",
  },
  {
    id: "jobs",
    title: "작업 내역",
    description: "수집·분석·생성 작업의 진행 상태와 오류를 확인합니다.",
  },
  {
    id: "example",
    title: "시험 예제",
    description: "가상 입력으로 취약점 판정과 근거를 확인합니다.",
  },
  { id: "accounts", title: "계정·권한", description: "사용자 계정과 자산 접근 권한을 관리합니다." },
  { id: "audit", title: "운영 기록", description: "접근·변경·작업 처리 기록을 확인합니다." },
] as const;

export type Route = (typeof routes)[number];

function subscribe(update: () => void) {
  window.addEventListener("hashchange", update);
  return () => window.removeEventListener("hashchange", update);
}

export function useRoute() {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash);
  const [path, query] = hash.split("?");
  const route = routes.find((item) => path === "#/" + item.id) ?? routes[0];
  return { route, hash, params: new URLSearchParams(query) };
}
