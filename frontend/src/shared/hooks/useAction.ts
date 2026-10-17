import { useState } from "react";

export function useAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function run(work: () => Promise<unknown>, message: string) {
    setPending(true);
    setError("");
    setNotice("");
    try {
      await work();
      setNotice(message);
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "요청에 실패했습니다.");
      return false;
    } finally {
      setPending(false);
    }
  }
  return { pending, error, notice, run };
}
