"""In-memory HTTP test double. Never contacts Supabase or sends email."""
from __future__ import annotations
from datetime import date
import json
from urllib.parse import parse_qs
import httpx
from curriculum import CURRICULUM

TEACHER_ID = "10000000-0000-4000-8000-000000000001"
STUDENT_ID = "10000000-0000-4000-8000-000000000002"


class FakeCloud:
    def __init__(self, populated=False):
        self.people = {
            "staff@example.test": {"id": TEACHER_ID, "password": "staff-only-test-passphrase"},
            "student@example.test": {"id": STUDENT_ID, "password": "student-only-test-passphrase"},
        }
        self.tokens = {"token-" + p["id"]: p["id"] for p in self.people.values()}
        self.profiles = [{"id": TEACHER_ID, "role": "teacher", "display_name": "Test Teacher", "student_id": None, "active": True}]
        self.students, self.scores, self.exams, self.schedule = [], [], [], []
        self.subjects, self.topics = [], []
        subject_names = list(next(iter(CURRICULUM.values())))
        for sid, name in enumerate(subject_names, 1):
            self.subjects.append({"id": sid, "name": name, "position": sid})
        for level, subjects in CURRICULUM.items():
            for name, chapters in subjects.items():
                sid = next(s["id"] for s in self.subjects if s["name"] == name)
                for pos, chapter in enumerate(chapters, 1):
                    self.topics.append({"id": len(self.topics) + 1, "subject_id": sid,
                                        "class_level": level, "name": chapter, "position": pos})
        self.requests = []
        if populated:
            self.add_student(STUDENT_ID, "Test Student", "Class 10", "student@example.test")
            self.exams.append({"id": 1, "name": "Unit assessment", "exam_date": date.today().isoformat(), "kind": "Unit Test"})
            self.scores.append({"id": 1, "student_id": 1, "exam_id": 1, "subject_id": 1, "topic_id": 1,
                                "score": 86, "max_score": 100, "raw_score": None, "raw_max": None})

    def add_student(self, uid, name, batch, email, class_level=10):
        sid = len(self.students) + 1
        self.students.append({"id": sid, "name": name, "batch": batch, "class_level": class_level,
                              "email": email, "joined_date": date.today().isoformat()})
        self.profiles.append({"id": uid, "role": "student", "display_name": name, "student_id": sid, "active": True})
        self.people.setdefault(email, {"id": uid, "password": "student-only-test-passphrase"})
        self.tokens["token-" + uid] = uid
        return sid

    def session(self, person):
        return {"access_token": "token-" + person["id"], "refresh_token": "refresh-" + person["id"],
                "expires_in": 3600, "user": {"id": person["id"], "email": next(e for e,p in self.people.items() if p["id"] == person["id"])}}

    def handle(self, request):
        path, method = request.url.path, request.method
        q = dict(request.url.params)
        body = json.loads(request.content) if request.content else {}
        uid = self.tokens.get(request.headers.get("Authorization", "").removeprefix("Bearer "))
        person = next((p for p in self.profiles if p["id"] == uid), None)
        teacher = bool(person and person["role"] == "teacher" and person["active"])
        active = bool(person and person["active"])
        self.requests.append((method, path, "teacher" if teacher else "student" if person else "none"))
        ok = lambda data, status=200: httpx.Response(status, json=data)
        if path == "/auth/v1/token":
            if q.get("grant_type") == "refresh_token":
                match = next((p for p in self.people.values() if "refresh-"+p["id"] == body.get("refresh_token")), None)
            else:
                match = self.people.get(body.get("email"))
                if match and match["password"] != body.get("password"):
                    match = None
            return ok(self.session(match)) if match else ok({"error": "bad credentials"}, 400)
        if path == "/auth/v1/user" and uid:
            email, record = next((e,p) for e,p in self.people.items() if p["id"] == uid)
            if method == "PUT":
                record["password"] = body["password"]
            return ok({"id": uid, "email": email})
        if path == "/auth/v1/verify":
            if body.get("token_hash") != "valid-invitation-token-for-testing":
                return ok({"error": "expired"}, 403)
            return ok(self.session(self.people["student@example.test"]))
        if path in ("/auth/v1/recover", "/auth/v1/logout"):
            return ok({})
        if path == "/functions/v1/manage-students":
            if not teacher:
                return ok({}, 403)
            if any(s["email"] == body["email"] for s in self.students):
                return ok({}, 409)
            new_uid = f"10000000-0000-4000-8000-{len(self.students)+3:012d}"
            self.add_student(new_uid, body["name"], body["batch"], body["email"],
                             class_level=body.get("class_level", 10))
            return ok({"message": "sent"}, 201)
        if path.startswith("/rest/v1/"):
            table = path.removeprefix("/rest/v1/")
            if table == "profiles":
                rows = [dict(p) for p in self.profiles if teacher or p["id"] == uid]
            elif not active:
                return ok([], 200) if method == "GET" else ok({}, 403)
            elif table == "students" and method == "PATCH":
                if not teacher: return ok({}, 403)
                target = str(q.get("id", "")).removeprefix("eq.")
                for s in self.students:
                    if str(s["id"]) == target:
                        s.update(body)
                return httpx.Response(204)
            elif table == "students":
                rows = [dict(s) for s in self.students if teacher or s["id"] == person["student_id"]]
            elif table == "student_access":
                rows = [{**s, "active": next(p["active"] for p in self.profiles if p["student_id"] == s["id"])} for s in self.students] if teacher else []
            elif table == "subjects": rows = self.subjects
            elif table == "topics": rows = self.topics
            elif table == "exams":
                if method == "POST":
                    if not teacher: return ok({}, 403)
                    existing = next((e for e in self.exams if e["name"] == body["name"] and e["exam_date"] == body["exam_date"]), None)
                    if not existing:
                        existing = {"id": len(self.exams)+1, **body}; self.exams.append(existing)
                    return ok([existing], 201)
                rows = self.exams
            elif table == "score_details":
                rows = []
                for mark in self.scores:
                    if not teacher and mark["student_id"] != person["student_id"]: continue
                    s = next(s for s in self.students if s["id"] == mark["student_id"])
                    e = next(e for e in self.exams if e["id"] == mark["exam_id"])
                    t = next(t for t in self.topics if t["id"] == mark["topic_id"])
                    sub = next(sub for sub in self.subjects if sub["id"] == mark["subject_id"])
                    rows.append({"score_id": mark["id"], "student_id": s["id"], "student_name": s["name"],
                                 "batch": s["batch"], "class_level": s["class_level"],
                                 "exam_id": e["id"], "exam_name": e["name"], "exam_date": e["exam_date"],
                                 "exam_kind": e["kind"],
                                 "subject_id": sub["id"], "subject": sub["name"], "topic_id": t["id"],
                                 "topic": t["name"],
                                 "score": mark["score"], "max_score": 100,
                                 "raw_score": mark.get("raw_score"), "raw_max": mark.get("raw_max")})
            elif table == "scores" and method == "POST":
                if not teacher: return ok({}, 403)
                old = next((m for m in self.scores if all(m[k] == body[k] for k in ("student_id", "exam_id", "topic_id"))), None)
                if old: old.update(body)
                else: self.scores.append({"id": len(self.scores)+1, "max_score": 100, **body})
                return httpx.Response(201)
            elif table == "scores" and method == "PATCH":
                if not teacher: return ok({}, 403)
                target = str(q.get("id", "")).removeprefix("eq.")
                for m in self.scores:
                    if str(m["id"]) == target:
                        m.update(body)
                return httpx.Response(204)
            elif table == "rpc/import_score_records":
                if not teacher: return ok({}, 403)
                records = body.get("p_records") or []
                if not 1 <= len(records) <= 1000:
                    return ok({"message": "Provide between 1 and 1000 rows"}, 400)
                for r in records:
                    existing = next((e for e in self.exams
                                     if e["name"] == r["exam"] and e["exam_date"] == r["exam_date"]), None)
                    if not existing:
                        existing = {"id": len(self.exams) + 1, "name": r["exam"],
                                    "exam_date": r["exam_date"],
                                    "kind": r.get("exam_kind") or "Practice Test"}
                        self.exams.append(existing)
                    old = next((m for m in self.scores
                                if m["student_id"] == r["student_id"]
                                and m["exam_id"] == existing["id"]
                                and m["topic_id"] == r["topic_id"]), None)
                    payload = {"subject_id": r["subject_id"], "score": r["score"],
                               "raw_score": r.get("raw_score"), "raw_max": r.get("raw_max")}
                    if old:
                        old.update(payload)
                    else:
                        self.scores.append({"id": len(self.scores) + 1, "max_score": 100,
                                            "student_id": r["student_id"],
                                            "exam_id": existing["id"],
                                            "topic_id": r["topic_id"], **payload})
                return ok(len(records))
            elif table == "rpc/delete_exam":
                if not teacher:
                    return ok({"message": "Teacher role required"}, 403)
                eid = int(body.get("p_exam_id") or 0)
                include = bool(body.get("p_include_scores"))
                hits = [m for m in self.scores if m["exam_id"] == eid]
                if hits and not include:
                    return ok({"message": "Exam still has scores"}, 400)
                if include:
                    self.scores[:] = [m for m in self.scores if m["exam_id"] != eid]
                self.exams[:] = [e for e in self.exams if e["id"] != eid]
                return httpx.Response(204)
            elif table in ("schedule_details", "upcoming_tests"): rows = self.schedule
            elif table == "audit_log": rows = []
            elif table == "rpc/set_student_active":
                if not teacher: return ok({}, 403)
                next(p for p in self.profiles if p["student_id"] == body["p_student_id"])["active"] = body["p_active"]
                return httpx.Response(204)
            elif table == "rpc/exam_comparison":
                viewer_class = None
                if not teacher and person and person.get("student_id"):
                    viewer_class = next(s["class_level"] for s in self.students
                                        if s["id"] == person["student_id"])
                result=[]
                for student in self.students:
                    if viewer_class is not None and student["class_level"] != viewer_class:
                        continue
                    profile=next(p for p in self.profiles if p["student_id"]==student["id"])
                    if not profile["active"]: continue
                    marks=[m["score"] for m in self.scores if m["student_id"]==student["id"] and m["exam_id"]==body["p_exam_id"]
                           and (body.get("p_subject_id") is None or m["subject_id"]==body["p_subject_id"])
                           and (body.get("p_topic_id") is None or m["topic_id"]==body["p_topic_id"])]
                    result.append({"student_id":student["id"],"student_name":student["name"],"batch":student["batch"],
                                   "score":sum(marks)/len(marks) if marks else None,"topic_count":len(marks)})
                return ok(result)
            else:
                raise AssertionError(f"Unhandled fake endpoint: {method} {table}")
            for key, value in q.items():
                if value.startswith("eq."):
                    rows = [r for r in rows if str(r.get(key)) == value[3:]]
                if value.startswith("gte."):
                    rows = [r for r in rows if str(r.get(key)) >= value[4:]]
            start, limit = int(q.get("offset", 0)), int(q.get("limit", 500))
            return ok(rows[start:start+limit])
        return ok({}, 401)

    @property
    def transport(self):
        return httpx.MockTransport(self.handle)
