# ExamPulse release verification

Date: 27 November 2026 (multi-class update; original verification below)

## Executed successfully in the authoring workspace

| Check | Result |
|---|---|
| Python HTTP/Auth/data/upload tests and Streamlit AppTest UI flows | 20 tests passed |
| Deno mocked invitation authorization/onboarding tests | 6 tests passed |
| Edge Function Deno type check | Passed |
| Fresh production migration on disposable PostgreSQL 17 | Passed |
| Real PostgreSQL RLS/grant/constraint/import tests, including invitation-rate cap and curriculum write denial | Passed |
| Legacy SQLite file compared with preserved pre-conversion backup | Byte-for-byte identical |
| Streamlit server restart on port 8501 | Passed; configuration-required setup screen |

The Python UI tests exercise teacher and student pages, both color modes,
invitation/password-setup gating and teacher entry → student marks visibility
using a mocked HTTP transport. PostgreSQL policy tests execute with actual
anonymous/authenticated/service roles and JWT claim simulation, rather than
mocking SQL permission decisions. Their data fixtures roll back.

## Not executed / still required by the deployment administrator

- No hosted Supabase project was connected or deployed.
- No real invitation/reset email was sent; custom SMTP and template behavior
  remain to be tested with the actual project and HTTPS UI host.
- Supabase gateway configuration, live token verification, concurrent school
  load, mobile-browser QA and backup restoration require staging validation.
- The included GitHub Actions workflow has not been run on a remote repository.
- Docker build/deployment has not been executed here.
- This verification is not an independent security assessment or certification.

Follow DEPLOY_SUPABASE.md and the hosted staging gate in TESTING.md before adding
real student information. Do not infer successful cloud deployment from local
suite results.

## Update — Classes 8/9/10 multi-class entry (27 November 2026)

| Check | Result |
|---|---|
| Python HTTP/Auth/data/upload tests and Streamlit AppTest UI flows | 21 tests passed |
| Fresh migrations applied to a disposable PostgreSQL 16.2 (embedded server) | Passed |
| Real PostgreSQL RLS/grant/trigger/constraint/import tests: cross-class score rejection, raw-marks bounds, class-scoped peer comparison, atomic multi-topic import | `ALL POSTGRESQL RLS TESTS PASSED` |
| Edge Function TypeScript files parsed (esbuild syntax check) | Passed |
| Deno Edge Function test suite | **Not re-run in this workspace** (Deno unavailable here). The function changes are code-reviewed; rerun the Deno commands in TESTING.md before release. |
| Upgrade path with pre-existing data (students + scheduled chapter test) replayed, then RLS suite | Passed |
| Upgrade migration + `manage-students` Edge Function applied to a hosted Supabase project with live test data | Applied and verified: 86 chapters, backfilled classes/schedule, preserved students/scores, Edge Function v2 active | |

Still required (unchanged): hosted staging/email gate, SMTP and template
verification, backups/PITR restore drill, and review of the Class 8/9 chapter
lists against the school's actual syllabus before first deployment.
