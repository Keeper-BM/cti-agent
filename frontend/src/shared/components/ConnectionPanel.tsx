import { useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "./Notice";

export function ConnectionPanel() {
  const { api, connect, disconnect } = useSession();
  const [token, setToken] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  if (api)
    return (
      <div className="session-row">
        <span>모든 시각은 KST 기준입니다. 자산·작업 목록은 자동 갱신됩니다.</span>
        <button className="text-button" onClick={disconnect}>
          연결 해제
        </button>
      </div>
    );
  return (
    <section className="panel connect-panel" aria-labelledby="connect-heading">
      <h2 id="connect-heading">개발 환경 연결</h2>
      <p>로컬 .env 파일의 DEV_API_TOKEN을 입력하세요. 토큰은 현재 탭의 메모리에만 보관됩니다.</p>
      <form
        className="connect-form"
        onSubmit={async (event) => {
          event.preventDefault();
          setPending(true);
          setError("");
          try {
            await connect(token.trim());
            setToken("");
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : "연결에 실패했습니다.");
          } finally {
            setPending(false);
          }
        }}
      >
        <label className="sr-only" htmlFor="token">
          개발용 API 토큰
        </label>
        <input
          id="token"
          type="password"
          autoComplete="off"
          required
          minLength={32}
          value={token}
          disabled={pending}
          onChange={(event) => setToken(event.target.value)}
          placeholder="DEV_API_TOKEN"
        />
        <button className="primary" disabled={pending} type="submit">
          {pending ? "연결 중…" : "연결하기 →"}
        </button>
      </form>
      <Notice error={error} />
    </section>
  );
}
