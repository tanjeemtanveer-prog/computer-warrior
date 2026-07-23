const encoder = new TextEncoder();
const LOCAL_PASSWORD_ITERATIONS = 100_000;
const BETA_PASSWORD_ITERATIONS = 310_000;
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;
const AUTH_WINDOW_MS = 15 * 60 * 1000;
const AUTH_MAX_ATTEMPTS = 8;
const AUTH_BLOCK_MS = 15 * 60 * 1000;
const ALLOWED_LOCAL_ORIGINS = new Set([
  "http://127.0.0.1:8765",
  "http://localhost:8765",
  "http://127.0.0.1:8787",
  "http://localhost:8787",
]);

function now() {
  return new Date().toISOString();
}

function isPrivateBeta(env) {
  return env?.APP_ENV === "beta";
}

function inviteOnly(env) {
  return env?.INVITE_ONLY === "true";
}

function passwordIterations(env) {
  return isPrivateBeta(env) ? BETA_PASSWORD_ITERATIONS : LOCAL_PASSWORD_ITERATIONS;
}

function requiredSecret(env, name) {
  const value = env?.[name];
  if (typeof value === "string" && value.length >= 32) return value;
  if (isPrivateBeta(env)) throw new Error(`Missing required Worker secret: ${name}`);
  return "";
}

function constantTimeEqual(left, right) {
  if (typeof left !== "string" || typeof right !== "string") return false;
  const length = Math.max(left.length, right.length, 1);
  let difference = left.length ^ right.length;
  for (let index = 0; index < length; index += 1) {
    difference |= (left.charCodeAt(index % left.length) || 0) ^ (right.charCodeAt(index % right.length) || 0);
  }
  return difference === 0;
}

