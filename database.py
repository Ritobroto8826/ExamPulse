"""Supabase/PostgreSQL repository. Every request uses the caller's JWT + RLS.

No local SQLite fallback, runtime schema creation, demo seeding or privileged key.
Schema/permissions are deployed separately from supabase/migrations/.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
import math
import re
import pandas as pd
import auth
from cloud import CloudError

SCORE_COLUMNS = ["score_id", "student_id", "student_name", "batch", "class_level",
                 "exam_id", "exam_name", "exam_date", "exam_kind", "subject_id",
                 "subject", "topic_id", "topic", "score", "max_score",
                 "raw_score", "raw_max"]


def init_db() -> None:
    """Compatibility entry point: NEVER changes a production database at startup."""


def list_students() -> list[dict]:
    return auth.client().rows("students", {"select": "id,name,batch,class_level,email,joined_date",
                                           "order": "class_level,batch,name,id"})


def list_student_accounts() -> list[dict]:
    return auth.client().rows("student_access", {"select": "id,name,batch,class_level,email,active",
                                                 "order": "class_level,batch,name,id"})


def invite_student(name: str, batch: str, email: str, class_level: int) -> None:
    name, batch, email = name.strip(), batch.strip(), email.strip().lower()
    if not 1 <= len(name) <= 120 or not 1 <= len(batch) <= 80:
        raise ValueError("Name and batch are required (maximum 120 and 80 characters).")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        raise ValueError("A valid, unique student email address is required.")
    level = _validate_class_level(class_level)
    auth.client().request("POST", "/functions/v1/manage-students",
                          body={"name": name, "batch": batch, "email": email, "class_level": level})


def set_student_active(student_id: int, active: bool) -> None:
    auth.client().rpc("set_student_active", {"p_student_id": int(student_id), "p_active": bool(active)})


def set_student_class(student_id: int, class_level: int) -> None:
    level = _validate_class_level(class_level)
    auth.client().rest("PATCH", "students", params={"id": f"eq.{int(student_id)}"},
                       body={"class_level": level})


def _validate_class_level(class_level) -> int:
    try:
        level = int(class_level)
    except (TypeError, ValueError):
        raise ValueError("Choose a class for this student.") from None
    if not 1 <= level <= 12:
        raise ValueError("Class must be between 1 and 12.")
    return level


def get_student(student_id: int):
    rows = auth.client().rows("students", {"id": f"eq.{int(student_id)}",
                                           "select": "id,name,batch,class_level,email,joined_date"})
    return rows[0] if rows else None


def students_joined_since(days: int) -> int:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return len(auth.client().rows("students", {"select": "id", "joined_date": f"gte.{cutoff}"}))


def list_subjects() -> list[dict]:
    return auth.client().rows("subjects", {"select": "id,name", "order": "position"})


def topics_for_subject(subject_name: str, class_level: int | None = None) -> list[str]:
    subjects = list_subjects()
    sid = next((s["id"] for s in subjects if s["name"] == subject_name), None)
    if sid is None:
        return []
    params = {"select": "name", "subject_id": f"eq.{sid}", "order": "class_level,position"}
    if class_level is not None:
        params["class_level"] = f"eq.{int(class_level)}"
    return [r["name"] for r in auth.client().rows("topics", params)]


def _topic_ids() -> dict[tuple[int, str, str], tuple[int, int]]:
    """(class_level, subject, chapter) -> (topic_id, subject_id). Chapter names
    repeat across classes, so the class is part of the key."""
    subjects = {s["id"]: s["name"] for s in list_subjects()}
    rows = auth.client().rows("topics", {"select": "id,subject_id,name,class_level",
                                         "order": "class_level,subject_id,position"})
    return {(int(r["class_level"]), subjects[r["subject_id"]], r["name"]):
            (r["id"], r["subject_id"]) for r in rows}


def list_exams() -> list[dict]:
    return auth.client().rows("exams", {"select": "id,name,exam_date,kind", "order": "exam_date.desc,id.desc"})


def delete_exam(exam_id: int, include_scores: bool = False) -> None:
    """Remove an exam from the entry dropdowns. The database refuses when the
    exam still has marks unless include_scores is set."""
    auth.client().rpc("delete_exam", {"p_exam_id": int(exam_id),
                                     "p_include_scores": bool(include_scores)})


def _score_frame(rows) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=SCORE_COLUMNS)
    frame["exam_date"] = pd.to_datetime(frame["exam_date"])
    for key in ("score", "max_score", "raw_score", "raw_max"):
        frame[key] = pd.to_numeric(frame[key]).astype(float)
    return frame


def load_scores_df() -> pd.DataFrame:
    # The security-invoker view inherits RLS, even if a caller removes UI filters.
    rows = auth.client().rows("score_details", {"select": ",".join(SCORE_COLUMNS), "order": "exam_date,score_id"})
    return _score_frame(rows)


def exam_comparison(exam_id: int, subject_id: int | None = None,
                    topic_id: int | None = None) -> pd.DataFrame:
    rows = auth.client().rpc_rows("exam_comparison", {"p_exam_id": int(exam_id),
                            "p_subject_id": int(subject_id) if subject_id is not None else None,
                            "p_topic_id": int(topic_id) if topic_id is not None else None})
    frame = pd.DataFrame(rows, columns=["student_id", "student_name", "batch", "score", "topic_count"])
    frame["score"] = pd.to_numeric(frame["score"]).astype(float)
    return frame


def update_score_value(score_id: int, score: float) -> None:
    if not math.isfinite(float(score)) or not 0 <= float(score) <= 100:
        raise ValueError("Score must be between 0 and 100.")
    # A manual percentage edit supersedes any stored raw marks (15/20 -> 75).
    auth.client().rest("PATCH", "scores", params={"id": f"eq.{int(score_id)}"},
                       body={"score": float(score), "raw_score": None, "raw_max": None})


def delete_scores(score_ids: list[int]) -> None:
    # Bounded URL length; no untrusted string interpolation into SQL.
    for start in range(0, len(score_ids), 100):
        ids = ",".join(str(int(i)) for i in score_ids[start:start + 100])
        auth.client().rest("DELETE", "scores", params={"id": f"in.({ids})"})


def recent_scores(limit: int = 120) -> pd.DataFrame:
    rows = auth.client().rest("GET", "score_details", params={
        "select": "score_id,student_name,exam_name,exam_date,subject,topic,score,raw_score,raw_max",
        "order": "exam_date.desc,score_id.desc", "limit": int(limit)})
    frame = pd.DataFrame(rows, columns=["score_id", "student_name", "exam_name", "exam_date",
                                        "subject", "topic", "score", "raw_score", "raw_max"])
    frame["score"] = pd.to_numeric(frame["score"]).astype(float)
    frame["raw_score"] = pd.to_numeric(frame["raw_score"])
    frame["raw_max"] = pd.to_numeric(frame["raw_max"])
    frame["marks"] = [
        f"{m:g}/{o:g}" if pd.notna(m) and pd.notna(o) else ""
        for m, o in zip(frame["raw_score"], frame["raw_max"])
    ]
    return frame.rename(columns={"student_name": "student", "exam_name": "exam"})


def import_records(records: list[dict]) -> int:
    if not records:
        return 0
    if len(records) > 1000:
        raise ValueError("Import at most 1,000 rows per file.")
    saved = auth.client().rpc("import_score_records", {"p_records": records})
    if saved is None:
        # An empty RPC body would crash int(None); treat it as unconfirmed.
        raise CloudError(
            "The save was not confirmed by the database. Refresh to check "
            "whether the marks landed before retrying."
        )
    return int(saved)


def build_marksheet_records(edited: pd.DataFrame, id_by_label: dict[str, int],
                            ticked: list[str], outs: dict[str, float],
                            topic_ids: dict, subject: str, class_level: int,
                            exam_name: str, exam_date: str, exam_kind: str,
                            ) -> tuple[list[dict], list[str], list[str]]:
    """Class marksheet grid -> import_score_records payload.

    Blank cells are skipped (they keep whatever was saved before); every
    filled cell must sit between 0 and its chapter's 'out of' value. Returns
    (records, conversions, errors) — callers refuse to save while errors
    exist so one bad cell never lands half a class.
    """
    records, conversions, errors = [], [], []
    for label, row in edited.iterrows():
        student_id = id_by_label.get(label)
        if student_id is None:
            continue
        who = str(label).split(" · ")[0]
        for topic in ticked:
            value = row[topic] if topic in edited.columns else None
            if value is None or pd.isna(value):
                continue
            try:
                marks = float(value)
            except (TypeError, ValueError):
                errors.append(f"{who} · {topic}: {value!r} is not a number")
                continue
            out_of = float(outs.get(topic, 0) or 0)
            if out_of <= 0:
                errors.append(f"{topic}: 'out of' must be above 0")
                continue
            if not math.isfinite(marks) or marks < 0 or marks > out_of:
                errors.append(f"{who} · {topic}: {marks:g} must be between 0 and {out_of:g}")
                continue
            topic_id, subject_id = topic_ids[(class_level, subject, topic)]
            percent = round(marks / out_of * 100.0, 2)
            records.append({
                "student_id": int(student_id), "subject_id": int(subject_id),
                "topic_id": int(topic_id), "exam": exam_name,
                "exam_date": exam_date, "exam_kind": exam_kind,
                "score": percent, "raw_score": marks, "raw_max": out_of,
            })
            conversions.append(f"{topic} {marks:g}/{out_of:g} → {percent:g}%")
    return records, conversions, errors


def resolve_upload(raw: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = ["student", "subject", "topic", "exam", "exam_date", "score"]
    missing = [c for c in required if c not in df.columns]
    if missing or df.columns.duplicated().any():
        return [], [{"row": "-", "field": ",".join(missing), "error": "Missing or duplicate columns. Download the template."}]
    if len(df) > 1000:
        return [], [{"row": "-", "field": "file", "error": "Import at most 1,000 rows per file."}]
    students = list_students()
    emails = {s["email"].casefold(): s["id"] for s in students}
    student_class = {s["id"]: int(s["class_level"]) for s in students}
    names = {}
    for student in students:
        names.setdefault(student["name"].casefold(), []).append(student["id"])
    topic_map = {(cl, s.casefold(), t.casefold()): (tid, sid)
                 for (cl, s, t), (tid, sid) in _topic_ids().items()}
    records, errors, seen = [], [], set()
    for index, (_, row) in enumerate(df.iterrows(), 2):
        def error(field, message):
            errors.append({"row": index, "field": field, "error": message})
        target = str(row["student"]).strip().casefold()
        sid = emails.get(target)
        if sid is None:
            matches = names.get(target, [])
            if len(matches) != 1:
                error("student", "Use a registered student email; the name is unknown or ambiguous.")
                continue
            sid = matches[0]
        subject, topic = str(row["subject"]).strip(), str(row["topic"]).strip()
        ids = topic_map.get((student_class[sid], subject.casefold(), topic.casefold()))
        if ids is None:
            error("topic", "Select a chapter from this student's class curriculum "
                           "(Mathematics/Science).")
            continue
        exam = str(row["exam"]).strip()
        if not exam or exam.lower() == "nan" or len(exam) > 160:
            error("exam", "Exam name is required (maximum 160 characters).")
            continue
        raw_date = row["exam_date"]
        if isinstance(raw_date, (datetime, date, pd.Timestamp)):
            exam_date = pd.Timestamp(raw_date).date().isoformat()
        else:
            exam_date = str(raw_date).strip()
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", exam_date):
                raise ValueError
            date.fromisoformat(exam_date)
        except ValueError:
            error("exam_date", "Use a valid YYYY-MM-DD date.")
            continue
        try:
            score = float(row["score"])
            if not math.isfinite(score) or not 0 <= score <= 100:
                raise ValueError
        except (ValueError, TypeError):
            error("score", "Score must be a finite percentage from 0 to 100.")
            continue
        key = (sid, exam, exam_date, ids[0])
        if key in seen:
            error("topic", "Duplicate student/exam/chapter row in this file.")
            continue
        seen.add(key)
        kind = str(row.get("exam_kind", "Practice Test")).strip()
        if not kind or kind.lower() == "nan":
            kind = "Practice Test"
        if len(kind) > 80:
            error("exam_kind", "Maximum 80 characters.")
            continue
        records.append({"student_id": sid, "subject_id": ids[1], "topic_id": ids[0],
                        "exam": exam, "exam_date": exam_date, "exam_kind": kind, "score": score})
    return records, errors


def list_upcoming() -> list[dict]:
    return auth.client().rows("schedule_details", {"select": "id,title,test_date,topic,notes,subject,class_level",
                                                   "order": "test_date,id"})


def add_upcoming(title: str, test_date: str, subject_id=None,
                 topic: str = "", notes: str = "", class_level: int | None = None) -> None:
    auth.client().rest("POST", "upcoming_tests", body={"title": title.strip(), "test_date": test_date,
                       "subject_id": subject_id, "topic": topic.strip() or None,
                       "notes": notes.strip(),
                       "class_level": int(class_level) if class_level is not None else None})


def delete_upcoming(test_id: int) -> None:
    auth.client().rest("DELETE", "upcoming_tests", params={"id": f"eq.{int(test_id)}"})


def subject_name_to_id(name: str):
    return next((s["id"] for s in list_subjects() if s["name"] == name), None)


def audit_events() -> list[dict]:
    return auth.client().rest("GET", "audit_log", params={"select": "id,actor,action,entity,entity_id,created_at", "order": "id.desc", "limit": 100})


def export_csv(frame: pd.DataFrame) -> str:
    """Avoid spreadsheet formula injection in exports containing student names."""
    out = frame.copy()
    for col in out.columns:
        if out[col].dtype == "object" or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].map(lambda value: "'" + value if isinstance(value, str)
                                  and value.lstrip().startswith(("=", "+", "-", "@")) else value)
    return out.to_csv(index=False)
