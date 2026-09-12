import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_kvpn import kvpn


class DebugTests(unittest.TestCase):
    def test_debug_output_is_disabled_by_default(self):
        output = io.StringIO()
        with mock.patch.dict(kvpn.os.environ, {}, clear=True), mock.patch.object(
            kvpn.sys, "stderr", output
        ):
            kvpn.debug_log("test-event", status=200)
        self.assertEqual(output.getvalue(), "")

    def test_explicit_debug_output_is_prefixed_json(self):
        output = io.StringIO()
        with mock.patch.dict(
            kvpn.os.environ, {"KVPN_DEBUG": "1"}, clear=True
        ), mock.patch.object(kvpn.sys, "stderr", output):
            kvpn.debug_log("test-event", status=200)
        line = output.getvalue().strip()
        self.assertTrue(line.startswith("[kvpn-debug] "))
        record = json.loads(line[len("[kvpn-debug] "):])
        self.assertEqual(record["event"], "test-event")
        self.assertEqual(record["status"], 200)

    def test_debug_file_is_created_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kvpn-debug.log"
            with mock.patch.dict(
                kvpn.os.environ, {"KVPN_DEBUG_LOG": str(path)}, clear=True
            ), mock.patch.object(kvpn.sys, "stderr", io.StringIO()):
                kvpn.debug_log("first-test-event", status=200)
                kvpn.debug_log("second-test-event", status=302)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            records = [json.loads(line[len("[kvpn-debug] "):]) for line in lines]
            self.assertEqual(
                [record["event"] for record in records],
                ["first-test-event", "second-test-event"],
            )
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_urls_retain_route_but_not_credentials_or_session_identifiers(self):
        urls = [
            (
                "https://private-user:private-password@kvpn.kaist.ac.kr/"
                "dana-na/auth/url_private-session/login.cgi"
                ";jsessionid=private-path-session?code=private-code#private-fragment",
                "/login.cgi",
            ),
            (
                kvpn.PORTAL + "/vpn/private-vpn-token"
                "?user_name=private-user&code=private-code#private-fragment",
                "/vpn/",
            ),
        ]
        for url, route in urls:
            with self.subTest(route=route):
                sanitized = kvpn._debug_url(url)
                self.assertIn(route, sanitized)
                for secret in (
                    "private-user", "private-password", "private-session",
                    "private-path-session", "private-code", "private-fragment",
                    "private-vpn-token",
                ):
                    self.assertNotIn(secret, sanitized)
                self.assertNotIn("?", sanitized)
                self.assertNotIn("#", sanitized)

    def test_body_summaries_do_not_expose_json_or_html_values(self):
        private_values = (
            "private-password", "otp-918273", "private-dsid",
            "private-jsessionid", "private-secondary-token",
        )
        json_body = json.dumps({
            "password": private_values[0],
            "otp": private_values[1],
            "DSID": private_values[2],
            "nested": {"JSESSIONID": private_values[3]},
            "message": private_values[4],
        })
        html_body = (
            '<html><input name="password" value="private-password">'
            '<input name="otp" value="otp-918273">'
            '<script>var message = "private-secondary-token";'
            'var cookies = "DSID=private-dsid; JSESSIONID=private-jsessionid";'
            '</script></html>'
        )
        for body in (json_body, html_body, json.dumps(json_body)):
            with self.subTest(body_type=body[:20]):
                summary = json.dumps(kvpn._debug_body(body))
                for secret in private_values:
                    self.assertNotIn(secret, summary)

    def test_json_diagnostics_distinguish_payload_shapes_and_encoded_json(self):
        for payload, expected in (({}, "object"), ([], "array"), ("unexpected", "string")):
            with self.subTest(expected=expected):
                summary = kvpn._debug_body(json.dumps(payload))
                self.assertEqual(summary["kind"], "json")
                self.assertEqual(summary["shape"]["type"], expected)
        body = json.dumps(json.dumps({"response": {"success": "false"}}))
        summary = kvpn._debug_body(body)
        embedded = summary["shape"]["embedded_json"]
        self.assertEqual(embedded["type"], "object")
        self.assertEqual(embedded["fields"]["response"]["type"], "object")
        self.assertEqual(summary["length"], len(body))

    def test_portal_error_scripts_produce_useful_signals_without_page_text(self):
        for script, expected in (
            ("invalidAccess.js", "invalid-access"), ("timeOut.js", "session-timeout")
        ):
            with self.subTest(script=script):
                summary = kvpn._debug_body(
                    '<html><script src="/js/%s"></script>private-page-data</html>' % script
                )
                self.assertEqual(summary["kind"], "html")
                self.assertIn(expected, summary["signals"])
                self.assertNotIn("private-page-data", json.dumps(summary))

    def test_response_metadata_omits_auth_headers_and_cookie_values(self):
        output = io.StringIO()
        with mock.patch.dict(
            kvpn.os.environ, {"KVPN_DEBUG": "1"}, clear=True
        ), mock.patch.object(kvpn.sys, "stderr", output):
            kvpn.debug_response(
                "portal", "POST",
                kvpn.PORTAL + "/api/portal?code=private-query-code",
                kvpn.PORTAL + "/request;jsessionid=private-path-session",
                302,
                {
                    "Content-Type": "text/html; charset=utf-8",
                    "Content-Encoding": "gzip",
                    "Set-Cookie": "JSESSIONID=private-cookie; DSID=private-dsid",
                    "Authorization": "Bearer private-access-token",
                    "Location": kvpn.PORTAL + "/request?code=private-location-code",
                },
                '<html><input value="private-otp"></html>',
            )
        diagnostic = output.getvalue()
        self.assertIn("302", diagnostic)
        self.assertIn("text/html", diagnostic)
        self.assertIn("gzip", diagnostic)
        for secret in (
            "private-query-code", "private-path-session", "private-cookie",
            "private-dsid", "private-access-token", "private-location-code", "private-otp",
        ):
            self.assertNotIn(secret, diagnostic)

    def test_http_wrappers_log_responses_without_request_secrets(self):
        url = kvpn.PORTAL + "/api/portal?code=private-query-code"
        body = '{"success":"false","password":"private-response-password"}'
        for wrapper in ("get", "post", "raw"):
            with self.subTest(wrapper=wrapper):
                opener = mock.MagicMock()
                response = opener.open.return_value.__enter__.return_value
                response.geturl.return_value = url
                response.getcode.return_value = 200
                response.headers = {
                    "Content-Type": "application/json",
                    "Set-Cookie": "JSESSIONID=private-response-session",
                }
                response.read.return_value = body.encode("utf-8")
                output = io.StringIO()
                with mock.patch.dict(
                    kvpn.os.environ, {"KVPN_DEBUG": "1"}, clear=True
                ), mock.patch.object(kvpn.sys, "stderr", output):
                    if wrapper == "get":
                        result = kvpn.http_get(opener, url)
                    elif wrapper == "post":
                        result = kvpn.http_post(
                            opener, url, {"password": "private-request-password"}
                        )
                    else:
                        portal = kvpn.Portal.__new__(kvpn.Portal)
                        portal.raw = opener
                        result = portal._raw(
                            "POST", url, data={"j_password": "private-request-otp"}
                        )
                self.assertEqual(result[-1], body)
                diagnostic = output.getvalue()
                self.assertTrue(diagnostic.startswith("[kvpn-debug] "))
                self.assertIn("application/json", diagnostic)
                self.assertIn("200", diagnostic)
                for secret in (
                    "private-query-code", "private-response-password",
                    "private-response-session", "private-request-password",
                    "private-request-otp",
                ):
                    self.assertNotIn(secret, diagnostic)

    def test_cli_logs_runtime_information_before_network_access(self):
        output = io.StringIO()
        with mock.patch.dict(
            kvpn.os.environ, {"KVPN_DEBUG": "1"}, clear=True
        ), mock.patch.object(kvpn.sys, "stderr", output), mock.patch.object(
            kvpn.sys, "stdout", io.StringIO()
        ), mock.patch.object(
            kvpn, "load_credentials", return_value=("alice", "password", kvpn.REALMS[0])
        ), mock.patch.object(kvpn, "Ivanti") as ivanti:
            ivanti.return_value.begin.side_effect = kvpn.KvpnError("stop before network")
            with self.assertRaises(kvpn.KvpnError):
                kvpn.main([])
        records = [
            json.loads(line[len("[kvpn-debug] "):])
            for line in output.getvalue().splitlines()
        ]
        runtime = next(record for record in records if record["event"] == "runtime")
        self.assertEqual(runtime["platform"], kvpn.sys.platform)
        self.assertIn(kvpn.sys.version.split()[0], runtime["python"])


if __name__ == "__main__":
    unittest.main()
