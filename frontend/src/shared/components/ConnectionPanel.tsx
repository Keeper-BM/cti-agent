import { useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "./Notice";

export function ConnectionPanel() {
  const { api, connect, signIn, mode, loading, connectionError } = useSession();
  const [token, setToken] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [username, setUsername] = useState("");
  if (api) return null;
  if (loading || !mode)
    return (
      <section className="connect-panel">
        <p>
          {loading
            ? "연결 방식을 확인하는 중입니다…"
            : "서버 실행 상태를 확인하고 페이지를 새로고침하세요."}
        </p>
        <Notice error={connectionError} />
      </section>
    );
  if (mode === "accounts")
    return (
      <section className="connect-panel" aria-labelledby="login-heading">
        <div className="connect-copy">
          <div>
            <h2 id="login-heading">로그인</h2>
            <p>계정에 부여된 자산 및 분석 권한으로 접속합니다.</p>
          </div>
        </div>
        <form
          className="connect-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setPending(true);
            setError("");
            try {
              await signIn(username.trim(), token);
              setToken("");
            } catch (cause) {
              setError(cause instanceof Error ? cause.message : "로그인에 실패했습니다.");
            } finally {
              setPending(false);
            }
          }}
        >
          <label>
            <span className="sr-only">로그인 이름</span>
            <input
              name="username"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              maxLength={64}
              placeholder="로그인 이름"
              disabled={pending}
            />
          </label>
          <label>
            <span className="sr-only">비밀번호</span>
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
              maxLength={256}
              placeholder="비밀번호"
              disabled={pending}
            />
          </label>
          <button className="primary" disabled={pending}>
            {pending ? "로그인 중…" : "로그인"}
          </button>
        </form>
        <Notice error={error || connectionError} />
      </section>
    );
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
