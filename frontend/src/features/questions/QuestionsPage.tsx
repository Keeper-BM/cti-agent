// 선택 자산의 판정과 근거에 기반한 질의응답 화면 구조.
import { FeaturePlaceholder } from "../../shared/components/FeaturePlaceholder";

export function QuestionsPage() {
  return (
    <FeaturePlaceholder
      title="근거 기반 질의응답"
      description="자산별 분석 결과, 공식 문서 검색, 모델 연결이 준비되면 질문할 수 있습니다."
      columns={["선택 자산", "질문 / 답변", "인용 출처", "불확실성 안내"]}
    />
  );
}
