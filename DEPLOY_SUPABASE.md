# Deploy ExamPulse with Supabase

This is the **clean Supabase edition**. It never reads the previous SQLite file,
never auto-creates demo accounts, and never falls back to local storage.

**Architecture:** Streamlit hosts the Python UI; Supabase hosts PostgreSQL,
Auth and the `manage-students` Edge Function. Supabase does not run a Streamlit
server. Host the UI on Streamlit Community Cloud, a Docker host, or another
Python-capable HTTPS host. This release is for **one school per Supabase project**.

## What you need

- A fresh Supabase project that you administer.
- A stable HTTPS URL for the Streamlit app (a staging URL first is recommended).
- A production SMTP provider configured for Supabase Auth.
- A unique email address for every teacher and student.
- Python 3.12 for the UI. Supabase CLI for the database/function deployment.

No real Supabase project is configured in this download. Do not paste privileged
keys into chat, source control, screenshots, or the Streamlit app.

## 1. Deploy the Python app to obtain its URL

Push the package contents to a private GitHub repository. Include all root Python
modules, `styles.css`, `requirements.txt`, and `.streamlit/config.toml`. Do not
include backups, SQLite files, `.streamlit/secrets.toml`, or `.env` files.

On Streamlit Community Cloud, select the repository, Python 3.12 and `app.py` as
the entry point. The first page will show the secure setup screen until Secrets
are configured. Record the app's HTTPS URL, without a query string or fragment.

For Docker:

```bash
docker build -t exampulse .
# The env file must contain only the three settings from Step 6.
docker run --rm -p 8501:8501 --env-file /secure/path/exampulse.env exampulse
```

Terminate HTTPS at the hosting proxy and allow WebSocket connections. Bind the
app to port 8501. Do not expose a plain HTTP deployment publicly.

## 2. Apply the database migrations to a FRESH project

Option A — SQL Editor: execute **both files in order**:

1. `supabase/migrations/202611260001_production.sql`
2. `supabase/migrations/202611270001_multi_class_entry.sql`

Option B — Supabase CLI, from the package root (applies every pending
migration in order):

```bash
supabase login
supabase link --project-ref YOUR_PROJECT_REF
supabase db push
```

Each migration runs in a transaction. Together they create:

- Two subjects, **Mathematics** and **Science**, with ordered chapters for
  **Class 8 (16 + 15), Class 9 (15 + 13) and Class 10 (14 + 13)** — 86 chapters.
- Empty students, profiles, exams, scores and schedule tables.
- Security-invoker reporting views, RLS policies and narrow RPCs.
- An audit log, an atomic invitation rate gate, and a trigger that rejects
  scores whose chapter does not match the student's class.

They deliberately fail if conflicting tables already exist. They do **not**
drop or migrate any existing classroom records. Do not edit a deployed
migration; add a new migration for future changes.

**Upgrading a deployment made from the single-class edition:** run only
`202611270001_multi_class_entry.sql` in the SQL Editor (it converts existing
students and scheduled chapter tests to Class 10 where the batch/topic text
says so), then **redeploy the `manage-students` Edge Function** — provisioning
now takes a class level. Review `students.class_level` afterwards;
unrecognised batch text falls back to Class 10 and can be corrected in
Manage Students.

Verify the seed in SQL Editor:

```sql
select t.class_level, s.name, count(t.id) as chapters
from public.subjects s join public.topics t on t.subject_id=s.id
group by t.class_level, s.id, s.name, s.position
order by t.class_level, s.position;
-- Class 8: Mathematics 16, Science 15
-- Class 9: Mathematics 15, Science 13
-- Class 10: Mathematics 14, Science 13
select count(*) from public.students; -- 0 before inviting anyone
select count(*) from public.scores;   -- 0 before entering marks
```

Keep the Data API max-row setting at **at least 500** (the default 1,000 is fine).
The app paginates reads and comparison RPCs in 500-row pages rather than silently
accepting the default 1,000-row truncation. The interactive client has an explicit
100,000-row safety limit; larger datasets need server-side reporting filters.

## 3. Configure Supabase Auth and email

In Supabase Authentication settings:

1. Enable email/password authentication and **disable public signups**. Students
   must be invited by a teacher. There is intentionally no signup UI or
   user-metadata-to-role trigger.
2. Set **Site URL** to the app's HTTPS URL and allow the exact app root redirect
   URL, including the trailing `/`. Avoid broad wildcard redirect allowlists.
