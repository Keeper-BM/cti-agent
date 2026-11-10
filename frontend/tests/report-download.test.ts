import assert from "node:assert/strict";
import test from "node:test";
import { createHttpClient } from "../src/api/client.ts";

test("Markdown download keeps Korean bytes and sends authentication", async (t) => {
  const original = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = original;
  });
  const document = "# 보고서\n\n추가 확인 필요 · 2.4.52-1ubuntu4.4\n";
  globalThis.fetch = async (input, options) => {
    assert.equal(input, "/api/v1/reports/example/markdown");
    assert.equal((options?.headers as Record<string, string>).Authorization, "Bearer test-only");
    return new Response(document, { headers: { "Content-Type": "text/markdown; charset=utf-8" } });
  };
  assert.equal(await createHttpClient("test-only").text("/reports/example/markdown"), document);
});

test("Failed download surfaces the API error instead of saving JSON as a report", async (t) => {
  const original = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = original;
  });
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ error: { message: "완료된 보고서만 내려받을 수 있습니다." } }), {
      status: 409,
    });
  await assert.rejects(
    () => createHttpClient("test-only").text("/reports/example/markdown"),
    /완료된 보고서/,
  );
});
