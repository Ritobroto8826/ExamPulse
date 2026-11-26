# ExamPulse — Supabase edition

A responsive academic dashboard with light/dark mode, **Mathematics + Science**,
Supabase PostgreSQL persistence and individual email/password accounts managed
by Supabase Auth. This edition starts with a **clean database**: no demo people,
marks, public accounts or shared student password.

## Start here

1. Read **[DEPLOY_SUPABASE.md](DEPLOY_SUPABASE.md)** for the full deployment guide.
2. Apply the migration to a **fresh Supabase project**.
3. Configure SMTP/Auth email templates and bootstrap your first teacher.
4. Deploy the invitation Edge Function and configure the three UI settings.
5. Invite students; each sets their own private password from their email link.

**The Python app is hosted separately** (Streamlit Community Cloud or a Docker /
Python host). Supabase runs the database, authentication and invitation function.
No actual Supabase credentials are included, and no hosted project was deployed
by this package. Without configuration, the app shows a secure setup screen and
the complete supported curriculum instead of a fake/demo login.

```bash
pip install -r requirements.txt
streamlit run app.py --server.address=0.0.0.0 --server.port=8501
```

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` for local use,
or use the host's secret manager. Only these settings belong in the UI:

```toml
SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_YOUR_PUBLIC_KEY"
APP_URL = "https://YOUR-APP.streamlit.app"
```

Never put a service-role/secret key or PostgreSQL owner connection string in
Streamlit. The app rejects privileged API keys and makes all data requests with
the signed-in user's JWT. Auth roles come from a protected database profile,
not an account-selection dropdown or editable user metadata.

## Exact curriculum

### Mathematics — 14 chapters

1. Real Numbers
2. Polynomials
3. Pair of Linear Equations in Two Variables
4. Quadratic Equations
5. Arithmetic Progressions
6. Triangles
7. Coordinate Geometry
8. Introduction to Trigonometry
9. Some Applications of Trigonometry
10. Circles
11. Areas Related to Circles
12. Surface Areas and Volumes
13. Statistics
14. Probability

### Science — 13 chapters

1. Chemical Reactions and Equations
2. Acids, Bases and Salts
3. Metals and Non-metals
4. Carbon and its Compounds
5. Life Processes
6. Control and Coordination
7. How do Organisms Reproduce?
8. Heredity
9. Light – Reflection and Refraction
10. The Human Eye and the Colourful World
11. Electricity
12. Magnetic Effects of Electric Current
13. Our Environment

`curriculum.py` and the migration seed contain the same ordered curriculum.
Scores enforce subject/chapter consistency using a composite foreign key.
Schedule chapters also reference the approved curriculum.

## Features

### Teacher

- Class-wide KPIs, trends, weak-topic analytics and progress leaderboard.
- Individual student drill-downs, one-topic-at-a-time exam score entry, inline
  edits and deletion. Student roster IDs prevent same-name account mix-ups.
- Email invitations, individual account activation/deactivation, no shared
  default password, no password visibility for teachers.
- CSV/XLSX imports with validation and atomic server-side writes; safe CSV reports.
- Upcoming tests/revision calendar and an adjustable mastery threshold.
- Account password change with current-password confirmation and staff audit view.

### Student

- Own-only Dashboard, My Progress, topic recommendations and schedule.
- Individual email/password login, password recovery and private password changes.
- Read-only **Student Comparison**, by exam/subject/chapter. As requested, this
  intentionally shares classmates' **names, batches and exam summary marks**.
  It does not share emails, Auth user IDs, passwords or account-management access.
  This privacy choice requires school authorization before real student use.

### Interface

- Professional light/dark layouts, responsive at phone/desktop widths.
- Clear chart legends, explicit mastery/benchmark lines and consistent percentage
  axes; contrasting indigo/lavender, teal, coral and amber indicators.
- User-highlighted, numeric-label comparison bars with 25-student chart pages.
- Theme preference persists through navigation/logout and URL-based refreshes.
- Missing marks are not zero. Multi-topic comparison uses the mean of recorded
  topic percentages; filter a single chapter for like-for-like comparison.

## Security and persistence

- PostgreSQL RLS enforces ownership even if someone bypasses the UI.
- Students cannot create exams, edit marks, invite accounts, promote themselves,
  view staff audits or query other students' raw score/account records.
- Comparison uses an explicitly authorized, narrow summary function.
- Disabled and unprovisioned users are denied school-data access.
- Invitation function verifies the user with Supabase, checks active teacher role,
  and applies a transaction-safe limit of 20 attempts per teacher per hour.
- Supabase alone stores password hashes; the application stores no passwords.
- JWT/refresh tokens are session-local; no globally shared authenticated client.
- Input length, score, upload-size, row-count and workbook-decompression checks;
  atomic bulk import, safe error messages and formula-neutralized CSV exports.
- Data/profile/schedule changes are audited in a restricted table.
- No runtime SQLite fallback or database seeding. All classroom writes are durable
  in your Supabase project; configure actual backups/PITR and verify restoration.

This is a production-oriented foundation for **one school per project**, not a
security certification or an SLA. Complete the hosted staging, email-delivery,
privacy, backup and security-review checklist in the deployment guide. Multi-
tenant organizations, in-app MFA/SSO challenges, CAPTCHA UI and large background
report jobs are outside this release's scope.

## Bulk uploads

Use these columns:

```text
student,subject,topic,exam,exam_date,score
```

`exam_kind` is optional. `student` should be the registered email; a unique full
name is accepted, but duplicated names must use email. Dates: `YYYY-MM-DD`.
Marks: finite percentages from 0 to 100. Use only the listed subjects/chapters.
Maximum: 5 MB, 1,000 rows per file. Any validation errors must be fixed before
import; the actual write executes in one PostgreSQL transaction. Re-importing
matching student/exam/chapter rows updates marks instead of duplicating them.

## Tests

See **[TESTING.md](TESTING.md)** for full instructions and test limitations.

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Additional suites verify the Edge Function with Deno and **actual PostgreSQL RLS**
against a disposable database. CI runs all three without production secrets.
Local tests do not prove your real SMTP, Auth email templates, cloud routing or
project configuration. A hosted end-to-end staging test is mandatory.

## Files

```text
app.py                     Streamlit pages, analytics and account flows
auth.py                    Supabase Auth/session/invite/recovery lifecycle
cloud.py                   Per-user HTTP transport, pagination, safe errors
database.py                Supabase repository and upload/report validation
settings.py                Safe API configuration; privileged-key rejection
curriculum.py              Exact 2-subject / 27-chapter curriculum
uploads.py                 Bounded CSV/XLSX parsing
charts.py                  Light/dark Plotly chart builders
components.py              Cards, rings, lists, badges and mastery bars
theme.py / styles.py        Session-scoped design tokens and app chrome
styles.css                 Responsive light/dark styling
supabase/migrations/       Fresh PostgreSQL schema, RLS, RPCs, curriculum seed
supabase/functions/        Teacher-only invitation Edge Function + tests/lock
supabase/bootstrap_teacher.sql  Trusted first-teacher setup
.streamlit/                Baseline config and secrets example (no real secrets)
Dockerfile                 Non-root UI container; inject settings at runtime
.github/workflows/ci.yml    Python, Edge and PostgreSQL test jobs
tests/                     HTTP/UI/upload tests and disposable SQL security tests
DEPLOY_SUPABASE.md          Deployment, Auth/email templates and operations guide
TESTING.md                 Tests and hosted staging release gate
```

The former SQLite database and application were preserved separately under
`backups/` in the authoring workspace. They are intentionally **excluded** from
this production source archive and are not read by this app. Keep any older
classroom backup securely; do not publish it in a repository or container.
