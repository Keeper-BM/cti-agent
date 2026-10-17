import { useEffect, useState } from "react";

export const routes = [
  {
    id: "assets",
    title: "자산 현황",
    description: "관리 대상을 등록하고 수집 상태를 확인하세요.",
  },
  {
    id: "findings",
    title: "취약점 분석",
    description: "자산별 영향 판정과 공식 근거를 확인하세요.",
  },
  {
    id: "questions",
    title: "AI 질의응답",
    description: "선택한 자산의 판정 결과와 문서를 바탕으로 질문하세요.",
  },
  {
    id: "reports",
    title: "대응 보고서",
    description: "같은 분석 기준본에 연결된 대응 내용과 출처를 모아 보세요.",
  },
  {
    id: "jobs",
    title: "작업 내역",
    description: "수집·분석 작업의 처리 상태와 실패 사유를 확인하세요.",
  },
  {
    id: "example",
    title: "시험 예제",
    description: "가상 자산의 입력, 기대 판정과 근거 표시를 확인하세요.",
  },
] as const;

export type Route = (typeof routes)[number];

function readRoute(): Route {
  return routes.find((route) => window.location.hash === `#/${route.id}`) ?? routes[0];
}

export function useRoute() {
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const changed = () => setRoute(readRoute());
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  return route;
}
