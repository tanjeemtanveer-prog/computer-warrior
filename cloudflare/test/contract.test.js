import test from "node:test";
import assert from "node:assert/strict";
import { __test, route } from "../src/index.js";

class AuthTestD1 {
  constructor() {
    this.rateLimits = new Map();
    this.sessionWrites = 0;
  }

  prepare(sql) {
    const database = this;
    return {
      bind(...values) {
        return {
          async first() {
            if (sql.includes("FROM auth_rate_limits")) return database.rateLimits.get(values[0]) || null;
            return null;
          },
          async run() {
            if (sql.includes("INSERT INTO auth_rate_limits")) {
              database.rateLimits.set(values[0], {
                window_started_at: values[1], attempt_count: values[2], blocked_until: values[3], updated_at: values[4],
              });
            }
            if (sql.includes("INSERT INTO sessions")) database.sessionWrites += 1;
            return { success: true };
          },
          async all() { return { results: [] }; },
        };
      },
    };
  }

  async batch() { return []; }
}

function betaEnvironment(database) {
  return {
    APP_ENV: "beta",
    INVITE_ONLY: "true",
    AUTH_PEPPER: "p".repeat(32),
    INVITE_CODE: "i".repeat(32),
    DB: database,
  };
}

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

test("private beta helpers require an exact invite and bind session hashes to the secret", async () => {
  assert.equal(__test.isPrivateBeta({ APP_ENV: "beta" }), true);
  assert.equal(__test.inviteOnly({ INVITE_ONLY: "true" }), true);
  assert.equal(__test.constantTimeEqual("correct-invite-code", "correct-invite-code"), true);
  assert.equal(__test.constantTimeEqual("correct-invite-code", "wrong-invite-code"), false);
  assert.equal(__test.constantTimeEqual("correct-invite-code", "correct-invite-code-extra"), false);
  const token = "a".repeat(40);
  const first = await __test.sessionTokenHash(token, { APP_ENV: "beta", AUTH_PEPPER: "a".repeat(32) });
  const second = await __test.sessionTokenHash(token, { APP_ENV: "beta", AUTH_PEPPER: "b".repeat(32) });
  assert.notEqual(first, second);
});

test("private beta registration rejects a missing invite and creates a session with the exact invite", async () => {
  const database = new AuthTestD1();
  const endpoint = "https://computer-warrior-beta.example/api/auth/register";
  const missingInvite = await route(new Request(endpoint, {
    method: "POST", headers: { "content-type": "application/json", "CF-Connecting-IP": "203.0.113.10" },
    body: JSON.stringify({ username: "beta_user", password: "correct horse battery staple" }),
  }), betaEnvironment(database));
  assert.equal(missingInvite.status, 403);
  assert.equal((await missingInvite.json()).error.code, "invite_required");

  const accepted = await route(new Request(endpoint, {
    method: "POST", headers: { "content-type": "application/json", "CF-Connecting-IP": "203.0.113.11" },
    body: JSON.stringify({ username: "beta_user", password: "correct horse battery staple", invite_code: "i".repeat(32) }),
  }), betaEnvironment(database));
  assert.equal(accepted.status, 201);
  assert.equal(database.sessionWrites, 1);
});

test("private beta blocks repeated account attempts from one address", async () => {
  const database = new AuthTestD1();
  const endpoint = "https://computer-warrior-beta.example/api/auth/register";
  let response;
  for (let attempt = 0; attempt < 9; attempt += 1) {
    response = await route(new Request(endpoint, {
      method: "POST", headers: { "content-type": "application/json", "CF-Connecting-IP": "203.0.113.12" },
      body: JSON.stringify({ username: "x", password: "too-short" }),
    }), betaEnvironment(database));
  }
  assert.equal(response.status, 429);
  assert.equal((await response.json()).error.code, "auth_rate_limited");
});