function json(data, status = 200, request, env) {
  const headers = new Headers({
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  const origin = request?.headers.get("origin");
  const allowed = origin && (ALLOWED_LOCAL_ORIGINS.has(origin) || origin === env?.APP_ORIGIN);
  if (allowed) {
    headers.set("access-control-allow-origin", origin);
    headers.set("access-control-allow-headers", "authorization, content-type");
    headers.set("access-control-allow-methods", "GET, POST, OPTIONS");
    headers.set("vary", "Origin");
  }
  return new Response(JSON.stringify(data), { status, headers });
}

function error(message, status, request, env, code = "request_failed") {
  return json({ error: { code, message } }, status, request, env);
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

async function body(request) {
  const contentType = request.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) throw new Error("JSON body required");
  return asObject(await request.json()) || {};
}

function base64(bytes) {
  let output = "";
  for (const value of bytes) output += String.fromCharCode(value);
  return btoa(output);
}

function randomToken(byteLength = 32) {
  const bytes = crypto.getRandomValues(new Uint8Array(byteLength));
  return base64(bytes).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function passwordHash(password, saltBase64, env) {
  const salt = Uint8Array.from(atob(saltBase64), (char) => char.charCodeAt(0));
  const pepper = requiredSecret(env, "AUTH_PEPPER");
  const material = await crypto.subtle.importKey("raw", encoder.encode(pepper ? `${password}\u0000${pepper}` : password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: passwordIterations(env) },
    material,
    256,
  );
  return base64(new Uint8Array(bits));
}

async function sessionTokenHash(token, env) {
  const pepper = requiredSecret(env, "AUTH_PEPPER");
  return pepper ? sha256(`session-v1:${pepper}:${token}`) : sha256(token);
}

async function throttleAuth(request, env, operation) {
  if (!isPrivateBeta(env)) return null;
  const ip = request.headers.get("CF-Connecting-IP") || request.headers.get("x-forwarded-for") || "unknown";
  const bucket = await sha256(`auth-v1:${requiredSecret(env, "AUTH_PEPPER")}:${operation}:${ip}`);
  const timestamp = Date.now();
  const existing = await env.DB.prepare(
    "SELECT window_started_at, attempt_count, blocked_until FROM auth_rate_limits WHERE bucket = ?",
  ).bind(bucket).first();
  if (existing && Number(existing.blocked_until) > timestamp) {
    return Math.ceil((Number(existing.blocked_until) - timestamp) / 1000);
  }
  const newWindow = !existing || timestamp - Number(existing.window_started_at) >= AUTH_WINDOW_MS;
  const attempts = newWindow ? 1 : Number(existing.attempt_count) + 1;
  const blockedUntil = attempts > AUTH_MAX_ATTEMPTS ? timestamp + AUTH_BLOCK_MS : 0;
  await env.DB.prepare(
    "INSERT INTO auth_rate_limits (bucket, window_started_at, attempt_count, blocked_until, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(bucket) DO UPDATE SET window_started_at = excluded.window_started_at, attempt_count = excluded.attempt_count, blocked_until = excluded.blocked_until, updated_at = excluded.updated_at",
  ).bind(bucket, newWindow ? timestamp : Number(existing.window_started_at), attempts, blockedUntil, timestamp).run();
  return blockedUntil ? Math.ceil(AUTH_BLOCK_MS / 1000) : null;
}

function validUsername(value) {
  return typeof value === "string" && /^[A-Za-z0-9_]{3,24}$/.test(value);
}

function validDeviceId(value) {
  return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function safeLabel(value) {
  if (typeof value !== "string") return null;
  const label = value.trim().replace(/\s+/g, " ");
  return label.length >= 2 && label.length <= 40 ? label : null;
}

function toPositiveInt(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function syncPayload(deviceId, payload) {
  const xp = asObject(payload.xp);
  const sequence = payload.sequence;
  const duration = payload.duration_seconds;
  if (!validDeviceId(deviceId)) return { error: "device_id must be a UUID" };
  if (!Number.isSafeInteger(sequence) || sequence <= 0) return { error: "sequence must be a positive integer" };
  if (!Number.isSafeInteger(duration) || duration < 1 || duration > 3600) return { error: "duration_seconds must be between 1 and 3600" };
  if (typeof payload.occurred_at !== "string" || Number.isNaN(Date.parse(payload.occurred_at))) return { error: "occurred_at must be an ISO timestamp" };
  if (!xp) return { error: "xp object is required" };

  const metrics = {};
  for (const name of ["keyboard", "click", "cursor", "scroll"]) {
    const value = toPositiveInt(xp[name]);
    if (value === null) return { error: `xp.${name} must be a non-negative integer` };
    metrics[name] = value;
  }
  const limits = {
    keyboard: duration * 35 + 60,
    click: duration * 50 + 100,
    cursor: duration * 20 + 50,
    scroll: duration * 20 + 50,
  };
  for (const [metric, maximum] of Object.entries(limits)) {
    if (metrics[metric] > maximum) return { error: `xp.${metric} exceeds the verified rate limit` };
  }
  const occurredAt = new Date(payload.occurred_at);
  const age = Date.now() - occurredAt.getTime();
  if (age > 1000 * 60 * 60 * 24 * 31 || age < -1000 * 60 * 10) return { error: "occurred_at is outside the accepted sync window" };
  const total = metrics.keyboard + metrics.click + metrics.cursor + metrics.scroll;
  return { value: { deviceId, sequence, duration, occurredAt: occurredAt.toISOString(), metrics, total } };
}

function canonicalSync(value) {
  return [
    value.deviceId, value.sequence, value.occurredAt, value.duration,
    value.metrics.keyboard, value.metrics.click, value.metrics.cursor, value.metrics.scroll,
  ].join("|");
}

async function accountFromRequest(request, env) {
  const header = request.headers.get("authorization") || "";
  const match = /^Bearer ([A-Za-z0-9_-]{30,})$/.exec(header);
  if (!match) return null;
  const tokenHash = await sessionTokenHash(match[1], env);
  const result = await env.DB.prepare(
    "SELECT a.id, a.username FROM sessions s JOIN accounts a ON a.id = s.account_id WHERE s.token_hash = ? AND s.expires_at > ?",
  ).bind(tokenHash, now()).first();
  return result || null;
}

async function accountSummary(env, accountId) {
  const total = await env.DB.prepare(
    "SELECT keyboard_xp, click_xp, cursor_xp, scroll_xp, verified_total, updated_at FROM account_totals WHERE account_id = ?",
  ).bind(accountId).first();
  return total || { keyboard_xp: 0, click_xp: 0, cursor_xp: 0, scroll_xp: 0, verified_total: 0, updated_at: null };
}

async function register(request, env) {
  const payload = await body(request);
  const retryAfter = await throttleAuth(request, env, "register");
  if (retryAfter) return error(`Too many account attempts. Try again in ${retryAfter} seconds`, 429, request, env, "auth_rate_limited");
  if (!validUsername(payload.username)) return error("Username must contain 3–24 letters, numbers, or underscores", 400, request, env, "invalid_username");
  if (typeof payload.password !== "string" || payload.password.length < 10 || payload.password.length > 256) return error("Password must be 10–256 characters", 400, request, env, "invalid_password");
  if (inviteOnly(env)) {
    const inviteCode = typeof payload.invite_code === "string" ? payload.invite_code.trim() : "";
    if (!constantTimeEqual(inviteCode, requiredSecret(env, "INVITE_CODE"))) {
      return error("A valid beta invite code is required", 403, request, env, "invite_required");
    }
  }
  const salt = base64(crypto.getRandomValues(new Uint8Array(16)));
  const hash = await passwordHash(payload.password, salt, env);
  const accountId = crypto.randomUUID();
  const createdAt = now();
  try {
    await env.DB.batch([
      env.DB.prepare("INSERT INTO accounts (id, username, password_salt, password_hash, created_at) VALUES (?, ?, ?, ?, ?)").bind(accountId, payload.username.trim(), salt, hash, createdAt),
      env.DB.prepare("INSERT INTO account_totals (account_id, updated_at) VALUES (?, ?)").bind(accountId, createdAt),
    ]);
  } catch (cause) {
    if (String(cause).includes("UNIQUE")) return error("Username is already taken", 409, request, env, "username_taken");
    throw cause;
  }
  return createSession(request, env, accountId, payload.username.trim(), 201);
}

async function createSession(request, env, accountId, username, status = 200) {
  const token = randomToken();
  const createdAt = now();
  const expiresAt = new Date(Date.now() + SESSION_TTL_SECONDS * 1000).toISOString();
  await env.DB.prepare("INSERT INTO sessions (token_hash, account_id, expires_at, created_at) VALUES (?, ?, ?, ?)")
    .bind(await sessionTokenHash(token, env), accountId, expiresAt, createdAt).run();
  return json({ token, expires_at: expiresAt, account: { id: accountId, username } }, status, request, env);
}

async function login(request, env) {
  const payload = await body(request);
  const retryAfter = await throttleAuth(request, env, "login");
  if (retryAfter) return error(`Too many sign-in attempts. Try again in ${retryAfter} seconds`, 429, request, env, "auth_rate_limited");
  if (typeof payload.username !== "string" || typeof payload.password !== "string") return error("Username and password are required", 400, request, env, "invalid_credentials");
  const account = await env.DB.prepare("SELECT id, username, password_salt, password_hash FROM accounts WHERE username = ?")
    .bind(payload.username.trim()).first();
  if (!account || await passwordHash(payload.password, account.password_salt, env) !== account.password_hash) return error("Invalid username or password", 401, request, env, "invalid_credentials");
  return createSession(request, env, account.id, account.username);
}

async function createDevice(request, env, account) {
  const payload = await body(request);
  if (!validDeviceId(payload.device_id)) return error("device_id must be a UUID", 400, request, env, "invalid_device_id");
  const label = safeLabel(payload.label);
  if (!label) return error("Device label must be 2–40 characters", 400, request, env, "invalid_device_label");
  const existing = await env.DB.prepare("SELECT account_id, id, label, last_sequence, verified_total, last_seen_at FROM devices WHERE id = ?").bind(payload.device_id).first();
  if (existing && existing.account_id !== account.id) return error("This device belongs to another account", 409, request, env, "device_claimed");
  const timestamp = now();
  if (existing) {
    await env.DB.prepare("UPDATE devices SET label = ?, last_seen_at = ? WHERE id = ?").bind(label, timestamp, payload.device_id).run();
  } else {
    await env.DB.prepare("INSERT INTO devices (id, account_id, label, public_key, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?)")
      .bind(payload.device_id, account.id, label, typeof payload.public_key === "string" ? payload.public_key.slice(0, 4096) : null, timestamp, timestamp).run();
  }
  const device = await env.DB.prepare("SELECT id, label, last_sequence, verified_total, created_at, last_seen_at FROM devices WHERE id = ?").bind(payload.device_id).first();
  return json({ device }, 201, request, env);
}

async function listDevices(request, env, account) {
  const { results } = await env.DB.prepare("SELECT id, label, last_sequence, verified_total, created_at, last_seen_at FROM devices WHERE account_id = ? ORDER BY last_seen_at DESC").bind(account.id).all();
  return json({ devices: results }, 200, request, env);
}

async function sync(request, env, account) {
  const payload = await body(request);
  const parsed = syncPayload(payload.device_id, payload);
  if (parsed.error) return error(parsed.error, 400, request, env, "invalid_sync");
  const item = parsed.value;
  const device = await env.DB.prepare("SELECT id, account_id, last_sequence FROM devices WHERE id = ?").bind(item.deviceId).first();
  if (!device || device.account_id !== account.id) return error("Register this device to your account first", 403, request, env, "unknown_device");
  const payloadHash = await sha256(canonicalSync(item));
  const duplicate = await env.DB.prepare("SELECT payload_hash, total_xp, status FROM sync_entries WHERE device_id = ? AND sequence = ?").bind(item.deviceId, item.sequence).first();
  if (duplicate) {
    if (duplicate.payload_hash !== payloadHash) return error("This sequence was already used with different data", 409, request, env, "sequence_conflict");
    return json({ accepted: true, idempotent: true, entry: { sequence: item.sequence, total_xp: duplicate.total_xp, status: duplicate.status }, totals: await accountSummary(env, account.id) }, 200, request, env);
  }
  if (item.sequence !== Number(device.last_sequence) + 1) return error(`Expected sequence ${Number(device.last_sequence) + 1}`, 409, request, env, "sequence_out_of_order");
  const receivedAt = now();
  const dayUtc = item.occurredAt.slice(0, 10);
  await env.DB.batch([
    env.DB.prepare("INSERT INTO sync_entries (device_id, sequence, account_id, occurred_at, received_at, duration_seconds, keyboard_xp, click_xp, cursor_xp, scroll_xp, total_xp, payload_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(item.deviceId, item.sequence, account.id, item.occurredAt, receivedAt, item.duration, item.metrics.keyboard, item.metrics.click, item.metrics.cursor, item.metrics.scroll, item.total, payloadHash),
    env.DB.prepare("UPDATE devices SET last_sequence = ?, verified_total = verified_total + ?, last_seen_at = ? WHERE id = ? AND account_id = ?")
      .bind(item.sequence, item.total, receivedAt, item.deviceId, account.id),
    env.DB.prepare("UPDATE account_totals SET keyboard_xp = keyboard_xp + ?, click_xp = click_xp + ?, cursor_xp = cursor_xp + ?, scroll_xp = scroll_xp + ?, verified_total = verified_total + ?, updated_at = ? WHERE account_id = ?")
      .bind(item.metrics.keyboard, item.metrics.click, item.metrics.cursor, item.metrics.scroll, item.total, receivedAt, account.id),
    env.DB.prepare("INSERT INTO account_daily_totals (account_id, day_utc, verified_total, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(account_id, day_utc) DO UPDATE SET verified_total = verified_total + excluded.verified_total, updated_at = excluded.updated_at")
      .bind(account.id, dayUtc, item.total, receivedAt),
  ]);
  return json({ accepted: true, idempotent: false, entry: { sequence: item.sequence, total_xp: item.total, status: "verified" }, totals: await accountSummary(env, account.id) }, 201, request, env);
}

async function leaderboard(request, env) {
  const period = new URL(request.url).searchParams.get("period") || "lifetime";
  let results;
  if (period === "lifetime") {
    ({ results } = await env.DB.prepare("SELECT a.username, t.verified_total FROM account_totals t JOIN accounts a ON a.id = t.account_id WHERE t.verified_total > 0 ORDER BY t.verified_total DESC, a.username ASC LIMIT 100").all());
  } else if (period === "daily") {
    const day = new URL(request.url).searchParams.get("day") || new Date().toISOString().slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return error("day must be YYYY-MM-DD", 400, request, env, "invalid_day");
    ({ results } = await env.DB.prepare("SELECT a.username, d.verified_total FROM account_daily_totals d JOIN accounts a ON a.id = d.account_id WHERE d.day_utc = ? AND d.verified_total > 0 ORDER BY d.verified_total DESC, a.username ASC LIMIT 100").bind(day).all());
  } else {
    return error("period must be lifetime or daily", 400, request, env, "invalid_period");
  }
  return json({ period, leaderboard: results.map((row, index) => ({ rank: index + 1, username: row.username, verified_total: row.verified_total })) }, 200, request, env);
}

async function route(request, env) {
  if (request.method === "OPTIONS") return json({ ok: true }, 204, request, env);
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/") return json({ name: "Computer Warrior API", storage: "D1", endpoints: ["/api/health", "/api/auth/register", "/api/auth/login", "/api/leaderboard"] }, 200, request, env);
  if (request.method === "GET" && url.pathname === "/api/health") return json({ ok: true, environment: env.APP_ENV || "unknown", storage: "D1" }, 200, request, env);
  if (request.method === "POST" && url.pathname === "/api/auth/register") return register(request, env);
  if (request.method === "POST" && url.pathname === "/api/auth/login") return login(request, env);
  if (request.method === "GET" && url.pathname === "/api/leaderboard") return leaderboard(request, env);
  const account = await accountFromRequest(request, env);
  if (!account) return error("Sign in is required", 401, request, env, "unauthorized");
  if (request.method === "POST" && url.pathname === "/api/auth/logout") {
    const token = request.headers.get("authorization").slice(7);
    await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?").bind(await sessionTokenHash(token, env)).run();
    return json({ ok: true }, 200, request, env);
  }
  if (request.method === "GET" && url.pathname === "/api/me") return json({ account, totals: await accountSummary(env, account.id) }, 200, request, env);
  if (request.method === "POST" && url.pathname === "/api/devices") return createDevice(request, env, account);
  if (request.method === "GET" && url.pathname === "/api/devices") return listDevices(request, env, account);
  if (request.method === "POST" && url.pathname === "/api/sync") return sync(request, env, account);
  return error("Route not found", 404, request, env, "not_found");
}

export default {
  async fetch(request, env) {
    try {
      return await route(request, env);
    } catch (cause) {
      if (cause instanceof Response) return cause;
      console.error("computer-warrior worker error", cause);
      return error("Unexpected server error", 500, request, env, "internal_error");
    }
  },
};

export { route };
export const __test = { canonicalSync, constantTimeEqual, inviteOnly, isPrivateBeta, sessionTokenHash, syncPayload, validDeviceId, validUsername };
