// 선택 자산의 판정과 근거에 기반한 질의응답 화면 구조.
import { FeaturePlaceholder } from "../../shared/components/FeaturePlaceholder";

export function QuestionsPage() {
  return (
    <FeaturePlaceholder
      title="취약점 인사이트"
      description="자산의 취약점과 대응 방법에 관한 질문에 근거 자료를 바탕으로 답변하는 기능입니다."
      columns={["대상 자산", "질문과 답변", "근거 자료", "확인이 필요한 내용"]}
    />
  );
}
