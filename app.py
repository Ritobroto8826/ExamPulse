"""ExamPulse — Streamlit exam score tracker & weak-area analytics dashboard.

Teacher role : full class access, score entry, bulk upload, analytics, schedule.
Student role : own progress/weak topics/schedule; read-only peer exam comparison.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="ExamPulse · Exam Score Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

import auth
import database
from charts import (
    CHART_CONFIG, area_trend_chart, score_bar_chart, student_comparison_chart,
)
from components import (
    band,
    card_head,
    kpi_row,
    leaderboard_html,
    login_hero_html,
    page_head,
    profile_badge_html,
    progress_bars_html,
    schedule_html,
)
from styles import inject_css, init_theme, render_app_chrome, theme_mode
from cloud import CloudError
from settings import ConfigurationError, load_settings
from curriculum import CLASS_LEVELS, CURRICULUM, class_label
from uploads import read_score_upload

TEACHER_PAGES = [
    "📊 Dashboard",
    "🧑‍🏫 Students & Scores",
    "📤 Bulk Upload & Reports",
    "📅 Schedule",
    "🔐 Account & Security",
]
STUDENT_PAGES = [
    "📊 Dashboard",
    "📈 My Progress",
    "📅 Upcoming Tests",
    "📊 Student Comparison",
    "🔐 Account & Security",
]
TARGET_SCORE = 75  # student benchmark line


# ---------------------------------------------------------------------------
# Fresh data access across logins and concurrent sessions
# ---------------------------------------------------------------------------

def get_scores() -> pd.DataFrame:
    # A session-local counter is not a database revision: a new student session
    # starts at 0 and could otherwise reuse a pre-entry, globally cached frame.
    # Query the user's RLS-protected Supabase view on every rerun.
    return database.load_scores_df()


def bump() -> None:
    st.session_state["data_version"] = int(st.session_state.get("data_version", 0)) + 1


# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------

def _exam_avg_series(df: pd.DataFrame) -> pd.Series:
    return df.groupby("exam_date")["score"].mean().sort_index()


def _delta_card(pts: float | None, suffix: str) -> dict:
    if pts is None or abs(pts) < 0.05:
        return {"delta": f"no change {suffix}", "delta_dir": "flat"}
    return {
        "delta": f"{pts:+.1f} pts {suffix}",
        "delta_dir": "up" if pts > 0 else "down",
    }


def topic_stats(df: pd.DataFrame, threshold: int) -> pd.DataFrame:
    # Chapters repeat across classes (e.g. "Triangles" in 9 and 10): group by
    # class too, and disambiguate labels when a view mixes several classes.
    g = (df.groupby(["class_level", "subject", "topic"])["score"]
         .agg(avg="mean", n="count")
         .reset_index()
         .sort_values("avg"))
    if df["class_level"].nunique() > 1:
        g["topic"] = g["class_level"].map(lambda v: class_label(int(v))) + " · " + g["topic"]
    g["color"] = g["avg"].apply(lambda v: band(v, threshold)[0])
    g["label"] = g["avg"].apply(lambda v: band(v, threshold)[1])
    g["pill"] = g["avg"].apply(lambda v: band(v, threshold)[2])
    return g


def build_kpi_cards(df: pd.DataFrame, role: str, threshold: int) -> list[dict]:
    series = _exam_avg_series(df)
    pts = float(series.iloc[-1] - series.iloc[-2]) if len(series) >= 2 else None
    cards: list[dict] = []

    if role == "teacher":
        n_students = int(df["student_id"].nunique())
        new_n = database.students_joined_since(90)
        if new_n:
            cards.append({
                "label": "Total Students", "value": str(n_students),
                "delta": f"+{new_n} this term", "delta_dir": "up",
            })
        else:
            cards.append({
                "label": "Total Students", "value": str(n_students),
                "delta": f"{df['batch'].nunique()} active batches",
                "delta_dir": "flat",
            })
        cards.append({
            "label": "Class Average",
            "value": f"{df['score'].mean():.1f}%",
            **_delta_card(pts, "vs last test"),
        })
        topic_means = df.groupby(["class_level", "subject", "topic"])["score"].mean()
        n_above = int((topic_means >= threshold).sum())
        cards.append({
            "label": "Topics Above Mastery",
            "ring": 100.0 * n_above / max(1, len(topic_means)),
            "ring_color": "#6C5CE7",
            "sub": f"{n_above} of {len(topic_means)} topics ≥ {threshold}%",
        })
        pairs = df.groupby(["student_id", "topic_id"])["score"].mean()
        pct_on = 100.0 * float((pairs >= threshold).mean())
        n_flagged = int((pairs < threshold).sum())
        n_weak_topics = int((topic_means < threshold).sum())
        cards.append({
            "label": "On Track",
            "ring": pct_on,
            "ring_color": "#10B981",
            "sub": f"{n_flagged} flagged results · {n_weak_topics} weak topics",
        })
        return cards

    # ---- student ----
    n_tests = int(df["exam_id"].nunique())
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
    recent = int(df[df["exam_date"] >= cutoff]["exam_id"].nunique())
    cards.append({
        "label": "Tests Taken", "value": str(n_tests),
        "delta": (f"+{recent} this month" if recent else "all tests logged"),
        "delta_dir": "up" if recent else "flat",
    })
    cards.append({
        "label": "Personal Average",
        "value": f"{df['score'].mean():.1f}%",
        **_delta_card(pts, "vs last test"),
    })
    topic_means = df.groupby(["class_level", "subject", "topic"])["score"].mean()
    n_above = int((topic_means >= threshold).sum())
    cards.append({
        "label": "Topics Above Mastery",
        "ring": 100.0 * n_above / max(1, len(topic_means)),
        "ring_color": "#6C5CE7",
        "sub": f"{n_above} of {len(topic_means)} topics ≥ {threshold}%",
    })
    pct_scores = 100.0 * float((df["score"] >= threshold).mean())
    n_weak = int((topic_means < threshold).sum())
    cards.append({
        "label": "On Track",
        "ring": pct_scores,
        "ring_color": "#10B981",
        "sub": f"{n_weak} topics need focus",
    })
    return cards


def improvement_rows(df: pd.DataFrame, limit: int = 5) -> list[dict]:
    """Top students by score improvement: early third of term vs. latest third."""
    dates = sorted(df["exam_date"].unique())
    if len(dates) < 4:
        mid = pd.Timestamp(df["exam_date"].median())
        early = df[df["exam_date"] <= mid].groupby("student_id")["score"].mean()
        recent = df[df["exam_date"] > mid].groupby("student_id")["score"].mean()
    else:
        c1 = dates[len(dates) // 3]
        c2 = dates[(2 * len(dates)) // 3]
        early = df[df["exam_date"] < c1].groupby("student_id")["score"].mean()
        recent = df[df["exam_date"] >= c2].groupby("student_id")["score"].mean()
    imp = (recent - early).dropna()
    if imp.empty:
        return []
    top = imp.sort_values(ascending=False).head(limit)
    meta = (df.drop_duplicates("student_id")
            .set_index("student_id")[["student_name", "batch"]])
    rows = []
    for i, (sid, val) in enumerate(top.items(), start=1):
        name = (meta.loc[sid, "student_name"] if sid in meta.index
                else f"Student {sid}")
        batch = meta.loc[sid, "batch"] if sid in meta.index else ""
        rows.append({
            "rank": i, "avatar": str(name), "name": str(name),
            "meta": str(batch),
            "badge": f"{val:+.0f}%", "badge_neg": bool(val < 0),
        })
    return rows


def focus_rows(df: pd.DataFrame, threshold: int, limit: int = 5) -> list[dict]:
    stats = topic_stats(df, threshold).head(limit)
    rows = []
    for i, (_, r) in enumerate(stats.iterrows(), start=1):
        rows.append({
            "rank": i,
            "name": r["topic"],
            "meta": f"{r['subject']} · avg {r['avg']:.0f}%",
            "pill": r["label"],
            "pill_class": r["pill"],
        })
    return rows


def upcoming_items(limit: int = 6) -> list[dict]:
    today = date.today()
    items = []
    for t in database.list_upcoming():
        try:
            d = date.fromisoformat(t["test_date"][:10])
        except ValueError:
            continue
        if d < today:
            continue
        meta = t["subject"] or "All subjects"
        if t.get("class_level"):
            meta = f"{meta} · {class_label(t['class_level'])}"
        if t.get("topic"):
            meta = f"{meta} · {t['topic']}"
        items.append({
            "title": t["title"], "date": t["test_date"], "meta": meta,
            "notes": t.get("notes"),
        })
    return items[:limit]


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def _start_session(user: dict) -> None:
    st.session_state["user"] = user
    st.session_state["threshold"] = 70
    st.session_state["data_version"] = 0
    st.session_state["nav"] = (TEACHER_PAGES if user["role"] == "teacher" else STUDENT_PAGES)[0]


def _logout() -> None:
    auth.sign_out()
    for key in list(st.session_state.keys()):
        if key != "dark_mode":
            del st.session_state[key]


def render_login() -> None:
    st.markdown(login_hero_html(), unsafe_allow_html=True)
    st.caption("School accounts only. Your role is assigned by the school, not selected at login.")
    notice = st.session_state.pop("auth_notice", None)
    if notice:
        st.info(notice)
    with st.form("login_form", clear_on_submit=True):
        email = st.text_input("Email address", placeholder="you@school.edu", max_chars=254)
        password = st.text_input("Password", type="password", max_chars=128)
        submitted = st.form_submit_button("Sign in securely", type="primary", width="stretch")
    if submitted:
        user, error = auth.authenticate(email, password)
        if error:
            st.error(error)
        else:
            _start_session(user)
            st.rerun()
    with st.expander("First login or forgotten password?"):
        st.caption("New students: open your school's invitation email to set your private password. "
                   "For an expired invite or forgotten password, request a new link below.")
        with st.form("recovery_form", clear_on_submit=True):
            recovery_email = st.text_input("Account email", max_chars=254)
            recover = st.form_submit_button("Send password link")
        if recover:
            auth.request_password_reset(recovery_email)
            st.success("If this email has an account, a password link will arrive shortly. Check spam as well.")


def render_password_form(user: dict, setup: bool = False) -> None:
    st.markdown(page_head("Set your private password" if setup else "Account & Security",
                         "Use a unique passphrase of at least 12 characters. Never share your login."),
                unsafe_allow_html=True)
    st.caption(f"Signed in as {user['email']}")
    with st.form("password_form", clear_on_submit=True):
        current = None if setup else st.text_input("Current password", type="password", max_chars=128)
        password = st.text_input("New password", type="password", max_chars=128)
        confirmation = st.text_input("Confirm new password", type="password", max_chars=128)
        save = st.form_submit_button("Save private password", type="primary", width="stretch")
    if save:
        auth.change_password(password, confirmation, current_password=current)
        st.session_state["account_notice"] = "Your password has been updated."
        st.rerun()
    if setup:
        st.button("Sign out", on_click=_logout, key="setup_logout")
    elif user["role"] == "teacher":
        with st.expander("Recent security and data audit events"):
            st.caption("Latest 100 events. Full before/after records are restricted to teachers in Supabase.")
            st.dataframe(pd.DataFrame(database.audit_events()), hide_index=True, width="stretch")


def render_setup(message: str) -> None:
    st.markdown(page_head("Connect your secure workspace", "Supabase PostgreSQL + individual student accounts"),
                unsafe_allow_html=True)
    st.info(message)
    st.markdown("**Deployment setup required** — follow `DEPLOY_SUPABASE.md` in the source package. "
                "This production edition does not seed demo accounts or read the old SQLite file.")
    st.caption("No Supabase credentials have been supplied here. Your previous local database is preserved separately.")
    for level in CLASS_LEVELS:
        for subject, chapters in CURRICULUM[level].items():
            with st.expander(f"{class_label(level)} · {subject} · {len(chapters)} chapters",
                             expanded=True):
                st.markdown("\n".join(f"{i}. {chapter}" for i, chapter in enumerate(chapters, 1)))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar(user: dict) -> None:
    with st.sidebar:
        if user["role"] == "teacher":
            role_line = "Teacher · All classes"
        else:
            batch = user.get("batch") or ""
            parts = []
            if user.get("class_level"):
                parts.append(class_label(user["class_level"]))
            if batch:
                parts.append(batch)
            role_line = f"Student · {' · '.join(parts)}" if parts else "Student"
        st.markdown(profile_badge_html(user["display_name"], role_line),
                    unsafe_allow_html=True)
        st.button("Logout", key="logout_btn", width="stretch",
                  on_click=_logout)

        notice = st.session_state.pop("role_notice", None)
        if notice:
            st.info(notice)

        st.markdown('<div class="side-sep"></div>', unsafe_allow_html=True)
        pages = TEACHER_PAGES if user["role"] == "teacher" else STUDENT_PAGES
        st.radio("Navigation", pages, key="nav", label_visibility="collapsed",
                 format_func=lambda page: page.partition(" ")[2])

        if user["role"] == "teacher":
            st.markdown('<div class="side-sep"></div>', unsafe_allow_html=True)
            st.selectbox(
                "🏫 Class view",
                ["All classes"] + [class_label(v) for v in CLASS_LEVELS],
                key="class_view",
                help="Scopes Dashboard, reports and schedule analytics to one "
                     "class. Score entry and student drill-down always follow "
                     "the selected student.",
            )
            st.slider(
                "🎯 Mastery threshold", 40, 90, key="threshold", step=5,
                help="Scores below this level are flagged as weak areas and "
                     "recolored across the dashboard.",
            )
            st.caption(
                "Weak-area flags, donuts and color bands update live with "
                "this threshold."
            )
        st.caption("ExamPulse · Supabase secured")


# ---------------------------------------------------------------------------
# Dashboard (shared by teacher, student and teacher drill-down)
# ---------------------------------------------------------------------------

def render_dashboard(df: pd.DataFrame, role: str, student_id: int | None = None,
                     subtitle: str | None = None) -> None:
    if role == "student":
        df = df[df["student_id"] == student_id].copy()
    if df.empty:
        st.info("No scores recorded yet — add a score to get started.")
        return

    threshold = int(st.session_state.get("threshold", 70))

    if subtitle is None:
        if role == "teacher":
            subtitle = (
                f"Class-wide performance · {df['student_id'].nunique()} students · "
                f"{df['exam_id'].nunique()} tests"
            )
        else:
            subtitle = "Your personal exam analytics"
    st.markdown(page_head("Dashboard", subtitle), unsafe_allow_html=True)

    # ---- KPI row ----
    st.markdown(kpi_row(build_kpi_cards(df, role, threshold)),
                unsafe_allow_html=True)

    # ---- Middle row ----
    left, mid, right = st.columns([1.5, 1, 1], gap="medium")

    with left:
        with st.container(border=True):
            st.markdown(card_head(
                "Score performance",
                "Average marks across recorded topics. Use the filters to explore.",
            ), unsafe_allow_html=True)
            dim = st.selectbox(
                "View", ["Weekly", "Monthly", "By Exam", "By Subject"],
                key="bar_dim",
            )
            batch_comparison = dim == "By Subject" and role == "teacher" and df["batch"].nunique() > 1
            color_key = (
                '<span>Compare batches · see legend below</span>' if batch_comparison else
                '<span><i class="chart-dot good"></i>At mastery</span>'
                '<span><i class="chart-dot weak"></i>Below mastery</span>'
            )
            st.markdown(
                f'<div class="chart-key">{color_key}'
                '<span><i class="chart-dash"></i>'
                f'Target {threshold}%</span></div>', unsafe_allow_html=True,
            )
            fig = score_bar_chart(
                df, dim, threshold,
                group_by_batch=(role == "teacher"),
                height=320, theme=theme_mode(),
            )

            st.plotly_chart(fig, width="stretch", theme=None,
                            config=CHART_CONFIG, key="bar_main")

    with mid:
        with st.container(border=True):
            st.markdown(card_head("Upcoming tests"),
                        unsafe_allow_html=True)
            items = upcoming_items(3)
            st.markdown(schedule_html(items), unsafe_allow_html=True)
            if role == "teacher":
                def _goto_schedule() -> None:
                    st.session_state["nav"] = "📅 Schedule"
                st.button(
                    "Manage schedule →", key="manage_sch",
                    width="stretch", on_click=_goto_schedule,
                )

    with right:
        with st.container(border=True):
            if role == "teacher":
                st.markdown(card_head("Top academic progress",
                                      "Biggest improvement: early term → now"),
                            unsafe_allow_html=True)
                st.markdown(leaderboard_html(improvement_rows(df)),
                            unsafe_allow_html=True)
            else:
                st.markdown(
                    card_head("Priority focus",
                              "Ranked by lowest average score"),
                    unsafe_allow_html=True,
                )
                st.markdown(leaderboard_html(focus_rows(df, threshold)),
                            unsafe_allow_html=True)

    # ---- Bottom row ----
    bl, br = st.columns([1.35, 1], gap="medium")

    with bl:
        with st.container(border=True):
            st.markdown(card_head("Performance over time",
                                  "Score progression over time"),
                        unsafe_allow_html=True)
            subjects = ["All Subjects"] + sorted(df["subject"].unique().tolist())
            subject = st.selectbox("Subject", subjects, key="trend_subject")
            if role == "teacher":
                benchmark = float(df["score"].mean())
                bench_label = f"Class Avg {benchmark:.0f}%"
            else:
                benchmark = float(TARGET_SCORE)
                bench_label = f"Target {TARGET_SCORE}%"
            fig = area_trend_chart(
                df, subject, benchmark, bench_label, height=320, theme=theme_mode(),
            )
            st.plotly_chart(fig, width="stretch", theme=None,
                            config=CHART_CONFIG, key="trend_main")

    with br:
        with st.container(border=True):
            st.markdown(card_head("Mastery breakdown",
                                  "Mastery color scale, weakest first"),
                        unsafe_allow_html=True)
            view = st.radio(
                "Breakdown", ["By Subject", "By Topic"],
                horizontal=True, key="bars_view", label_visibility="collapsed",
            )
            if view == "By Subject":
                items = (
                    df.groupby("subject")["score"].mean()
                    .sort_values().reset_index().itertuples(index=False)
                )
                pairs = [(r.subject, r.score) for r in items]
            else:
                stats = topic_stats(df, threshold)
                pairs = list(zip(stats["topic"], stats["avg"]))
            st.markdown(progress_bars_html(pairs, threshold),
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Teacher: Students & Scores
# ---------------------------------------------------------------------------

def _student_overview(df: pd.DataFrame, threshold: int) -> pd.DataFrame:
    rows = []
    for sid, g in df.groupby("student_id"):
        stats = topic_stats(g, threshold)
        weakest = stats.iloc[0] if not stats.empty else None
        rows.append({
            "Student": g["student_name"].iloc[0],
            "Class": class_label(int(g["class_level"].iloc[0])),
            "Batch": g["batch"].iloc[0],
            "Tests": int(g["exam_id"].nunique()),
            "Average %": round(float(g["score"].mean()), 1),
            "Weak topics": int((stats["avg"] < threshold).sum()),
            "Weakest topic": (f"{weakest['topic']} ({weakest['avg']:.0f}%)"
                              if weakest is not None else "—"),
        })
    return (pd.DataFrame(rows)
            .sort_values("Average %", ascending=False)
            .reset_index(drop=True))


def render_students_page(df: pd.DataFrame) -> None:
    threshold = int(st.session_state.get("threshold", 70))
    st.markdown(page_head(
        "Students & Scores",
        "Drill into individual performance, enter topic-level scores, manage rosters",
    ), unsafe_allow_html=True)

    tab_drill, tab_entry, tab_roster = st.tabs(
        ["Student Drill-down", "Add / Edit Scores", "Manage Students"]
    )

    # ---------------- Drill-down ----------------
    with tab_drill:
        students = database.list_students()
        if not students:
            st.info("No students yet.")
        else:
            labels = [f"{s['name']} · {class_label(s['class_level'])} · {s['batch']}"
                      for s in students]
            choice = st.selectbox("Select a student", labels, key="drill_pick")
            sid = students[labels.index(choice)]["id"]
            if df.empty:
                st.info("No scores recorded yet.")
            else:
                render_dashboard(
                    df, role="student", student_id=sid,
                    subtitle=f"Drill-down · {choice}",
                )

    # ---------------- Score entry ----------------
    with tab_entry:
        render_score_entry(df)

    # ---------------- Roster ----------------
    with tab_roster:
        st.caption("Every student needs a unique email. An invitation lets them set a private "
                   "password in Supabase Auth; there is no shared or teacher-visible password.")
        with st.form("add_student_form", clear_on_submit=True):
            new_name = st.text_input("Full name", max_chars=120)
            r1, r2 = st.columns([1, 1])
            with r1:
                new_class = st.selectbox(
                    "Class", CLASS_LEVELS, format_func=class_label,
                    index=(CLASS_LEVELS.index(10) if 10 in CLASS_LEVELS else 0),
                    key="invite_class",
                    help="Decides which chapters this student can be marked "
                         "against.",
                )
            with r2:
                new_batch = st.text_input("Batch", max_chars=80,
                                          placeholder="Section A")
            new_email = st.text_input("Student email", max_chars=254)
            added = st.form_submit_button("Invite student by email", type="primary", width="stretch")
        if added:
            database.invite_student(new_name, new_batch, new_email, new_class)
            st.success("Invitation sent. The student can set their private password from the email link.")
        accounts = database.list_student_accounts()
        if accounts:
            st.markdown(card_head("Student accounts", "Disable access immediately without deleting historical marks."),
                        unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(accounts), hide_index=True, width="stretch")
            account_map = {s["id"]: s for s in accounts}
            with st.form("student_access_form"):
                chosen = st.selectbox("Student account", list(account_map),
                    format_func=lambda sid: f"{account_map[sid]['name']} · {account_map[sid]['email']}")
                enabled = st.selectbox("Access", ["Enabled", "Disabled"])
                update_access = st.form_submit_button("Update access")
            if update_access:
                database.set_student_active(chosen, enabled == "Enabled")
                st.success("Access updated. Disabling blocks database access immediately, including existing sessions.")
            # Plain widgets (not a form): switching student must re-sync the
            # class dropdown immediately via the change callback.
            def _sync_class_choice() -> None:
                level = account_map[st.session_state["edit_class_student"]]["class_level"]
                if level in CLASS_LEVELS:
                    st.session_state["edit_class_value"] = level
            cc1, cc2, cc3 = st.columns([1.5, 1, 1])
            with cc1:
                edit_student = st.selectbox(
                    "Student to update", list(account_map),
                    format_func=lambda sid: (
                        f"{account_map[sid]['name']} · {account_map[sid]['batch']}"
                    ),
                    key="edit_class_student",
                    on_change=_sync_class_choice,
                )
            with cc2:
                current_class = account_map[edit_student]["class_level"]
                edit_class = st.selectbox(
                    "New class", CLASS_LEVELS, format_func=class_label,
                    index=(CLASS_LEVELS.index(current_class)
                           if current_class in CLASS_LEVELS else 0),
                    key="edit_class_value",
                )
            with cc3:
                st.caption(" ")
                if st.button("Update class", key="save_class_btn"):
                    database.set_student_class(edit_student, edit_class)
                    st.success(
                        f"{account_map[edit_student]['name']} is now in "
                        f"{class_label(edit_class)}. Score entry uses the new "
                        "class's chapters from the next save."
                    )
        else:
            st.info("No student accounts yet. Invite your first student above.")



def _render_marksheet(students: list[dict], subjects: list[dict],
                      df: pd.DataFrame) -> None:
    """Whole-class fast entry: exam + chapters once, one marks grid, one save."""
    with_students = {int(s["class_level"]) for s in students}
    view = st.session_state.get("class_view", "All classes")
    level_from_view = (int(view.rsplit(" ", 1)[-1])
                       if view and view != "All classes" else None)
    default_level = (level_from_view if level_from_view in with_students
                     else next((lv for lv in CLASS_LEVELS if lv in with_students),
                               CLASS_LEVELS[0]))
    class_sel = st.selectbox(
        "Class for this marksheet", CLASS_LEVELS, format_func=class_label,
        index=CLASS_LEVELS.index(default_level), key="ms_class",
        help="Marks save class-by-class — every class has its own chapters.",
    )
    roster = [s for s in students if int(s["class_level"]) == class_sel]
    if not roster:
        st.info(f"No students in {class_label(class_sel)} yet — invite them "
                "in Manage Students first.")
        return
    if not subjects:
        st.info("Curriculum missing — ask the administrator to run the "
                "Supabase migration.")
        return

    subjects_by_name = {s["name"]: s for s in subjects}
    col_a, col_b = st.columns([1, 1])
    with col_a:
        subject = st.selectbox("Subject (filters chapters)",
                               list(subjects_by_name), key="ms_subject")
    with col_b:
        topics = database.topics_for_subject(subject, class_sel)
        st.caption(f"{class_label(class_sel)} · {len(topics)} chapters "
                   f"under {subject}")

    exams = database.list_exams()
    exam_labels = [f"{e['name']}  ·  {e['exam_date']}" for e in exams]
    new_exam = st.checkbox(
        "➕ Create a new exam / test", key="ms_new_exam",
        help="Chapters you tick stay remembered for this exam, so every "
             "student's row uses the same setup.",
    )
    if new_exam:
        e1, e2, e3 = st.columns([2, 1, 1])
        with e1:
            exam_name = st.text_input("Exam name", key="ms_exam_name",
                                      placeholder="Weekly Test 12 – Science")
        with e2:
            exam_date = st.date_input("Date", value=date.today(),
                                      key="ms_exam_date")
        with e3:
            exam_kind = st.selectbox(
                "Type", ["Weekly Test", "Monthly Exam", "Unit Test",
                         "Mock Exam"], key="ms_exam_kind")
        exam_key, exam_id = "new", None
        exam_date_value = exam_date.isoformat()
    else:
        if not exam_labels:
            st.warning("No exams exist yet — create a new exam above.")
            return
        exam_label = st.selectbox(
            "Exam", exam_labels, key="ms_exam",
            help="Chapters already scored on this exam come pre-ticked.",
        )
        chosen = exams[exam_labels.index(exam_label)]
        exam_key, exam_id = str(chosen["id"]), chosen["id"]
        exam_name = chosen["name"]
        exam_date_value, exam_kind = chosen["exam_date"], chosen["kind"]

    sub_id = subjects_by_name[subject]["id"]
    scored = (df[(df["exam_id"] == exam_id) & (df["subject_id"] == sub_id)]
              if exam_id is not None else df.iloc[0:0])
    default_topics = [t for t in topics if t in set(scored["topic"])]
    ticked = st.multiselect(
        "Chapters covered in this test", topics, default=default_topics,
        key=f"ms_topics_{exam_key}_{subject}",
        help="Tick every chapter this test covered — remembered for this exam.",
    )
    if not ticked:
        st.info("Tick the chapters this test covered — the marks grid "
                "appears below.")
        return

    outs: dict[str, float] = {}
    st.caption("Total marks per chapter — set once, applies to every student:")
    cols = st.columns(min(len(ticked), 3))
    for i, topic in enumerate(ticked):
        with cols[i % len(cols)]:
            prior = scored.loc[scored["topic"] == topic, "raw_max"].dropna()
            fallback = max(float(prior.iloc[-1]), 1.0) if len(prior) else 100.0
            outs[topic] = st.number_input(
                f"Out of · {topic}", min_value=1.0, value=fallback, step=1.0,
                key=f"ms_out_{exam_key}_{subject}_{topic}",
            )

    labels = [f"{s['name']} · {s['batch']} · ID {s['id']}" for s in roster]
    id_by_label = {lbl: int(s["id"]) for lbl, s in zip(labels, roster)}
    cells: dict[str, dict] = {}
    for label in labels:
        sid = id_by_label[label]
        row = {}
        for topic in ticked:
            match = scored[(scored["student_id"] == sid)
                           & (scored["topic"] == topic)]
            row[topic] = None
            if len(match):
                rec = match.iloc[-1]
                if pd.notna(rec["raw_score"]):
                    row[topic] = float(rec["raw_score"])
                else:
                    row[topic] = round(
                        float(rec["score"]) * outs[topic] / 100.0, 2)
        cells[label] = row
    grid = pd.DataFrame.from_dict(cells, orient="index")
    grid.index.name = "Student"

    st.caption("Type marks per cell — blank means 'not taken'. Existing "
               "scores come pre-filled; a blank cell keeps what was saved.")
    edited = st.data_editor(
        grid, key=f"ms_grid_{exam_key}_{subject}_{class_sel}",
        width="stretch", hide_index=False,
        column_config={
            topic: st.column_config.NumberColumn(
                topic, min_value=0.0, max_value=float(outs[topic]),
                step=0.5, format="%.2f",
            )
            for topic in ticked
        },
    )

    if st.button("💾 Save marksheet", key="ms_save", type="primary",
                 width="stretch"):
        if new_exam and not str(exam_name).strip():
            st.error("Please enter an exam name.")
            return
        topic_ids = database._topic_ids()
        records, conversions, errors = database.build_marksheet_records(
            edited, id_by_label, ticked, outs, topic_ids, subject, class_sel,
            str(exam_name).strip(), exam_date_value, exam_kind,
        )
        if errors:
            listed = "\n".join(f"- {e}" for e in errors[:8])
            more = "\n- …" if len(errors) > 8 else ""
            st.error(f"Fix these cells first:\n\n{listed}{more}")
            return
        if not records:
            st.info("No marks entered — type marks into the grid, then save.")
            return
        # One database transaction: every filled cell saves or none does.
        database.import_records(records)
        bump()
        detail = "; ".join(conversions[:3]) + \
            (" …" if len(conversions) > 3 else "")
        st.success(
            f"Saved {len(records)} mark(s) · {exam_name} · "
            f"{class_label(class_sel)} — {detail}"
        )


def render_score_entry(df: pd.DataFrame) -> None:
    students = database.list_students()
    subjects = database.list_subjects()

    notice = st.session_state.pop("score_notice", None)
    if notice:
        st.success(notice)

    mode = st.radio(
        "Entry mode", ["Class marksheet", "Single student"],
        horizontal=True, key="entry_mode",
        help="Marksheet = the whole class in one grid, one save. "
             "Single student = one pupil at a time.",
    )
    if mode == "Class marksheet":
        _render_marksheet(students, subjects, df)
        _render_recent_entries(df)
        return

    if not students or not subjects:
        st.info("Invite a student in Manage Students first. If the curriculum is missing, ask the administrator to run the Supabase migration.")
        return

    students_by_id = {s["id"]: s for s in students}

    # Student first: their class decides which chapters can be ticked.
    student_id = st.selectbox(
        "Student", list(students_by_id), key="entry_student",
        format_func=lambda sid: (
            f"{students_by_id[sid]['name']} · "
            f"{class_label(students_by_id[sid]['class_level'])} · "
            f"{students_by_id[sid]['batch']} · ID {sid}"
        ),
    )
    stu = students_by_id[student_id]
    class_level = int(stu["class_level"])

    subject_names = [s["name"] for s in subjects]
    col_a, col_b = st.columns([1, 1])
    with col_a:
        subject = st.selectbox(
            "Subject (filters topics)", subject_names, key="entry_subject",
            help="Pick a subject first — the topic list below updates to "
                 "its chapters.",
        )
    with col_b:
        topics = database.topics_for_subject(subject, class_level)
        st.caption(
            f"{class_label(class_level)} · {len(topics)} chapters under {subject}"
        )

    # Tick every chapter this test covered; one save records them all under
    # the same exam (student/exam/chapter upserts, one transaction).
    selected = st.multiselect(
        "Topics covered in this test", topics, key="entry_topics",
        help="One score row per ticked chapter. Untick chapters that were "
             "not part of this test.",
    )
    for topic in selected:
        mark_col, out_col = st.columns(2)
        with mark_col:
            st.number_input(
                f"Marks · {topic}", min_value=0.0, value=None, step=0.5,
                key=f"entry_mark_{topic}",
                help="Marks obtained — decimal marks allowed.",
            )
        with out_col:
            st.number_input(
                f"Out of · {topic}", min_value=1.0, value=100.0, step=1.0,
                key=f"entry_out_{topic}",
                help="Total marks for this chapter — not always 100. "
                     "The app stores the converted percentage.",
            )

    exams = database.list_exams()
    exam_labels = [f"{e['name']}  ·  {e['exam_date']}" for e in exams]

    # Outside the form so the new-exam fields appear immediately.
    new_exam = st.checkbox(
        "➕ Create a new exam / test", key="entry_new_exam",
        help="If two classes test on the same day, give each class its own "
             "exam name so the tests stay separate.",
    )
    with st.form("score_form"):
        if new_exam:
            e1, e2, e3 = st.columns([2, 1, 1])
            with e1:
                exam_name = st.text_input("Exam name",
                                          placeholder="Weekly Test 12 – Science")
            with e2:
                exam_date = st.date_input("Date", value=date.today())
            with e3:
                exam_kind = st.selectbox(
                    "Type",
                    ["Weekly Test", "Monthly Exam", "Unit Test", "Mock Exam"],
                )
        else:
            if not exam_labels:
                st.warning("No exams exist yet — create a new exam above.")
                exam_name, exam_date, exam_kind, exam_label = "", None, "", ""
            exam_label = st.selectbox("Exam", exam_labels) if exam_labels else ""
        saved = st.form_submit_button(
            "💾 Save score(s)", type="primary", width="stretch",
        )

    if saved:
        # Never resolve a roster record by name: names may be duplicated.
        stu_name = stu["name"]
        if not selected:
            st.error("Tick at least one topic covered by this test.")
            return
        rows = []
        for topic in selected:
            marks = st.session_state.get(f"entry_mark_{topic}")
            out_of = float(st.session_state.get(f"entry_out_{topic}") or 0)
            if marks is None:
                st.error(f"Enter the marks obtained for {topic}.")
                return
            marks = float(marks)
            if out_of <= 0 or marks < 0 or marks > out_of:
                st.error(f"{topic}: marks must be between 0 and the total "
                         f"({out_of:g}).")
                return
            rows.append((topic, marks, out_of))
        if new_exam:
            if not exam_name.strip():
                st.error("Please enter an exam name.")
                return
            exam_name_value = exam_name.strip()
            exam_date_value = exam_date.isoformat()
            exam_kind_value = exam_kind
        else:
            if not exam_label:
                st.error("Please select or create an exam.")
                return
            existing = exams[exam_labels.index(exam_label)]
            exam_name_value = existing["name"]
            exam_date_value = existing["exam_date"]
            exam_kind_value = existing["kind"]
        topic_ids = database._topic_ids()
        records, conversions = [], []
        for topic, marks, out_of in rows:
            percent = round(marks / out_of * 100.0, 2)
            tid, sub_id = topic_ids[(class_level, subject, topic)]
            records.append({
                "student_id": int(stu["id"]), "subject_id": sub_id,
                "topic_id": tid, "exam": exam_name_value,
                "exam_date": exam_date_value, "exam_kind": exam_kind_value,
                "score": percent, "raw_score": marks, "raw_max": out_of,
            })
            conversions.append(f"{topic} {marks:g}/{out_of:g} → {percent:g}%")
        # One database transaction: every ticked chapter saves or none does.
        database.import_records(records)
        bump()
        detail = "; ".join(conversions[:3]) + (" …" if len(conversions) > 3 else "")
        st.success(
            f"Saved {len(records)} topic(s) for {stu_name} "
            f"({class_label(class_level)}) — {detail}"
        )

    _render_recent_entries(df)


def _render_recent_entries(df: pd.DataFrame) -> None:
    # ---------------- Edit / delete recent ----------------
    st.markdown('<div class="side-sep"></div>', unsafe_allow_html=True)
    st.markdown(card_head("Recent entries",
                          "Edit a score inline, or remove entries below"),
                unsafe_allow_html=True)
    recent = database.recent_scores(120)
    if recent.empty:
        st.caption("No scores yet.")
        return
    display = recent[["score_id", "student", "exam", "exam_date",
                      "subject", "topic", "score", "marks"]].copy()
    original = display.set_index("score_id")["score"].to_dict()

    edited = st.data_editor(
        display,
        column_config={
            "score_id": None,
            "student": st.column_config.TextColumn("Student", width="medium"),
            "exam": st.column_config.TextColumn("Exam", width="medium"),
            "exam_date": st.column_config.TextColumn("Date", width="small"),
            "subject": st.column_config.TextColumn("Subject", width="small"),
            "topic": st.column_config.TextColumn("Topic", width="medium"),
            "score": st.column_config.NumberColumn(
                "Score (%)", min_value=0, max_value=100, step=1, width="small",
            ),
            "marks": st.column_config.TextColumn(
                "Raw marks", width="small",
                help="Marks as entered (e.g. 15/20). Editing the percentage "
                     "directly clears the raw marks.",
            ),
        },
        disabled=["student", "exam", "exam_date", "subject", "topic", "marks"],
        hide_index=True,
        width="stretch",
        key="score_editor",
    )

    changed = 0
    for _, row in edited.iterrows():
        sid_ = row["score_id"]
        if pd.isna(sid_):
            continue
        old = original.get(int(sid_))
        if old is not None and float(row["score"]) != float(old):
            database.update_score_value(int(sid_), float(row["score"]))
            changed += 1
    if changed:
        bump()
        st.session_state["score_notice"] = f"Updated {changed} score(s)."
        st.rerun()

    del_choice = st.multiselect(
        "Select entries to delete",
        options=display["score_id"].tolist(),
        format_func=lambda i: (
            f"{display.loc[display.score_id == i, 'student'].iloc[0]} · "
            f"{display.loc[display.score_id == i, 'exam'].iloc[0]} · "
            f"{display.loc[display.score_id == i, 'subject'].iloc[0]} → "
            f"{display.loc[display.score_id == i, 'topic'].iloc[0]}"
        ),
        key="del_picks",
    )
    if del_choice and st.button("🗑 Delete selected", key="del_btn"):
        database.delete_scores(del_choice)
        bump()
        st.success(f"Deleted {len(del_choice)} entr"
                   f"{'y' if len(del_choice) == 1 else 'ies'}.")
        st.rerun()



# ---------------------------------------------------------------------------
# Teacher: Bulk upload & reports
# ---------------------------------------------------------------------------


def render_upload_page(df: pd.DataFrame) -> None:
    threshold = int(st.session_state.get("threshold", 70))
    st.markdown(page_head(
        "Bulk Upload & Reports",
        "Import CSV/Excel score sheets with validation, export one-click reports",
    ), unsafe_allow_html=True)

    c1, c2 = st.columns([1, 1], gap="medium")

    with c1:
        with st.container(border=True):
            st.markdown(card_head(
                "📤 Upload scores",
                "Columns: student, subject, topic, exam, exam_date, score "
                "(optional: exam_kind). Chapters are matched to each "
                "student's class.",
            ), unsafe_allow_html=True)
            template = (
                "student,subject,topic,exam,exam_date,exam_kind,score\n"
                "student1@school.edu,Mathematics,Quadratic Equations,"
                "Weekly Test 12,2026-12-05,Weekly Test,82\n"
                "student2@school.edu,Science,Electricity,Weekly Test 12,"
                "2026-12-05,Weekly Test,67\n"
            )
            st.download_button(
                "⬇️ Download CSV template", template,
                file_name="exam_upload_template.csv", mime="text/csv",
                width="stretch",
            )
            uploaded = st.file_uploader(
                "CSV or Excel file", type=["csv", "xlsx"],
                label_visibility="collapsed",
            )
            if uploaded is not None:
                if uploaded.size > 5 * 1024 * 1024:
                    st.error("Upload a file of at most 5 MB.")
                    return
                try:
                    raw = read_score_upload(uploaded.getvalue(), uploaded.name)
                except ValueError as error:
                    st.error(str(error))
                    raw = None
                except Exception:
                    st.error("This file could not be read. Use a UTF-8 CSV or unencrypted XLSX matching the template.")
                    raw = None
                if raw is not None:
                    records, errors = database.resolve_upload(raw)
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Rows", len(raw))
                    m2.metric("Valid", len(records))
                    m3.metric("Errors", len(errors))
                    if errors:
                        st.caption("Fix these rows and re-upload:")
                        st.dataframe(pd.DataFrame(errors),
                                     width="stretch",
                                     hide_index=True)
                    if records and not errors:
                        if st.button(
                            f"✅ Import {len(records)} valid rows",
                            type="primary", width="stretch",
                            key="import_btn",
                        ):
                            n = database.import_records(records)
                            bump()
                            st.success(f"Imported {n} score rows successfully.")
                            st.rerun()

    with c2:
        with st.container(border=True):
            st.markdown(card_head(
                "📥 One-click reports",
                f"Exports reflect the current {threshold}% mastery threshold",
            ), unsafe_allow_html=True)
            if df.empty:
                st.caption("No data to export yet.")
            else:
                report = df.copy()
                report["status"] = report["score"].apply(
                    lambda v: band(v, threshold)[1]
                )
                report_csv = (
                    report[["student_name", "batch", "class_level", "exam_name",
                            "exam_date", "exam_kind", "subject", "topic",
                            "score", "raw_score", "raw_max", "status"]]
                    .rename(columns={
                        "student_name": "student", "class_level": "class",
                        "raw_score": "marks", "raw_max": "out_of",
                        "exam_name": "exam", "exam_date": "date",
                        "exam_kind": "type",
                    })
                    .pipe(database.export_csv)
                ).encode("utf-8-sig")
                st.download_button(
                    "⬇️ Full scores report (CSV)", report_csv,
                    file_name="examscores_report.csv", mime="text/csv",
                    width="stretch", key="dl_full",
                )

                summary = _student_overview(df, threshold).rename(columns={
                    "Average %": "average_score",
                    "Weak topics": "weak_topics",
                    "Weakest topic": "weakest_topic",
                })
                st.download_button(
                    "⬇️ Class summary by student (CSV)",
                    database.export_csv(summary).encode("utf-8-sig"),
                    file_name="class_summary.csv", mime="text/csv",
                    width="stretch", key="dl_summary",
                )
                st.markdown(
                    '<div class="pb-legend">Reports include every exam, topic '
                    "breakdown and the live status pill for each score.</div>",
                    unsafe_allow_html=True,
                )

    # quick glance: weakness hotspots
    with st.container(border=True):
        st.markdown(card_head(
            "Class-wide weakness analytics",
            "Subjects/topics with the lowest class average (below threshold "
            "shown in coral)",
        ), unsafe_allow_html=True)
        if df.empty:
            st.caption("No data yet.")
        else:
            stats = topic_stats(df, threshold)
            worst = stats.head(8)
            pairs = list(zip(worst["topic"], worst["avg"]))
            st.markdown(progress_bars_html(pairs, threshold),
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Schedule (teacher manage / student view)
# ---------------------------------------------------------------------------

def render_schedule_page(role: str, df: pd.DataFrame,
                         user: dict | None = None) -> None:
    threshold = int(st.session_state.get("threshold", 70))
    is_teacher = role == "teacher"
    st.markdown(page_head(
        "Schedule" if is_teacher else "Upcoming Tests",
        "Plan tests and revision targets" if is_teacher
        else "Your upcoming tests and revision priorities",
    ), unsafe_allow_html=True)

    c1, c2 = st.columns([1.25, 1], gap="medium")

    with c1:
        with st.container(border=True):
            st.markdown(card_head(
                "Upcoming tests" if is_teacher
                else "Upcoming Tests",
                "Newest dates first" if is_teacher else None,
            ), unsafe_allow_html=True)
            st.markdown(schedule_html(upcoming_items(12)), unsafe_allow_html=True)

            if is_teacher:
                st.markdown('<div class="side-sep"></div>',
                            unsafe_allow_html=True)
                subject_opts = ["General / All subjects"] + [s["name"] for s in database.list_subjects()]
                subj = st.selectbox("Test subject", subject_opts, key="schedule_subject")
                sch_class = None
                if subj != "General / All subjects":
                    sch_class = st.selectbox(
                        "Class", CLASS_LEVELS, format_func=class_label,
                        index=(CLASS_LEVELS.index(10) if 10 in CLASS_LEVELS else 0),
                        key="schedule_class",
                    )
                    chapter_options = [""] + database.topics_for_subject(subj, sch_class)
                else:
                    chapter_options = [""]
                with st.form("add_test_form"):
                    st.markdown(card_head("Add a test date"), unsafe_allow_html=True)
                    title = st.text_input("Title", placeholder="Mathematics – Probability Quiz", max_chars=160)
                    tdate = st.date_input("Date", value=date.today())
                    topic = st.selectbox("Chapter", chapter_options,
                                         format_func=lambda value: value or "All chapters / general")
                    notes = st.text_input(
                        "Batch / notes (optional)",
                        placeholder="Grade 10 – A & B",
                    )
                    added = st.form_submit_button(
                        "➕ Add to calendar", type="primary",
                        width="stretch",
                    )
                if added:
                    if not title.strip():
                        st.error("Title is required.")
                    else:
                        database.add_upcoming(
                            title, tdate.isoformat(),
                            database.subject_name_to_id(subj), topic, notes,
                            class_level=sch_class if topic else None,
                        )
                        st.success(f"Scheduled “{title.strip()}” "
                                   f"on {tdate.strftime('%d %b %Y')}.")
                        st.rerun()

                # delete entries
                all_items = database.list_upcoming()
                upcoming = [
                    t for t in all_items
                    if t["test_date"][:10] >= date.today().isoformat()
                ]
                if upcoming:
                    st.markdown('<div class="side-sep"></div>',
                                unsafe_allow_html=True)
                    st.markdown(card_head("Remove a scheduled test"),
                                unsafe_allow_html=True)
                    choice = st.selectbox(
                        "Scheduled test", upcoming,
                        format_func=lambda t: f"{t['title']} · {t['test_date']}",
                        key="del_test_pick",
                    )
                    if st.button("🗑 Delete test", key="del_test_btn",
                                 width="stretch"):
                        database.delete_upcoming(choice["id"])
                        st.success("Deleted.")
                        st.rerun()

    with c2:
        if is_teacher:
            with st.container(border=True):
                st.markdown(card_head(
                    "Revision hotspots",
                    "Weakest class topics — target these before the next test",
                ), unsafe_allow_html=True)
                if df.empty:
                    st.caption("No data yet.")
                else:
                    rows = focus_rows(df, threshold, limit=6)
                    st.markdown(leaderboard_html(rows), unsafe_allow_html=True)
        else:
            with st.container(border=True):
                st.markdown(card_head(
                    "🎯 Revision targets",
                    "Topics below your mastery threshold — revise these first",
                ), unsafe_allow_html=True)
                if df.empty or user is None:
                    st.caption("No data yet.")
                else:
                    sdf = df[df["student_id"] == user["student_id"]]
                    if sdf.empty:
                        st.caption("No scores yet.")
                    else:
                        rows = focus_rows(sdf, threshold, limit=6)
                        st.markdown(leaderboard_html(rows),
                                    unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Student: My Progress
# ---------------------------------------------------------------------------

def render_my_progress(df: pd.DataFrame, user: dict) -> None:
    threshold = int(st.session_state.get("threshold", 70))
    sdf = df[df["student_id"] == user["student_id"]].copy()
    st.markdown(page_head(
        "My Progress",
        f"Personal trends, subject breakdown and weak-area plan · "
        f"{user.get('batch', '')}",
    ), unsafe_allow_html=True)

    if sdf.empty:
        st.info("No scores recorded for you yet.")
        return

    st.markdown(kpi_row(build_kpi_cards(sdf, "student", threshold)),
                unsafe_allow_html=True)

    left, right = st.columns([1.5, 1], gap="medium")

    with left:
        with st.container(border=True):
            st.markdown(card_head("Performance over time",
                                  "Your score progression vs. target"),
                        unsafe_allow_html=True)
            subjects = ["All Subjects"] + sorted(sdf["subject"].unique().tolist())
            subject = st.selectbox("Subject", subjects, key="mp_subject")
            fig = area_trend_chart(
                sdf, subject, float(TARGET_SCORE),
                f"Target {TARGET_SCORE}%", height=320, theme=theme_mode(),
            )
            st.plotly_chart(fig, width="stretch", theme=None,
                            config=CHART_CONFIG, key="mp_trend")

    with right:
        with st.container(border=True):
            st.markdown(card_head("Snapshot"), unsafe_allow_html=True)
            stats = topic_stats(sdf, threshold)
            best = stats.iloc[-1] if not stats.empty else None
            worst = stats.iloc[0] if not stats.empty else None
            series = _exam_avg_series(sdf)
            latest = float(series.iloc[-1]) if len(series) else 0.0
            snap = [
                ("Tests taken", f"{sdf['exam_id'].nunique()}"),
                ("Personal average", f"{sdf['score'].mean():.1f}%"),
                ("Latest test", f"{latest:.1f}%"),
                ("Strongest topic",
                 f"{best['topic']} ({best['avg']:.0f}%)" if best is not None else "—"),
                ("Focus topic",
                 f"{worst['topic']} ({worst['avg']:.0f}%)" if worst is not None else "—"),
            ]
            rows_html = "".join(
                f'<div class="lb-row" style="justify-content:space-between">'
                f'<div class="lb-info"><div class="lb-meta">{k}</div>'
                f'<div class="lb-name">{v}</div></div></div>'
                for k, v in snap
            )
            st.markdown(f'<div class="lb-list">{rows_html}</div>',
                        unsafe_allow_html=True)

    b1, b2 = st.columns([1, 1], gap="medium")

    with b1:
        with st.container(border=True):
            st.markdown(card_head("Mastery breakdown",
                                  "Mastery color scale, weakest first"),
                        unsafe_allow_html=True)
            view = st.radio("Breakdown", ["By Subject", "By Topic"],
                            horizontal=True, key="mp_bars",
                            label_visibility="collapsed")
            if view == "By Subject":
                g = (sdf.groupby("subject")["score"].mean()
                     .sort_values().reset_index())
                pairs = list(zip(g["subject"], g["score"]))
            else:
                pairs = list(zip(stats["topic"], stats["avg"]))
            st.markdown(progress_bars_html(pairs, threshold),
                        unsafe_allow_html=True)

    with b2:
        with st.container(border=True):
            st.markdown(card_head(
                "Weak-area recommendations",
                f"Every topic averaging under {threshold}%",
            ), unsafe_allow_html=True)
            weak = stats[stats["avg"] < threshold]
            if weak.empty:
                st.markdown(
                    '<div class="lb-list"><div class="lb-row">'
                    '<div class="lb-info"><div class="lb-name">🎉 All topics '
                    'at or above mastery</div>'
                    '<div class="lb-meta">Keep the streak going — try harder '
                    'practice sets next.</div></div></div></div>',
                    unsafe_allow_html=True,
                )
            else:
                rec_rows = []
                for i, (_, r) in enumerate(weak.head(6).iterrows(), start=1):
                    gap = threshold - r["avg"]
                    rec_rows.append({
                        "rank": i,
                        "name": r["topic"],
                        "meta": (f"{r['subject']} · {r['avg']:.0f}% · "
                                 f"{gap:.0f} pts below mastery"),
                        "pill": r["label"], "pill_class": r["pill"],
                    })
                st.markdown(leaderboard_html(rec_rows), unsafe_allow_html=True)
                st.markdown(
                    '<div class="pb-legend">Suggested plan: 20 minutes of '
                    "targeted questions per flagged topic, then re-test.</div>",
                    unsafe_allow_html=True,
                )

    with st.container(border=True):
        st.markdown(card_head("Recent tests"), unsafe_allow_html=True)
        recent = (sdf.groupby(["exam_name", "exam_date"], as_index=False)
                  ["score"].mean()
                  .sort_values("exam_date", ascending=False).head(8))
        recent["score"] = recent["score"].round(1)
        recent["status"] = recent["score"].apply(
            lambda v: band(v, threshold)[1]
        )
        recent.columns = ["Exam", "Date", "Score", "Status"]
        recent["Date"] = pd.to_datetime(recent["Date"]).dt.strftime("%d %b %Y")
        st.dataframe(recent, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Student: deliberate read-only access to peer exam marks
# ---------------------------------------------------------------------------

def render_student_comparison(user: dict) -> None:
    st.markdown(page_head(
        "Student Comparison",
        "Compare exam marks across students · your score is highlighted in purple",
    ), unsafe_allow_html=True)
    st.caption("This comparison page shares exam marks and student names. Your "
               "Dashboard and My Progress pages still show only your own records.")
    exams = database.list_exams()
    if not exams:
        st.info("No exams have been created yet.")
        return
    exam_map = {e["id"]: e for e in exams}
    exam_id = st.selectbox(
        "Choose an exam", list(exam_map), key="comparison_exam",
        format_func=lambda eid: (
            f"{exam_map[eid]['name']} · {exam_map[eid]['exam_date']}"
        ),
    )
    subjects = {s["id"]: s["name"] for s in database.list_subjects()}
    subject_id = st.selectbox(
        "Subject", [None, *subjects], key="comparison_subject",
        format_func=lambda sid: "All subjects" if sid is None else subjects[sid],
    )
    topic_id = None
    if subject_id is not None:
        topics = {
            tid: f"{class_label(level)} · {name}"
            for (level, subject, name), (tid, sid) in database._topic_ids().items()
            if sid == subject_id
        }
        topic_id = st.selectbox(
            "Topic / Chapter", [None, *topics],
            key=f"comparison_topic_{subject_id}",
            format_func=lambda tid: "All topics" if tid is None else topics[tid],
        )
    summary = database.exam_comparison(exam_id, subject_id, topic_id)
    marked = summary.dropna(subset=["score"])
    st.caption(
        "Marks are percentages. When multiple topics are selected, each bar is "
        "the mean of that student's recorded topic marks, not a total. Missing "
        "marks are excluded, not counted as zero. Use the topic filter for a "
        "like-for-like comparison; topic counts can differ between students."
    )
    if marked.empty:
        st.info("No marks recorded for this exam and selection yet.")
    else:
        my_marks = marked[marked["student_id"] == user.get("student_id")]
        if my_marks.empty:
            st.info("Your marks have not been recorded for this selection yet. "
                    "You can still compare the available results below.")
        else:
            st.success(f"Your score: {my_marks['score'].iloc[0]:.1f}%")
        with st.container(border=True):
            st.markdown(card_head(
                "Exam marks — all students",
                f"{len(marked)} with marks · {len(summary) - len(marked)} not recorded",
            ), unsafe_allow_html=True)
            chart_data = marked.sort_values(["score", "student_name", "student_id"], ascending=[False, True, True]).reset_index(drop=True)
            if len(chart_data) > 25:
                pages = list(range((len(chart_data) + 24) // 25))
                page_number = st.selectbox("Chart page", pages,
                    format_func=lambda p: f"{p * 25 + 1}–{min((p + 1) * 25, len(chart_data))} of {len(chart_data)} students")
                own_position = chart_data.index[chart_data["student_id"] == user.get("student_id")].tolist()
                if own_position:
                    st.caption(f"Your result is on chart page {own_position[0] // 25 + 1}.")
                chart_data = chart_data.iloc[page_number * 25:(page_number + 1) * 25]
            st.plotly_chart(
                student_comparison_chart(chart_data, user.get("student_id"), theme=theme_mode()),
                width="stretch", theme=None, config=CHART_CONFIG, key="comparison_chart",
            )
    # All roster members are listed, including absent/not-yet-entered marks.
    table = summary[["student_name", "batch", "score", "topic_count"]].copy()
    table["score"] = table["score"].round(1)
    table["Status"] = summary["score"].apply(
        lambda value: "Not recorded" if pd.isna(value) else "Recorded"
    )
    table.columns = ["Student", "Batch", "Mark (%)", "Topics recorded", "Status"]
    st.dataframe(table, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    init_theme()
    inject_css()
    render_app_chrome()
    try:
        load_settings()
    except ConfigurationError as error:
        render_setup(str(error))
        return

    try:
        if auth.consume_email_link():
            _start_session(st.session_state["user"])
    except CloudError as error:
        st.session_state["auth_notice"] = str(error)
    user = auth.ensure_session()
    if not user:
        render_login()
        return
    if "nav" not in st.session_state:
        _start_session(user)
    if st.session_state.get("password_setup"):
        render_password_form(user, setup=True)
        return
    render_sidebar(user)
    notice = st.session_state.pop("account_notice", None)
    if notice:
        st.success(notice)
    page = st.session_state.get("nav")
    if page == "🔐 Account & Security":
        render_password_form(user)
        return
    scores = get_scores()  # PostgreSQL RLS enforces ownership before data leaves Supabase.
    if user["role"] != "teacher":
        scores = scores[scores["student_id"] == user.get("student_id")].copy()
        roster_scores = scores
    else:
        # Sidebar class view scopes analytics pages; the roster page (drill-down,
        # entry, accounts) always sees every class.
        roster_scores = scores
        view = st.session_state.get("class_view", "All classes")
        if view != "All classes" and not scores.empty:
            level = int(view.rsplit(" ", 1)[-1])
            scores = scores[scores["class_level"] == level].copy()
    if user["role"] == "teacher":
        if page == TEACHER_PAGES[1]:
            render_students_page(roster_scores)
        elif page == TEACHER_PAGES[2]:
            render_upload_page(scores)
        elif page == TEACHER_PAGES[3]:
            render_schedule_page("teacher", scores, user)
        else:
            render_dashboard(scores, "teacher")
    else:
        if page == STUDENT_PAGES[1]:
            render_my_progress(scores, user)
        elif page == STUDENT_PAGES[2]:
            render_schedule_page("student", scores, user)
        elif page == STUDENT_PAGES[3]:
            render_student_comparison(user)
        else:
            render_dashboard(scores, "student", user.get("student_id"))


def main() -> None:
    try:
        _main()
    except (CloudError, ValueError) as error:
        st.error(str(error))
        if st.button("Refresh safely", key="retry_request"):
            st.rerun()
    except Exception as error:
        # Never render raw exceptions, Auth responses, URLs or tokens to clients.
        import logging
        import uuid
        incident = uuid.uuid4().hex[:12]
        logging.getLogger(__name__).error("Application incident=%s type=%s", incident, type(error).__name__)
        st.error(f"The request could not be completed. Contact the administrator with reference {incident}.")


main()
