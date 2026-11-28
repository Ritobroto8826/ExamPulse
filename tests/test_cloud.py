"""Unit tests: isolated HTTP transport, auth lifecycle and import validation."""
import base64
import json
import time
import unittest
from unittest.mock import patch
import httpx
import pandas as pd
import auth
import database
from cloud import CloudClient, CloudError
from curriculum import CURRICULUM
from settings import ConfigurationError, Settings, load_settings
from fake_cloud import FakeCloud, STUDENT_ID

CONFIG = Settings("https://project.example.test", "sb_publishable_unit_tests_only", "https://app.example.test")


class TransportTests(unittest.TestCase):
    def test_jwts_are_isolated(self):
        sent = []
        def handler(request):
            sent.append(request.headers["authorization"])
            self.assertEqual(request.headers["apikey"], CONFIG.public_key)
            return httpx.Response(200, json=[])
        transport = httpx.MockTransport(handler)
        a, b = CloudClient(CONFIG, "student-A", transport), CloudClient(CONFIG, "student-B", transport)
        a.rows("students"); b.rows("students"); a.rows("students")
        self.assertEqual(sent, ["Bearer student-A", "Bearer student-B", "Bearer student-A"])

    def test_pagination_no_default_thousand_row_truncation(self):
        def handler(request):
            offset = int(request.url.params["offset"])
            return httpx.Response(200, json=[{"id": i} for i in range(offset, min(offset+500, 1203))])
        c = CloudClient(CONFIG, "jwt", httpx.MockTransport(handler))
        self.assertEqual(len(c.rows("score_details")), 1203)

    def test_errors_do_not_echo_provider_secrets(self):
        c = CloudClient(CONFIG, "jwt", httpx.MockTransport(lambda _: httpx.Response(403, json={"message": "PRIVATE-SECRET"})))
        with self.assertRaises(CloudError) as raised:
            c.rows("scores")
        self.assertEqual(raised.exception.status, 403)
        self.assertNotIn("PRIVATE", str(raised.exception))

    def test_unauthenticated_mutation_blocked_before_request(self):
        c = CloudClient(CONFIG)
        with self.assertRaises(CloudError): c.rest("POST", "scores", body={})

    def test_read_only_rpc_is_paginated(self):
        def handler(request):
            offset = int(request.url.params["offset"])
            return httpx.Response(200, json=[{"student_id": i} for i in range(offset, min(offset+500, 1503))])
        client = CloudClient(CONFIG, "jwt", httpx.MockTransport(handler))
        self.assertEqual(len(client.rpc_rows("exam_comparison", {"p_exam_id": 1})), 1503)

    def test_configuration_rejects_privileged_key(self):
        values = {"SUPABASE_URL": CONFIG.url, "APP_URL": CONFIG.app_url, "SUPABASE_PUBLISHABLE_KEY": "sb_secret_do_not_use"}
        with patch("settings._value", side_effect=lambda key: values.get(key, "")):
            with self.assertRaises(ConfigurationError): load_settings()
        encoded = base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
        values["SUPABASE_PUBLISHABLE_KEY"] = "header."+encoded+".signature"
        with patch("settings._value", side_effect=lambda key: values.get(key, "")):
            with self.assertRaises(ConfigurationError): load_settings()


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeCloud(populated=True)
        self.state = {}
        self.patches = [patch.object(auth.st, "session_state", self.state),
                        patch("auth.load_settings", return_value=CONFIG),
                        patch("auth.CloudClient", side_effect=lambda settings, access_token="": CloudClient(settings, access_token, self.fake.transport))]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def login(self):
        user, error = auth.authenticate("student@example.test", "student-only-test-passphrase")
        self.assertIsNone(error); self.assertEqual(user["role"], "student")
        self.state["user"] = user
        return user

    def test_no_shared_default_or_wrong_password(self):
        user, error = auth.authenticate("student@example.test", "wrong-password")
        self.assertIsNone(user); self.assertIn("Incorrect", error)
        self.assertNotIn("auth_session", self.state)

    def test_session_refresh_and_disable(self):
        self.login(); self.state["auth_session"]["expires_at"] = time.time()-1
        self.assertEqual(auth.ensure_session()["id"], STUDENT_ID)
        self.assertGreater(self.state["auth_session"]["expires_at"], time.time())
        next(p for p in self.fake.profiles if p["id"]==STUDENT_ID)["active"] = False
        self.assertIsNone(auth.ensure_session()); self.assertNotIn("auth_session", self.state)

    def test_password_change_requires_current_password(self):
        self.login()
        with self.assertRaises(ValueError): auth.change_password("another-long-private-passphrase", "another-long-private-passphrase")
        with self.assertRaises(ValueError): auth.change_password("another-long-private-passphrase", "another-long-private-passphrase", "wrong-current")
        auth.change_password("another-long-private-passphrase", "another-long-private-passphrase", "student-only-test-passphrase")
        self.assertEqual(self.fake.people["student@example.test"]["password"], "another-long-private-passphrase")

    def test_invite_callback_scrubs_url_and_gates_password(self):
        query = {"token_hash": "valid-invitation-token-for-testing", "type": "invite", "theme": "dark"}
        with patch.object(auth.st, "query_params", query):
            self.assertTrue(auth.consume_email_link())
        self.assertEqual(query, {"theme": "dark"})
        self.assertTrue(self.state["password_setup"])
        with self.assertRaises(ValueError): auth.change_password("short", "short")
        auth.change_password("private-invitation-passphrase", "private-invitation-passphrase")
        self.assertNotIn("password_setup", self.state)

    def test_only_own_records_leave_supabase_mock(self):
        self.login()
        self.fake.add_student("10000000-0000-4000-8000-000000000003", "Other Student", "Class 10", "other@example.test")
        self.fake.scores.append({"id":2,"student_id":2,"exam_id":1,"subject_id":1,"topic_id":1,"score":12,"max_score":100})
        frame = database.load_scores_df()
        self.assertEqual(frame.student_name.tolist(), ["Test Student"])
        comparison = database.exam_comparison(1)
        self.assertEqual(set(comparison.student_name), {"Test Student", "Other Student"})
        self.assertNotIn("email", comparison)