3. Set the minimum password length to **12 or more**, enable available strong /
   leaked-password protection, and enable secure password changes. The app also
   requires 12–128 characters and current-password reauthentication for normal
   password changes. It uses a freshly verified session for invite/recovery flows.
4. Configure custom SMTP, sender address and sender-domain authentication. The
   default Supabase test email service can restrict recipients and is not a
   production school-mail setup. Check SMTP quotas and Auth/email rate limits.
5. Review Auth session expiration, refresh-token reuse protection and rate limits.
   Auth requests originate from the Streamlit server, so test rate limits with
   the expected number of concurrent students rather than assuming one client IP
   per browser. The school account's `active` flag is rechecked on every UI rerun
   and on every database policy evaluation.
6. Do not enable a CAPTCHA requirement without adding a compatible challenge UI;
   this version does not include a CAPTCHA widget or MFA/SSO challenge screens.

### Important: replace the invitation and reset email links

Streamlit's Python server cannot read access tokens in a browser URL **fragment**
(`#access_token=...`). Use one-time `token_hash` callbacks instead.

In **Authentication → Email Templates**, set the **Invite user** link to:

```html
<a href="{{ .SiteURL }}/?token_hash={{ .TokenHash }}&amp;type=invite">Set my private password</a>
```

Set the **Reset password** link to:

```html
<a href="{{ .SiteURL }}/?token_hash={{ .TokenHash }}&amp;type=recovery">Reset my private password</a>
```

Configure Site URL without a trailing slash so these links contain a single `/`.
Use the same app URL everywhere. The callback exchanges the one-time hash with
Supabase, removes it from the URL and requires password setup before showing marks.
Email/password login handles the session after that. There is no public default
password and no password is stored in the ExamPulse tables.

Test the templates end to end. Email link-tracking/security scanners may consume
one-time links; disable link tracking if necessary and use the reset-link form
for expired invitations. Do not log full callback URLs or enable third-party
analytics that capture authentication query parameters.

## 4. Create the first teacher securely

1. In **Authentication → Users → Add user**, create a teacher with the teacher's
   real email and a strong, unique password. Confirm the email through the
   supported admin/confirmation flow. Store the password in a password manager.
2. Open `supabase/bootstrap_teacher.sql`, replace `admin_email` and `admin_name`,
   and run it in the SQL Editor.
3. Verify that `public.profiles` has that user's Auth UUID, role `teacher`, active
   status, and no student link.

Additional teachers require the same trusted administrator process. Neither a
student nor a normal teacher can change profile roles through the public API.
Never assign a teacher role from `user_metadata` or by a role selector at login.

## 5. Deploy the invitation Edge Function

```bash
supabase secrets set APP_URL=https://YOUR-APP.streamlit.app
supabase functions deploy manage-students --no-verify-jwt
```

The hosted function uses Supabase's server-only `SUPABASE_URL`,
`SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` runtime secrets. Verify those
are available for your project's runtime. The service-role key belongs **only**
in the Edge Function environment, never in Streamlit Secrets. `APP_URL` is set
separately because it is the trusted redirect target; request bodies cannot
choose arbitrary redirects or roles.

**Why `--no-verify-jwt`?** Gateway verification can be incompatible with newer
signing-key formats. The function explicitly calls `auth.getUser(jwt)` against
Supabase to validate the bearer token, then checks the caller's active teacher
profile using the caller's JWT. It denies anonymous, invalid, student and inactive
callers before creating an admin client. Do not remove these checks.

The function claims an atomic per-teacher rate slot before inviting (20 attempts
per hour), invites by email, and links the Auth user and student profile through
a service-only transaction. It returns no keys, tokens, passwords or invite URLs.
If onboarding cannot be confirmed, it checks whether the DB transaction committed
before compensating. An unknown network outcome is returned as an administrator
review error; **do not blindly retry uncertain invitations**.

To investigate an onboarding error, inspect Edge logs, Authentication Users,
`public.students` and `public.profiles`. A user without a linked active school
profile has no school-data access. Resolve or remove confirmed orphaned test
accounts through the administrator tools, not by weakening RLS.

## 6. Configure Streamlit Secrets

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` locally, or
paste the following into the host's secret manager:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_YOUR_PUBLIC_KEY"
APP_URL = "https://YOUR-APP.streamlit.app"
```

