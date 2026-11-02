import { useEffect, useState } from "react";

export const routes = [
  {
    id: "assets",
    title: "자산 현황",
    description: "관리할 서버를 등록하고 자산 정보를 확인하세요.",
  },
  {
    id: "findings",
    title: "취약점 분석",
    description: "자산별 취약점 판정과 근거를 확인합니다.",
  },
  {
    id: "questions",
    title: "취약점 인사이트",
    description: "자산의 취약점과 대응 방법을 근거와 함께 살펴봅니다.",
  },
  {
    id: "reports",
    title: "대응 보고서",
    description: "취약점 판정과 대응 내용을 보고서로 정리합니다.",
  },
  {
    id: "jobs",
    title: "작업 내역",
    description: "작업의 처리 상태와 오류를 확인하세요.",
  },
  {
    id: "example",
    title: "시험 예제",
    description: "가상 데이터로 취약점 판정과 근거 표시 방식을 살펴보세요.",
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
