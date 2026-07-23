import test from "node:test";
import assert from "node:assert/strict";
import { __test, route } from "../src/index.js";

test("public API health endpoint is CORS-safe for the local dashboard", async () => {
  const request = new Request("http://127.0.0.1:8787/api/health", { headers: { origin: "http://127.0.0.1:8765" } });
  const response = await route(request, { APP_ENV: "local" });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("access-control-allow-origin"), "http://127.0.0.1:8765");
  assert.deepEqual(await response.json(), { ok: true, environment: "local", storage: "D1" });
});

test("sync payload accepts valid aggregate-only XP", () => {
  const parsed = __test.syncPayload("76438f04-e74e-4a24-9f83-63c4d7a999f4", {
    sequence: 1,
    occurred_at: new Date().toISOString(),
    duration_seconds: 10,
    xp: { keyboard: 12, click: 2, cursor: 0, scroll: 1 },
  });
  assert.equal(parsed.error, undefined);
  assert.equal(parsed.value.total, 15);
  assert.match(__test.canonicalSync(parsed.value), /\|12\|2\|0\|1$/);
});

test("sync payload rejects private or impossible data", () => {
  const privatePayload = __test.syncPayload("76438f04-e74e-4a24-9f83-63c4d7a999f4", {
    sequence: 1,
    occurred_at: new Date().toISOString(),
    duration_seconds: 10,
    xp: { keyboard: "typed text", click: 0, cursor: 0, scroll: 0 },
  });
  assert.match(privatePayload.error, /keyboard/);

  const impossible = __test.syncPayload("76438f04-e74e-4a24-9f83-63c4d7a999f4", {
    sequence: 1,
    occurred_at: new Date().toISOString(),
    duration_seconds: 1,
    xp: { keyboard: 10_000, click: 0, cursor: 0, scroll: 0 },
  });
  assert.match(impossible.error, /rate limit/);
});

test("identifiers are strict", () => {
  assert.equal(__test.validUsername("Tanveer_01"), true);
  assert.equal(__test.validUsername("too-long-name-with-hyphen"), false);
  assert.equal(__test.validDeviceId("76438f04-e74e-4a24-9f83-63c4d7a999f4"), true);
  assert.equal(__test.validDeviceId("computer-name-or-hardware-id"), false);
});