Legacy `SUPABASE_ANON_KEY` is accepted instead of `SUPABASE_PUBLISHABLE_KEY`.
These are API connection settings, **not** database passwords. The app rejects
`sb_secret_` and legacy `service_role` keys. Every data request carries the
individual user's access JWT, and PostgreSQL RLS checks it independently of UI
controls. The public key alone grants no classroom-table access.

Restart the UI after changing settings. It must not contain a service key,
PostgreSQL owner connection string, shared user password, or production tokens.

## 7. Invite students and enter marks

1. Sign in with the first teacher's email/password.
2. Open **Students & Scores → Manage Students**.
3. Enter the student's full name, **class** (8, 9 or 10), batch and **unique
   email**, then invite. The class decides which chapters can be recorded for
   that student; it can be corrected later in Manage Students if needed.
4. The student opens the email and sets their **own private password**. The
   teacher cannot see it. Students should choose distinct passwords and not
   share email accounts; Supabase does not promise that two people cannot
   independently choose the same password string.
5. Enter marks in **Add / Edit Scores**: pick the student, the subject, then
   **tick every chapter the test covered** and type each chapter's raw marks
   with their total (e.g. 15 out of 20 — not every test is out of 100). One
   save records all ticked chapters under the same exam in a single
   transaction, storing both the converted percentage and the raw marks.
   When different classes test on the same day, give each class its own exam
   name so the tests stay separate. Bulk uploads identify students by
   registered email (unique names are also accepted, but ambiguous names are
   rejected) and validate chapters against each student's class.
6. Use **Account & Security** for password changes and recent staff audit events.
7. A teacher can disable/enable a student in Manage Students without deleting
   historical marks. Disabling immediately blocks DB access even for an existing
   JWT. It does not retract marks a user already saw or downloaded.

Students' personal pages show only their own rows. As requested, **Student
Comparison deliberately shares names, batches and selected exam summaries**
with active school users **of the viewer's own class**. It exposes neither
email addresses nor Auth UUIDs or account details. Comparison charts paginate
at 25 bars per chart page for large rosters. This is an explicit privacy
choice; obtain school/parental authorization before using real student data.
Do not describe this feature as fully private marks.

## 8. Backups, operations and release gates

Before admitting real student records:

- Run an end-to-end staging test with **real** email delivery: invite two students,
  set passwords, log in separately, reset a password, disable one account, and
  verify personal pages and named comparisons. Local tests cannot prove your
  project's SMTP, policies, email templates or hosting configuration.
- Run the security tests in `TESTING.md`; repeat after every schema/auth change.
  Confirm policies are enabled and no extra permissive policies were added.
- Set up database backups/PITR appropriate to your Supabase plan and perform a
  restore drill. CSV reports are not a full database/Auth backup.
- Rotate exposed keys immediately. Secure administrator accounts with your
  organization's MFA policies and restrict SQL/Edge deployment access.
- Monitor Auth failures, Edge errors, invitation rate events and audit logs.
  Audit tables have no user delete/update grants; privileged administrators must
  implement retention/archival with the school's approved policy.
- Define retention/deletion procedures for Auth users, roster rows, marks and
  audit history. Disabling is not deletion. Authorize any permanent deletion.
- Pin/review dependency updates, rehearse migrations in staging and keep the
  previous deployment artifact for rollback. Do not use schema rollback that
  silently destroys student records.
- Obtain a security/privacy review for the actual deployment. This is a tested
  production foundation, not a security certification or an SLA. The current
  version is single-school; multi-tenant isolation, app MFA/SSO challenges,
  CAPTCHA UI, and background report jobs require additional work if needed.

## Troubleshooting

| Symptom | Check |
|---|---|
| Setup screen remains | Three Streamlit Secrets are present, correct and HTTPS; restart |
| Login succeeds in Auth but school access denied | Matching `profiles` row exists and is active |
| Invitation not delivered | Edge deployed, runtime secrets, custom SMTP, Auth quotas, spam folder |
| Link opens but no password form | Email template must use `token_hash`, not fragment tokens |
| Expired/used invitation | Request a new password link from login; verify SMTP/template |
| Empty student dashboard | Teacher saved marks for the correct roster ID/exam; no marks is valid in a fresh DB |
| Role/profile edits fail | Expected: roles cannot be changed by users; use the trusted admin process |
| Uncertain write/invite outcome | Refresh/inspect the database first; mutations are not blindly retried |
| Large file rejected | At most 5 MB / 1,000 rows; supported CSV/XLSX only, decompression limits apply |
