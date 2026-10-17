// 판정 결과·근거·우선순위 표시를 위한 화면 구조.
import { FeaturePlaceholder } from "../../shared/components/FeaturePlaceholder";

export function FindingsPage() {
  return (
    <FeaturePlaceholder
      title="취약점·대응 결과"
      description="판정 데이터가 아직 연결되지 않았습니다. 영향 여부와 처리하지 못한 상태를 구분해 표시할 예정입니다."
      columns={["자산 / CVE", "설치·수정 버전", "판정 / 이유", "CVSS / KEV", "공식 근거"]}
    />
  );
}