class DataTests(unittest.TestCase):
    def test_exact_curriculum_and_sql_seed(self):
        self.assertEqual(sorted(CURRICULUM), [8, 9, 10])
        for level in (8, 9, 10):
            self.assertEqual(list(CURRICULUM[level]), ["Mathematics", "Science"])
        self.assertEqual({lvl: [len(v) for v in subs.values()]
                          for lvl, subs in CURRICULUM.items()},
                         {8: [16, 15], 9: [15, 13], 10: [14, 13]})
        from pathlib import Path
        root = Path(__file__).parents[1]
        sql = ((root/"supabase/migrations/202611260001_production.sql").read_text()
               + (root/"supabase/migrations/202611270001_multi_class_entry.sql").read_text())
        for subs in CURRICULUM.values():
            for chapters in subs.values():
                for chapter in chapters:
                    self.assertIn(chapter.replace("'", "''"), sql)

    def test_validation_ambiguous_names_and_invalid_topics(self):
        roster=[{"id":1,"name":"Same Name","email":"one@example.test","class_level":10},
                {"id":2,"name":"Same Name","email":"two@example.test","class_level":10}]
        base={"student":"one@example.test","subject":"Mathematics","topic":"Real Numbers","exam":"Unit 1","exam_date":"2026-11-26","score":82}
        # A Class 8 chapter must not validate against a Class 10 student.
        wrong_class={**base,"topic":"Rational Numbers"}
        rows=[base,{**base,"student":"Same Name"},{**base,"topic":"English"},{**base,"score":float('inf')},base,wrong_class]
        topic_ids={(10,"Mathematics","Real Numbers"):(1,1),(8,"Mathematics","Rational Numbers"):(2,1)}
        with patch("database.list_students", return_value=roster), patch("database._topic_ids",return_value=topic_ids):
            valid, errors=database.resolve_upload(pd.DataFrame(rows))
        self.assertEqual(len(valid),1); self.assertEqual(len(errors),5)
        self.assertEqual(valid[0]["student_id"],1)
        self.assertTrue(any(e["field"]=="topic" for e in errors))

    def test_export_neutralizes_spreadsheet_formulas(self):
        csv=database.export_csv(pd.DataFrame({"name":["=HYPERLINK(\"bad\")"," @SUM(1)","Safe"]}))
        self.assertIn("'=HYPERLINK",csv); self.assertIn("' @SUM",csv); self.assertIn("Safe",csv)


class ReadCacheTests(unittest.TestCase):
    """Reads memoize per session; every write must invalidate them."""

    def setUp(self):
        self.fake = FakeCloud(populated=True)
        self.state = {}
        self.patches = [patch.object(auth.st, "session_state", self.state),
                        patch("auth.load_settings", return_value=CONFIG),
                        patch("auth.CloudClient", side_effect=lambda settings, access_token="": CloudClient(settings, access_token, self.fake.transport))]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        # Reads need a signed-in JWT or the transport refuses before fetching.
        user, error = auth.authenticate("staff@example.test", "staff-only-test-passphrase")
        self.assertIsNone(error)
        self.state["user"] = user

    def test_reads_hit_cache_until_invalidated(self):
        with patch.object(self.fake, "handle", wraps=self.fake.handle) as handle:
            first = database.load_scores_df()
            second = database.load_scores_df()
            self.assertEqual(handle.call_count, 1)  # second read is a cache hit
            self.assertTrue(first.equals(second))
            database.invalidate_cache()
            database.load_scores_df()
            self.assertEqual(handle.call_count, 2)

    def test_write_invalidates_cached_reads(self):
        with patch.object(self.fake, "handle", wraps=self.fake.handle) as handle:
            database.list_exams()
            self.assertEqual(handle.call_count, 1)
            database.add_upcoming("Cache probe", "2026-12-01")  # a real write
            database.list_exams()
            self.assertEqual(handle.call_count, 3)  # write + fresh read


if __name__ == '__main__': unittest.main()
