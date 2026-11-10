import assert from "node:assert/strict";
import test from "node:test";
import { MAX_INVENTORY_BYTES, readInventoryFile } from "../src/features/inventories/file.ts";

test("UTF-8 BOM input keeps JSON and Korean text intact", async () => {
  const text = '{"origin":"사용자 입력"}';
  const file = new File([new Uint8Array([0xef, 0xbb, 0xbf]), text], "input.JSON");
  assert.equal(await readInventoryFile(file), text);
});

test("invalid, oversized, and non-UTF-8 files are rejected before upload", async () => {
  await assert.rejects(readInventoryFile(new File(["{}"], "input.txt")), /\.json/);
  await assert.rejects(readInventoryFile(new File(["{broken"], "input.json")), /JSON 문법/);
  await assert.rejects(readInventoryFile(new File(["[]"], "input.json")), /JSON 문법/);
  await assert.rejects(
    readInventoryFile(new File([new Uint8Array([0xff])], "input.json")),
    /UTF-8/,
  );
  await assert.rejects(
    readInventoryFile(new File([new Uint8Array(MAX_INVENTORY_BYTES + 1)], "big.json")),
    /2 MiB/,
  );
});
