// 분석 기준본과 인용에 연결된 보고서 화면 구조.
import { FeaturePlaceholder } from "../../shared/components/FeaturePlaceholder";

export function ReportsPage() {
  return (
    <FeaturePlaceholder
      title="대응 보고서"
      description="자산별 취약점 판정과 대응 정보를 근거와 함께 보고서로 정리하는 기능입니다."
      columns={["분석 대상", "판정 및 대응 내용", "근거 자료", "생성 시각"]}
    />
  );
}
