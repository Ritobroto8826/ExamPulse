// Only this Edge Function uses a service-role key. Never send that key to
// Streamlit, browsers, source control or client-side JavaScript.
import { createClient } from "npm:@supabase/supabase-js@2.119.2";

const headers = { "Content-Type": "application/json", "Cache-Control": "no-store" };
const respond = (status: number, message: string) =>
  new Response(JSON.stringify({ message }), { status, headers });

export async function handleRequest(request: Request): Promise<Response> {
  if (request.method !== "POST") return respond(405, "POST required");
  const url = Deno.env.get("SUPABASE_URL");
  const anon = Deno.env.get("SUPABASE_ANON_KEY");
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const app = Deno.env.get("APP_URL");
  if (!url || !anon || !service || !app) return respond(503, "Function configuration incomplete");
  let appUrl: URL;
  try {
    appUrl = new URL(app);
    if (appUrl.protocol !== "https:" || appUrl.search || appUrl.hash) throw new Error();
  } catch {
    return respond(503, "Invalid redirect configuration");
  }
  const origin = request.headers.get("Origin");
  if (origin && origin !== appUrl.origin) return respond(403, "Origin not allowed");
  const authorization = request.headers.get("Authorization") ?? "";
  if (!authorization.startsWith("Bearer ")) return respond(401, "Sign in required");

  // verify_jwt is disabled at the gateway for signing-key compatibility; DO NOT
  // remove this explicit server-side signature/user verification and role check.
  const caller = createClient(url, anon, {
    global: { headers: { Authorization: authorization } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data: identity, error: authError } = await caller.auth.getUser(authorization.slice(7));
  if (authError || !identity.user) return respond(401, "Invalid session");
  const { data: profile, error: roleError } = await caller.from("profiles")
    .select("role,active").eq("id", identity.user.id).single();
  if (roleError || profile?.role !== "teacher" || !profile.active) return respond(403, "Teacher access required");

  let body: Record<string, unknown>;
  try {
    if (Number(request.headers.get("Content-Length") ?? 0) > 4096) return respond(413, "Request too large");
    const raw = await request.text();
    if (raw.length > 4096) return respond(413, "Request too large");
    body = JSON.parse(raw);
    if (!body || Array.isArray(body) || typeof body !== "object") throw new Error();
  } catch {
    return respond(400, "Invalid input");
  }
  const name = typeof body.name === "string" ? body.name.trim() : "";
  const batch = typeof body.batch === "string" ? body.batch.trim() : "";
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const classLevel = typeof body.class_level === "number" ? body.class_level : NaN;
  if (!name || name.length > 120 || !batch || batch.length > 80 || email.length > 254 ||
      !Number.isInteger(classLevel) || classLevel < 1 || classLevel > 12 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return respond(400, "Valid name, class, batch and email required");
  }

  const { error: limitError } = await caller.rpc("claim_invitation");
  if (limitError) return respond(429, "Invitation limit reached; try later");
  const admin = createClient(url, service, { auth: { persistSession: false, autoRefreshToken: false } });
  const { data: invited, error: inviteError } = await admin.auth.admin.inviteUserByEmail(email, {
    redirectTo: app.replace(/\/$/, "") + "/",
  });
  if (inviteError || !invited.user) return respond(409, "Unable to invite. Check whether the email already has an account.");

  const { error: provisionError } = await admin.rpc("provision_student", {
    p_user_id: invited.user.id, p_name: name, p_batch: batch, p_email: email,
    p_class_level: classLevel,
  });
  if (provisionError) {
    // A timeout can hide a successful commit. Check before compensating; never
    // delete a successfully provisioned account based only on a timeout.
    const { data: linked, error: checkError } = await admin.from("profiles")
      .select("student_id").eq("id", invited.user.id).maybeSingle();
    if (!checkError && linked?.student_id) return respond(201, "Invitation sent and student provisioned");
    if (!checkError && !linked) {
      const { error: cleanupError } = await admin.auth.admin.deleteUser(invited.user.id);
      if (cleanupError) console.error("Student onboarding cleanup needed; Auth user ID:", invited.user.id);
    } else {
      console.error("Student onboarding outcome unknown; inspect Auth user ID:", invited.user.id);
    }
    return respond(503, "Provisioning could not be confirmed. Ask the administrator to inspect onboarding before retrying.");
  }
  return respond(201, "Invitation sent. The student sets their private password from the email link.");
}
