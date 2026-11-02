import { useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "./Notice";

export function ConnectionPanel() {
  const { api, connect } = useSession();
  const [token, setToken] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  if (api) return null;
  return (
    <section className="connect-panel" aria-labelledby="connect-heading">
      <div className="connect-copy">
        <span className="connect-mark" aria-hidden="true">
          ↗
        </span>
        <div>
          <h2 id="connect-heading">서비스 연결</h2>
          <p>.env 파일의 DEV_API_TOKEN을 입력하세요. 토큰은 새로고침하면 삭제됩니다.</p>
        </div>
      </div>
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
          placeholder="개발용 API 토큰"
        />
        <button className="primary" disabled={pending} type="submit">
          {pending ? "연결 중…" : "연결하기"}
        </button>
      </form>
      <Notice error={error} />
    </section>
  );
}
