// 분석 기준본과 인용에 연결된 보고서 화면 구조.
import { FeaturePlaceholder } from "../../shared/components/FeaturePlaceholder";

export function ReportsPage() {
  return (
    <FeaturePlaceholder
      title="대응 보고서"
      description="보고서 기능은 아직 연결되지 않았습니다. 생성 시점의 판정과 출처를 고정해 Markdown으로 제공할 예정입니다."
      columns={["보고서", "분석 기준본", "출처 / 생성 시각", "내려받기"]}
    />
  );
}
