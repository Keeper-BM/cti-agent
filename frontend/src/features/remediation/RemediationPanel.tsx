import type { components } from "../../api/schema";
const priorities: Record<string, string> = {
  ROUTINE: "정기 확인",
  URGENT_REVIEW: "긴급 검토",
  HIGH_REVIEW: "우선 검토",
  REVIEW: "확인 필요",
};
export function RemediationPanel({ value }: { value: components["schemas"]["Remediation"] }) {
  return (
    <section className="collection-result" aria-label="대응 권고">
      <h3>대응 권고 · {priorities[value.priority] ?? value.priority}</h3>
      <p>{value.priority_reason}</p>
      <ol>
        {value.steps.map((step, index) => (
          <li key={index}>
            <strong>{step.title}</strong>
            <p>{step.description}</p>
            {step.evidence_urls.map((url) => (
              <a
                key={url}
                href={/^https?:\/\//.test(url) ? url : undefined}
                target="_blank"
                rel="noreferrer"
              >
                공식 근거 확인{" "}
              </a>
            ))}
          </li>
        ))}
      </ol>
      <ul>
        {value.limitations.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </section>
  );
}
