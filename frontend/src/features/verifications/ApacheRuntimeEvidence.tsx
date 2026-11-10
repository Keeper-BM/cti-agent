import type { components } from "../../api/schema";
import { formatKst } from "../../shared/format";

export function ApacheRuntimeEvidence({
  evidence,
}: {
  evidence: components["schemas"]["ApacheHTTP2Evidence"];
}) {
  return (
    <section className="ai-original" aria-label="Apache HTTP/2 실행 조건 근거">
      <h3>실행 조건 확인 · Apache HTTP/2</h3>
      <p>
        {formatKst(evidence.observed_at)}에 실행 중인 Apache와 HTTP/2 모듈이 공식 패키지 파일과
        일치했고, VM 내부의 HTTP/2 요청에 정상 응답했습니다.
      </p>
      <dl className="detail-list">
        <div>
          <dt>확인한 응답</dt>
          <dd>
            {evidence.endpoint} · HTTP/{evidence.http_version} · {evidence.http_status}
          </dd>
        </div>
        <div>
          <dt>Apache 프로세스</dt>
          <dd>PID {evidence.main_pid} · 관측 전후 동일</dd>
        </div>
        <div>
          <dt>관측한 소스 버전</dt>
          <dd>{evidence.source_version}</dd>
        </div>
      </dl>
      <p>기록된 시점의 로컬 서비스 조건입니다. 공격 실행이나 외부 노출 검증을 의미하지 않습니다.</p>
      <details>
        <summary>파일과 검증 기록</summary>
        <p className="mono">
          실행 파일 SHA-256 {evidence.executable_sha256}
          <br />
          HTTP/2 모듈 SHA-256 {evidence.module_sha256}
          <br />
          검증 기록 {evidence.verification_id}
        </p>
      </details>
    </section>
  );
}
