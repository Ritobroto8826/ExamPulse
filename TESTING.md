# Verification and release checklist

Tests included in this package do **not** use or modify a real Supabase project.
They cover application behavior plus actual PostgreSQL authorization semantics.
A real hosted-project/email smoke test is still required before production use.

## Python transport, validation and UI tests

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
```

HTTP requests are intercepted by `httpx.MockTransport`. No real mail is sent and
no real passwords or cloud keys are needed. Test-only email domains use
`example.test`. Coverage includes:

- Per-class curriculum (Classes 8/9/10, 86 chapters) and migration seed
  agreement; class-scoped chapter lists, multi-topic saves, raw-mark
  conversion and the teacher class view.
- User JWT isolation; REST and read-only RPC pagination beyond 1,000 rows.
- No unauthenticated data writes and no raw provider-secret error echoing.
- Fresh teacher onboarding, invitation UI, multi-topic chapter entry and
  student marks (15/20 → 75%).
- Individual login, wrong password, refresh, disable, invite callback and URL
  scrubbing, mandatory password setup UI and current-password confirmation.
- Teacher/student pages in light and dark modes with chart palette assertions.
- Names versus unique email matching, duplicate rows, invalid dates/topics/
  marks, atomic-import boundary, spreadsheet formula-safe exports.
- CSV/XLSX parsing limits, unsafe compression and oversized input rejection.

These mocks validate the application contract, not Supabase's hosted SMTP,
networking, token signatures or project-specific settings.

## Edge Function tests and type check

With Deno installed:

```bash
deno check --config supabase/functions/manage-students/deno.json \
  supabase/functions/manage-students/index.ts
deno test --config supabase/functions/manage-students/deno.json --allow-env \
  supabase/functions/manage-students/handler_test.ts
```

The function SDK dependency graph is locked in its `deno.lock`. Runtime fetches
are mocked by the tests; no network invitations are sent. Tests deny missing /
invalid bearer tokens, student callers, inactive staff, invalid class levels
and invitation-rate failures, and verify the teacher-only success path returns
no token/key material.

## Actual PostgreSQL RLS tests

Use a **disposable** PostgreSQL 15+ database with a name containing `test`.
Never run `local_bootstrap.sql` against a hosted Supabase project: it emulates
Supabase's Auth schema/roles only for a local test server.

```bash
createdb exampulse_security_test
cat tests/local_bootstrap.sql \
    supabase/migrations/202611260001_production.sql \
    tests/pre_upgrade_schedule.sql \
    supabase/migrations/202611270001_multi_class_entry.sql \
    supabase/migrations/202611270002_schedule_view.sql \
    supabase/migrations/202611270003_delete_exam.sql \
    tests/rls.sql | psql -X -v ON_ERROR_STOP=1 exampulse_security_test
```

Run the command as a local test superuser capable of creating roles, or supply
its normal local connection settings. `tests/rls.sql` rolls its fixtures back;
the schema and curriculum migration remain in that disposable test database.
To repeat policy tests without re-creating the schema:

```bash
psql -X -v ON_ERROR_STOP=1 exampulse_security_test < tests/rls.sql
```

Expected final line: `ALL POSTGRESQL RLS TESTS PASSED`.

The SQL tests check anonymous denial, raw/view student row ownership, no role
escalation, no student writes/imports/invitations, teacher full-class reads,
service-only provisioning, exact chapter/subject/class consistency (including
the cross-class score trigger and raw-marks bounds), invalid marks, atomic
rollback of invalid imports, audit records, invitation-rate locking,
disabled/unprovisioned account denial, class-scoped peer comparison,
immutable curriculum and the intentionally allowed named comparison function.

The repository's CI workflow runs the Python, Deno and PostgreSQL suites without
production secrets. Hosted Supabase behavior still needs the following release gate.

## Hosted staging release gate — administrator action required

1. Use a staging Supabase project and HTTPS UI URL, with the production migration.
2. Confirm RLS is enabled and no extra permissive policies exist.
3. Configure custom SMTP and the exact `token_hash` invite/reset templates.
4. Bootstrap one teacher through trusted administrator tools.
5. Invite two distinct student emails; verify both receive real emails and each
   chooses their own password. No shared password or demo account should work.
6. Create an exam and enter different marks for both students.
7. Sign in from separate browser profiles. Verify own-only Dashboard/My Progress,
   read-only named comparisons and absence of staff controls.
8. Test the student's JWT against the REST API in a **local private test script**:
   raw class marks must remain RLS-filtered and direct write/role attempts denied.
   Never place tokens in screenshots, issue trackers or committed test files.
9. Disable one student while signed in. Verify subsequent UI/API requests fail.
10. Test expired/used invitation, password reset, current-password change,
    session refresh, logout, bad credentials and provider rate limiting.
11. Inspect Edge/Auth logs for safe error handling and onboarding cleanup states.
12. Verify backups/PITR and perform a restore drill before real records are added.
13. Test desktop and 360–430px mobile layouts, both color modes, the calendar,
    upload rejection/validation, score edits and CSV download safety.

Do not skip this gate based on local test results. No project credentials were
provided with the package, so the authoring environment cannot certify a real
cloud deployment, email delivery, institution policy compliance, or an SLA.
