import assert from "node:assert/strict";
import { test } from "node:test";
import { startPolling } from "../src/shared/hooks/polling.ts";

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

test("requests slower than the polling interval finish without being cancelled", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let started = 0;
  let aborted = 0;
  const results: number[] = [];
  const loading: boolean[] = [];
  const polling = startPolling<number>(
    (signal) =>
      new Promise<number>((resolve) => {
        started += 1;
        signal.addEventListener("abort", () => {
          aborted += 1;
        });
        setTimeout(() => resolve(started), 6000);
      }),
    {
      success: (value) => results.push(value),
      error: (cause) => assert.fail(String(cause)),
      loading: (value) => loading.push(value),
    },
  );
  t.after(polling.stop);
  t.mock.timers.tick(5000);
  await flush();
  assert.equal(started, 1);
  assert.deepEqual(results, []);
  t.mock.timers.tick(1000);
  await flush();
  assert.deepEqual(results, [1]);
  assert.deepEqual(loading, [true, false]);
  assert.equal(aborted, 0);
  t.mock.timers.tick(5000);
  await flush();
  assert.equal(started, 2);
  t.mock.timers.tick(6000);
  await flush();
  assert.deepEqual(results, [1, 2]);
  assert.equal(aborted, 0);
});

test("repeated manual refreshes during a request queue one refresh without overlap", async (t) => {
  let complete: (value: number) => void = () => {};
  let started = 0;
  const results: number[] = [];
  const polling = startPolling<number>(
    () => {
      started += 1;
      return new Promise<number>((resolve) => {
        complete = resolve;
      });
    },
    {
      success: (value) => results.push(value),
      error: (cause) => assert.fail(String(cause)),
      loading: () => {},
    },
    null,
  );
  t.after(polling.stop);
  polling.refresh();
  polling.refresh();
  assert.equal(started, 1);
  complete(1);
  await flush();
  assert.equal(started, 2);
  complete(2);
  await flush();
  assert.deepEqual(results, [1, 2]);
  assert.equal(started, 2);
});

test("stop aborts the active request and suppresses late responses and further refreshes", async () => {
  let signal: AbortSignal | undefined;
  let complete: (value: number) => void = () => {};
  const results: number[] = [];
  const polling = startPolling<number>(
    (value) => {
      signal = value;
      return new Promise<number>((resolve) => {
        complete = resolve;
      });
    },
    {
      success: (value) => results.push(value),
      error: (cause) => assert.fail(String(cause)),
      loading: () => {},
    },
  );
  polling.stop();
  assert.equal(signal?.aborted, true);
  polling.refresh();
  complete(1);
  await flush();
  assert.deepEqual(results, []);
});

test("errors clear loading and a later successful poll recovers", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let attempts = 0;
  const errors: unknown[] = [];
  const results: number[] = [];
  const loading: boolean[] = [];
  const polling = startPolling<number>(
    async () => {
      attempts += 1;
      if (attempts === 1) throw new Error("temporary failure");
      return 2;
    },
    {
      success: (value) => results.push(value),
      error: (cause) => errors.push(cause),
      loading: (value) => loading.push(value),
    },
  );
  t.after(polling.stop);
  await flush();
  assert.equal(errors.length, 1);
  assert.deepEqual(loading, [true, false]);
  t.mock.timers.tick(5000);
  await flush();
  assert.deepEqual(results, [2]);
  assert.deepEqual(loading, [true, false, true, false]);
});
