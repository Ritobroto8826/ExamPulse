// Unit tests only: all provider calls are intercepted; no real invitations.
import { handleRequest } from "./handler.ts";

function assert(value: unknown, message = "assertion failed"): asserts value {
  if (!value) throw new Error(message);
}

const teacherId = "10000000-0000-4000-8000-000000000001";
const studentId = "10000000-0000-4000-8000-000000000002";
const originalFetch = globalThis.fetch;

function setup(role = "teacher", active = true, validJwt = true, rateLimited = false) {
  Deno.env.set("SUPABASE_URL", "https://project.example.test");
  Deno.env.set("SUPABASE_ANON_KEY", "unit-test-public-key");
  Deno.env.set("SUPABASE_SERVICE_ROLE_KEY", "unit-test-service-key-not-a-real-key");
  Deno.env.set("APP_URL", "https://app.example.test");
  const calls: string[] = [];
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init);
    const path = new URL(request.url).pathname;
    calls.push(path);
    let data: unknown = {};
    let status = 200;
    if (path === "/auth/v1/user") {
      if (validJwt) data = { id: teacherId, email: "staff@example.test", aud: "authenticated", app_metadata: {}, user_metadata: { role: "teacher" } };
      else { data = { message: "invalid token" }; status = 401; }
    } else if (path === "/rest/v1/profiles") {
      data = { role, active };
    } else if (path === "/rest/v1/rpc/claim_invitation") {
      if (rateLimited) { data = { message: "limit" }; status = 400; }
      else status = 204;
    } else if (path === "/auth/v1/invite") {
      data = { id: studentId, email: "student@example.test", aud: "authenticated", app_metadata: {}, user_metadata: {} };
    } else if (path === "/rest/v1/rpc/provision_student") {
      data = 42;
    } else throw new Error(`Unexpected network call ${path}`);
    return Promise.resolve(new Response(status === 204 ? null : JSON.stringify(data), {
      status, headers: { "Content-Type": "application/json" },
    }));
  }) as typeof fetch;
  return calls;
}

function request(authorization = "Bearer unit-user-jwt", extra = {}) {
  return new Request("https://edge.example.test/manage-students", {
    method: "POST", headers: { Authorization: authorization, "Content-Type": "application/json" },
    body: JSON.stringify({ name: "Test Student", batch: "Class 10", email: "student@example.test", ...extra }),
  });
}

Deno.test("no bearer token cannot reach any provider call", async () => {
  const calls = setup();
  try { const response = await handleRequest(request("")); assert(response.status === 401); assert(calls.length === 0); }
  finally { globalThis.fetch = originalFetch; }
});
Deno.test("invalid JWT is checked with Supabase before role lookup", async () => {
  const calls = setup("teacher", true, false);
  try { const response = await handleRequest(request()); assert(response.status === 401); assert(calls.length === 1); }
  finally { globalThis.fetch = originalFetch; }
});
Deno.test("student cannot invite, even with teacher metadata or request role", async () => {
  const calls = setup("student");
  try {
    const response = await handleRequest(request("Bearer unit-user-jwt", { role: "teacher" }));
    assert(response.status === 403); assert(!calls.includes("/auth/v1/invite"));
  } finally { globalThis.fetch = originalFetch; }
});
Deno.test("disabled teacher cannot invite", async () => {
  setup("teacher", false);
  try { assert((await handleRequest(request())).status === 403); }
  finally { globalThis.fetch = originalFetch; }
});
Deno.test("database rate gate runs before invitation", async () => {
  const calls = setup("teacher", true, true, true);
  try { assert((await handleRequest(request())).status === 429); assert(!calls.includes("/auth/v1/invite")); }
  finally { globalThis.fetch = originalFetch; }
});
Deno.test("active teacher invitation provisions a student without returning keys or tokens", async () => {
  const calls = setup();
  try {
    const response = await handleRequest(request());
    assert(response.status === 201, `Expected 201, got ${response.status}`);
    const text = await response.text();
    assert(!text.includes("unit-test-service")); assert(!text.includes("unit-user-jwt"));
    assert(calls.includes("/rest/v1/rpc/provision_student"));
  } finally { globalThis.fetch = originalFetch; }
});
