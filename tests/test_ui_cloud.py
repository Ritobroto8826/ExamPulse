"""UI regression with a local HTTP double, not a real Supabase project."""
from contextlib import ExitStack
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import auth
from cloud import CloudClient
from settings import Settings
from fake_cloud import FakeCloud

ROOT=Path(__file__).resolve().parents[1]
CONFIG=Settings("https://project.example.test","sb_publishable_unit_tests_only","https://app.example.test")


def submit(at, form):
    next(b for b in at.button if f"FormSubmitter:{form}-" in str(b.key)).click()
    at.run()


def login(at,email,password):
    next(x for x in at.text_input if x.label=="Email address").set_value(email)
    next(x for x in at.text_input if x.label=="Password").set_value(password)
    submit(at,"login_form")


class CloudUITests(unittest.TestCase):
    def setup_cloud(self,populated=False):
        fake=FakeCloud(populated)
        stack=ExitStack()
        stack.enter_context(patch("settings.load_settings",return_value=CONFIG))
        stack.enter_context(patch("auth.load_settings",return_value=CONFIG))
        stack.enter_context(patch("auth.CloudClient",side_effect=lambda settings,access_token="":CloudClient(settings,access_token,fake.transport)))
        self.addCleanup(stack.close)
        return fake

    def check(self,at):
        self.assertFalse(at.exception,str(at.exception))
        incidents=[e.value for e in at.error if "reference" in str(e.value)]
        self.assertFalse(incidents,str(incidents))

    def test_fresh_teacher_invites_student_and_marks_appear(self):
        fake=self.setup_cloud()
        teacher=AppTest.from_file(str(ROOT/"app.py"),default_timeout=30).run()
        self.check(teacher)
        self.assertFalse(teacher.radio)  # no caller-selectable teacher/student role
        login(teacher,"staff@example.test","staff-only-test-passphrase");self.check(teacher)
        self.assertTrue(any("No scores recorded" in x.value for x in teacher.info))
        teacher.radio(key="nav").set_value("🧑‍🏫 Students & Scores");teacher.run();self.check(teacher)
        self.assertTrue(any(x.label=="Student email" for x in teacher.text_input))
        next(x for x in teacher.selectbox if x.label=="Class").select(10)
        next(x for x in teacher.text_input if x.label=="Full name").set_value("Fresh Student")
        next(x for x in teacher.text_input if x.label=="Batch").set_value("A")
        next(x for x in teacher.text_input if x.label=="Student email").set_value("fresh@example.test")
        submit(teacher,"add_student_form");self.check(teacher)
        self.assertEqual(len(fake.students),1)
        self.assertEqual(fake.students[0]["class_level"],10)
        self.assertTrue(any("Invitation sent" in x.value for x in teacher.success))
        teacher.run()
        self.assertEqual(teacher.selectbox(key="entry_subject").options,["Mathematics","Science"])
        teacher.selectbox(key="entry_subject").select("Science");teacher.run();self.check(teacher)
        chapters=next(x for x in teacher.multiselect if x.label=="Topics covered in this test").options
        self.assertEqual(len(chapters),13)
        self.assertEqual(chapters[0],"Chemical Reactions and Equations")
        self.assertIn("How do Organisms Reproduce?",chapters)
        teacher.selectbox(key="entry_subject").select("Mathematics");teacher.run()
        self.assertEqual(len(next(x for x in teacher.multiselect if x.label=="Topics covered in this test").options),14)
        # Two chapters in one save, one of them converted from raw marks.
        topics=next(x for x in teacher.multiselect if x.label=="Topics covered in this test")
        topics.select("Real Numbers");topics.select("Polynomials");teacher.run();self.check(teacher)
        teacher.checkbox(key="entry_new_exam").check();teacher.run()
        next(x for x in teacher.text_input if x.label=="Exam name").set_value("Fresh chapter test")
        next(x for x in teacher.number_input if x.label=="Marks · Real Numbers").set_value(91)
        next(x for x in teacher.number_input if x.label=="Marks · Polynomials").set_value(15)
        next(x for x in teacher.number_input if x.label=="Out of · Polynomials").set_value(20)
        submit(teacher,"score_form");self.check(teacher)
        self.assertTrue(any("Saved 2 topic(s)" in x.value for x in teacher.success))
        self.assertEqual(len(fake.scores),2)
        self.assertEqual(sorted(m["score"] for m in fake.scores),[75.0,91.0])
        converted=next(m for m in fake.scores if m["score"]==75.0)
        self.assertEqual(converted["raw_score"],15)   # 15/20 -> 75%
        self.assertEqual(converted["raw_max"],20)
        plain=next(m for m in fake.scores if m["score"]==91.0)
        self.assertEqual(plain["raw_score"],91)       # 91/100 -> 91%
        student=AppTest.from_file(str(ROOT/"app.py"),default_timeout=30).run()
        login(student,"fresh@example.test","student-only-test-passphrase");self.check(student)
        self.assertIn("83.0%","\n".join(x.value for x in student.markdown))  # mean(91, 75)
        self.assertNotIn("Students & Scores",student.radio(key="nav").options)
        student.radio(key="nav").set_value("📊 Student Comparison");student.run();self.check(student)
        self.assertTrue(student.get("plotly_chart"))
        self.assertFalse(student.get("data_editor"))
        student.radio(key="nav").set_value("🔐 Account & Security");student.run();self.check(student)
        self.assertTrue(any(x.label=="Current password" for x in student.text_input))

    def test_class_scoped_chapters_and_class_view(self):
        fake=self.setup_cloud()
        teacher=AppTest.from_file(str(ROOT/"app.py"),default_timeout=30).run()
        login(teacher,"staff@example.test","staff-only-test-passphrase");self.check(teacher)
        teacher.radio(key="nav").set_value("🧑‍🏫 Students & Scores");teacher.run();self.check(teacher)
        # Invite a Class 8 student: entry must offer the Class 8 curriculum.
        next(x for x in teacher.selectbox if x.label=="Class").select(8)
        next(x for x in teacher.text_input if x.label=="Full name").set_value("Class Eight Student")
        next(x for x in teacher.text_input if x.label=="Batch").set_value("A")
        next(x for x in teacher.text_input if x.label=="Student email").set_value("eight@example.test")
        submit(teacher,"add_student_form");self.check(teacher)
        self.assertEqual(fake.students[0]["class_level"],8)
        teacher.run()
        chapters=next(x for x in teacher.multiselect if x.label=="Topics covered in this test").options
        self.assertEqual(len(chapters),16)
        self.assertIn("Rational Numbers",chapters)
        self.assertNotIn("Quadratic Equations",chapters)  # Class 10 only
        # 12/16 converts to 75%.
        next(x for x in teacher.multiselect if x.label=="Topics covered in this test").select("Rational Numbers")
        teacher.run();self.check(teacher)
        next(x for x in teacher.number_input if x.label=="Marks · Rational Numbers").set_value(12)
        next(x for x in teacher.number_input if x.label=="Out of · Rational Numbers").set_value(16)
        teacher.checkbox(key="entry_new_exam").check();teacher.run()
        next(x for x in teacher.text_input if x.label=="Exam name").set_value("Class 8 maths test")
        submit(teacher,"score_form");self.check(teacher)
        self.assertEqual(fake.scores[0]["score"],75.0)
        # A Class 10 student gets the Class 10 chapter list.
        teacher.run()
        next(x for x in teacher.selectbox if x.label=="Class").select(10)
        next(x for x in teacher.text_input if x.label=="Full name").set_value("Class Ten Student")
        next(x for x in teacher.text_input if x.label=="Batch").set_value("A")
        next(x for x in teacher.text_input if x.label=="Student email").set_value("ten@example.test")
        submit(teacher,"add_student_form");self.check(teacher)
        teacher.run()
        next(x for x in teacher.selectbox if x.label=="Student").select(2)
        teacher.run();self.check(teacher)
        chapters=next(x for x in teacher.multiselect if x.label=="Topics covered in this test").options
        self.assertEqual(len(chapters),14)
        self.assertIn("Quadratic Equations",chapters)
        self.assertNotIn("Rational Numbers",chapters)
        next(x for x in teacher.multiselect if x.label=="Topics covered in this test").select("Real Numbers")
        teacher.run();self.check(teacher)
        next(x for x in teacher.number_input if x.label=="Marks · Real Numbers").set_value(90)
        next(x for x in teacher.text_input if x.label=="Exam name").set_value("Class 10 maths test")
        submit(teacher,"score_form");self.check(teacher)
        self.assertEqual(fake.scores[1]["score"],90.0)
        # Sidebar class view scopes analytics but the roster stays complete.
        teacher.radio(key="nav").set_value("📊 Dashboard");teacher.run();self.check(teacher)
        view=teacher.selectbox(key="class_view")
        self.assertEqual(view.options,["All classes","Class 8","Class 9","Class 10"])
        teacher.selectbox(key="class_view").select("Class 8");teacher.run();self.check(teacher)
        self.assertTrue(any("75.0%" in x.value for x in teacher.markdown))
        teacher.selectbox(key="class_view").select("Class 10");teacher.run();self.check(teacher)
        self.assertTrue(any("90.0%" in x.value for x in teacher.markdown))
        teacher.selectbox(key="class_view").select("All classes");teacher.run();self.check(teacher)
        teacher.radio(key="nav").set_value("📤 Bulk Upload & Reports");teacher.run();self.check(teacher)
        self.assertTrue(any("Class 8 · " in x.value for x in teacher.markdown))
        teacher.radio(key="nav").set_value("🧑‍🏫 Students & Scores");teacher.run();self.check(teacher)
        self.assertEqual(len(teacher.selectbox(key="drill_pick").options),2)

    def test_invitation_requires_private_password_before_scores(self):
        self.setup_cloud(populated=True)
        at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=30)
        at.query_params["token_hash"]="valid-invitation-token-for-testing"
        at.query_params["type"]="invite"
        at.run();self.check(at)
        self.assertTrue(any(x.label=="Confirm new password" for x in at.text_input))
        self.assertFalse(at.get("plotly_chart"))
        self.assertFalse(at.dataframe)
        self.assertNotIn("token_hash",at.query_params)
        next(x for x in at.text_input if x.label=="New password").set_value("a-private-student-passphrase")
        next(x for x in at.text_input if x.label=="Confirm new password").set_value("a-private-student-passphrase")
        submit(at,"password_form");self.check(at)
        self.assertTrue(at.get("plotly_chart"))
        self.assertIn("86.0%","\n".join(x.value for x in at.markdown))

    def test_dark_and_light_roles_all_pages(self):
        self.setup_cloud(populated=True)
        for mode in (False,True):
            for email,password,pages in [
                ("staff@example.test","staff-only-test-passphrase",["📊 Dashboard","🧑‍🏫 Students & Scores","📤 Bulk Upload & Reports","📅 Schedule","🔐 Account & Security"]),
                ("student@example.test","student-only-test-passphrase",["📊 Dashboard","📈 My Progress","📅 Upcoming Tests","📊 Student Comparison","🔐 Account & Security"]),
            ]:
                at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=30).run()
                at.toggle(key="dark_mode").set_value(mode);at.run()
                login(at,email,password);self.check(at)
                for page in pages:
                    at.radio(key="nav").set_value(page);at.run();self.check(at)
                    for element in at.get("plotly_chart"):
                        spec=json.loads(element.proto.spec)
                        self.assertEqual(spec["layout"]["paper_bgcolor"],"#131F31" if mode else "#FFFFFF")
                at.button(key="logout_btn").click();at.run();self.check(at)
                self.assertEqual(at.session_state["dark_mode"],mode)
                self.assertTrue(any(x.label=="Email address" for x in at.text_input))


if __name__=='__main__':unittest.main()
