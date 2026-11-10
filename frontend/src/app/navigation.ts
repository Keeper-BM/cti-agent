import { useEffect, useState } from "react";

export const routes = [
  {
    id: "assets",
    title: "자산 현황",
    description: "서버 자산 등록 및 패키지 수집 관리",
  },
  {
    id: "sources",
    title: "보안 자료",
    description: "공식 CVE 자료 수집 및 출처별 갱신 이력",
  },
  {
    id: "findings",
    title: "취약점 분석",
    description: "자산별 취약점 판정 및 근거 분석",
  },
  {
    id: "questions",
    title: "취약점 인사이트",
    description: "분석 결과·공식 근거 기반 AI 질의응답",
  },
  {
    id: "reports",
    title: "대응 보고서",
    description: "취약점 분석·대응 보고서 생성 및 이력 관리",
  },
  {
    id: "jobs",
    title: "작업 내역",
    description: "수집·분석·생성 작업의 처리 상태 및 오류",
  },
  {
    id: "example",
    title: "시험 예제",
    description: "가상 입력 기반 취약점 판정 및 근거 예제",
  },
  { id: "accounts", title: "계정·권한", description: "사용자 계정 및 자산 접근 권한 관리" },
  { id: "audit", title: "운영 기록", description: "접근·변경·작업 처리 감사 기록" },
] as const;

export type Route = (typeof routes)[number];

function readRoute(): Route {
  return (
    routes.find((route) => window.location.hash.split("?")[0] === `#/${route.id}`) ??
    routes.find((route) => route.id === "assets")!
  );
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
