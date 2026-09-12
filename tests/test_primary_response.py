import io
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from test_kvpn import kvpn


# Red-paragraph markup matches the publicly observed Ivanti credential-error page.
# Field values and all other error scenarios below are synthetic test data.
CREDENTIAL_ERROR = '<p style="color:#ff0000">Invalid username or password.</p>'
LOGIN_FORM = """<form name="frmLogin" action="/login.cgi">
<input type="hidden" name="tz_offset" value="540">
<input name="username" value="private-user">
<input name="password" type="password" value="private-password">
<input name="password#2" value="private-handshake">
<select name="realm"><option>KAIST Members</option></select>
<input name="private-field-name" value="private-field-value">
</form>"""


class PrimaryResponseTests(unittest.TestCase):
    def setUp(self):
        debug_env = mock.patch.dict(
            kvpn.os.environ, {"KVPN_DEBUG": "", "KVPN_DEBUG_LOG": ""}
        )
        debug_env.start()
        self.addCleanup(debug_env.stop)
        self.ivanti = kvpn.Ivanti.__new__(kvpn.Ivanti)
        self.ivanti.welcome_url = kvpn.IVANTI + "/dana-na/auth/url_test/welcome.cgi"
        self.ivanti.login_url = self.ivanti.welcome_url.replace("welcome.cgi", "login.cgi")
        self.ivanti.opener = mock.MagicMock()
        self.ivanti.cj = []
        self.response = self.ivanti.opener.open.return_value.__enter__.return_value
        self.response.geturl.return_value = self.ivanti.login_url
        self.response.getcode.return_value = 200
        self.response.headers = {"Content-Type": "text/html"}
        self.response.read.return_value = LOGIN_FORM.encode("utf-8")

    def test_primary_login_error_page_is_left_to_authoritative_onepass_check(self):
        self.response.read.return_value = (LOGIN_FORM + CREDENTIAL_ERROR).encode("utf-8")
        for suffix in ("", "?p=failed"):
            with self.subTest(suffix=suffix):
                self.response.geturl.return_value = self.ivanti.login_url + suffix
                self.ivanti.authenticate_primary("alice", "password", kvpn.REALMS[0], "Tn2Xf8|test-code")
                self.assertIsNone(kvpn.cookie_value(self.ivanti.cj, "DSID"))

    def test_login_form_summary_only_contains_allowed_field_names(self):
        summary = kvpn._ivanti_response_summary(LOGIN_FORM)
        self.assertTrue(summary["login_form"])
        self.assertEqual(set(summary["fields"]), {"tz_offset", "username", "password", "password#2", "realm"})
        self.assertEqual(summary["other_field_count"], 1)
        for secret in ("private-user", "private-password", "private-handshake", "private-field-name", "private-field-value"):
            self.assertNotIn(secret, json.dumps(summary))

    def test_login_cgi_substring_is_not_treated_as_a_login_form(self):
        summary = kvpn._ivanti_response_summary(
            '<a href="/login.cgi">Sign in</a><form name="unrelated"><input name="search"></form>'
        )
        self.assertFalse(summary["login_form"])

    def test_incomplete_attributes_and_disabled_fields_are_safe(self):
        summary = kvpn._ivanti_response_summary(
            '<form name><p style class role>private-message</p></form>'
            '<form name="frmLogin"><input name="password" disabled>'
            '<input name><input name="username"></form>'
        )
        self.assertTrue(summary["login_form"])
        self.assertEqual(summary["fields"], ["username"])
        self.assertEqual(summary["errors"], [])
        self.assertNotIn("private-message", json.dumps(summary))

    def test_public_credential_error_is_classified_without_raw_text(self):
        summary = kvpn._ivanti_response_summary(LOGIN_FORM + CREDENTIAL_ERROR)
        self.assertEqual(summary["errors"], ["invalid-credentials"])
        self.assertEqual(len(summary["error_text_lengths"]), 1)
        self.assertGreater(summary["error_text_lengths"][0], 0)
        self.assertNotIn("Invalid username or password", json.dumps(summary))

    def test_synthetic_error_regions_are_normalized_and_classified(self):
        cases = (
            ('<div role="alert"> INVALID\nREQUEST </div>', "invalid-request"),
            ('<span class="cssError">Sign-in failed</span>', "login-failed"),
            ('<p class="error-message">Login failed</p>', "login-failed"),
            ('<p style="color: #FF0000">Access <b>denied</b></p>', "access-denied"),
            ('<div role="alert">Account is locked</div>', "account-locked"),
            ('<p class="error-message">Account locked</p>', "account-locked"),
            ('<span class="cssError">Session has expired</span>', "session-expired"),
            ('<div role="alert">Session expired</div>', "session-expired"),
        )
        for body, label in cases:
            with self.subTest(label=label, body=body):
                summary = kvpn._ivanti_response_summary(body)
                self.assertEqual(summary["errors"], [label])
                self.assertTrue(all(isinstance(length, int) for length in summary["error_text_lengths"]))

    def test_unknown_error_only_reports_label_and_length(self):
        summary = kvpn._ivanti_response_summary(
            '<div role="alert">private-user: private-server-message private-session-token</div>'
        )
        self.assertEqual(summary["errors"], ["unknown-error"])
        self.assertEqual(len(summary["error_text_lengths"]), 1)
        self.assertNotIn("private-", json.dumps(summary))

    def test_script_style_comments_and_ordinary_text_are_not_error_regions(self):
        body = """<script>var template = '<form name="frmLogin"><p role="alert">Invalid request</p></form>';</script>
<style>.message::after { content: 'Account locked'; }</style>
<!-- <form name="frmLogin"><p style="color:#ff0000">Invalid username or password</p></form> -->
<p>Session has expired</p><a href="/login.cgi">Sign in</a>"""
        summary = kvpn._ivanti_response_summary(body)
        self.assertFalse(summary["login_form"])
        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["error_text_lengths"], [])

    def test_submitted_diagnostics_include_only_sanitized_response_and_cookie_presence(self):
        self.ivanti.cj = [
            SimpleNamespace(name="DSSIGNIN", value="private-signin-cookie"),
            SimpleNamespace(name="DSID", value="private-dsid-cookie"),
        ]
        self.response.read.return_value = (LOGIN_FORM + CREDENTIAL_ERROR).encode("utf-8")
        output = io.StringIO()
        with mock.patch.dict(kvpn.os.environ, {"KVPN_DEBUG": "1"}), mock.patch.object(
            kvpn.sys, "stderr", output
        ):
            self.ivanti.authenticate_primary("private-user", "private-password", kvpn.REALMS[0], "Tn2Xf8|private-correlation")
        records = [json.loads(line[len("[kvpn-debug] "):]) for line in output.getvalue().splitlines()]
        submitted = next(record for record in records if record["event"] == "primary-auth" and record["phase"] == "submitted")
        self.assertEqual(submitted["response"]["errors"], ["invalid-credentials"])
        self.assertEqual(submitted["cookies"], {"DSSIGNIN": True, "DSID": True})
        for secret in (
            "private-user", "private-password", "private-correlation", "private-handshake",
            "private-field-name", "private-field-value", "private-signin-cookie", "private-dsid-cookie",
        ):
            self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
