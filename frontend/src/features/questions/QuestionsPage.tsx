// 선택 자산의 판정과 근거에 기반한 질의응답 화면 구조.
import { FeaturePlaceholder } from "../../shared/components/FeaturePlaceholder";

export function QuestionsPage() {
  return (
    <FeaturePlaceholder
      title="취약점 인사이트"
      description="자산별 판정 결과와 공식 근거를 바탕으로 취약점 정보를 확인할 수 있습니다."
      columns={["선택 자산", "질문 / 답변", "인용 출처", "불확실성 안내"]}
    />
  );
}
