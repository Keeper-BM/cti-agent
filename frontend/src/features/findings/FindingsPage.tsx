// 판정 결과·근거·우선순위 표시를 위한 화면 구조.
import { FeaturePlaceholder } from "../../shared/components/FeaturePlaceholder";

export function FindingsPage() {
  return (
    <FeaturePlaceholder
      title="취약점 분석 결과"
      description="자산별 취약점의 영향 여부와 판정 근거를 확인하는 기능입니다."
      columns={["자산과 CVE", "설치 버전과 수정 버전", "판정 및 이유", "공식 근거"]}
    />
  );
}
