import io
import json
import unittest
import urllib.error
import urllib.parse
from unittest import mock

from test_kvpn import kvpn


class PortalTests(unittest.TestCase):
    # Delivery fields, success/negative reasons, and otp_flag values follow
    # https://kvpnportal.kaist.ac.kr:8443/js/mainMenu.js.
    def setUp(self):
        # Keep every request offline while exercising the real request builder.
        self.portal = kvpn.Portal.__new__(kvpn.Portal)
        self.portal.parent = kvpn.IVANTI + "/dana-na/auth/url_default/welcome.cgi"
        self.portal.opener = mock.MagicMock()
        self.portal.raw = mock.MagicMock()
        self.response = self.portal.raw.open.return_value.__enter__.return_value
        self.portal.opener.open.return_value.__enter__.return_value = self.response
        self.response.getcode.return_value = 200
        self.response.geturl.return_value = kvpn.PORTAL + "/api/portal"
        self.response.headers = {}
        self.response.read.return_value = b'{"success":"true"}'

    def test_accepted_requests_use_portal_ajax_form(self):
        for send_type in ("email", "sms"):
            with self.subTest(send_type=send_type):
                self.portal.raw.open.reset_mock()
                self.portal.send_code("test+user", send_type)

                self.portal.raw.open.assert_called_once()
                request = self.portal.raw.open.call_args.args[0]
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(request.full_url, kvpn.PORTAL + "/api/portal")
                self.assertEqual(
                    urllib.parse.parse_qs(request.data.decode("utf-8")),
                    {
                        "cmd": ["AuthPortal.twoAuthSend"],
                        "send_type": [send_type],
                        "user_name": ["test+user"],
                    },
                )
                headers = {key.lower(): value for key, value in request.header_items()}
                self.assertEqual(headers["referer"], kvpn.PORTAL + "/view/mainMenu")
                self.assertEqual(headers["origin"], kvpn.PORTAL)
                self.assertEqual(headers["x-requested-with"], "XMLHttpRequest")
                self.assertEqual(headers["sec-fetch-dest"], "empty")
                self.assertEqual(headers["sec-fetch-mode"], "cors")
                self.assertEqual(
                    headers["content-type"], "application/x-www-form-urlencoded"
                )

    def test_boolean_success_acknowledgement_is_accepted(self):
        self.response.read.return_value = b'{"success":true}'
        self.portal.send_code("alice", "email")
        self.portal.raw.open.assert_called_once()

    def test_explicit_api_rejection_is_an_error(self):
        for success in ("false", False, None, 0, 1, "", "TRUE"):
            with self.subTest(success=success):
                self.response.read.return_value = json.dumps(
                    {"success": success}
                ).encode("utf-8")
                with self.assertRaises(kvpn.KvpnError):
                    self.portal.send_code("alice", "email")

    def test_missing_success_or_wrong_response_shape_is_an_error(self):
        for payload in ({}, {"message": "OK"}, [], None, "true", 1):
            with self.subTest(payload=payload):
                self.response.read.return_value = json.dumps(payload).encode("utf-8")
                with self.assertRaises(kvpn.KvpnError):
                    self.portal.send_code("alice", "email")

    def test_empty_malformed_and_html_responses_are_errors(self):
        for body in (b"", b"{invalid json", b"<html>Login required</html>"):
            with self.subTest(body=body):
                self.response.read.return_value = body
                with self.assertRaises(kvpn.KvpnError):
                    self.portal.send_code("alice", "email")

    def test_non_200_responses_cannot_claim_success(self):
        for status in (201, 302, 401, 403, 429, 500):
            with self.subTest(status=status):
                self.response.getcode.return_value = status
                self.response.headers = {"Location": kvpn.PORTAL + "/request"}
                with self.assertRaises(kvpn.KvpnError):
                    self.portal.send_code("alice", "email")

    def test_missing_email_has_an_actionable_error(self):
        self.response.read.return_value = b'{"success":"false","reason":"emailNull"}'
        with self.assertRaisesRegex(kvpn.KvpnError, "[Ee]mail"):
            self.portal.send_code("alice", "email")

    def test_missing_phone_has_an_actionable_error(self):
        self.response.read.return_value = (
            b'{"success":"false","reason":"phoneNumberNull"}'
        )
        with self.assertRaisesRegex(kvpn.KvpnError, "[Pp]hone|SMS"):
            self.portal.send_code("alice", "sms")

    def test_network_errors_are_reported_without_exposing_request_details(self):
        self.portal.raw.open.side_effect = urllib.error.URLError(
            "test-private-session-token"
        )
        with self.assertRaises(kvpn.KvpnError) as error:
            self.portal.send_code("alice", "email")
        self.assertIn("EMAIL", str(error.exception))
        self.assertIn("URLError", str(error.exception))
        self.assertNotIn("test-private-session-token", str(error.exception))

    def test_server_rejection_does_not_dump_private_response_data(self):
        self.response.read.return_value = json.dumps(
            {
                "success": "false",
                "reason": "alice@example.test: test-private-session-token",
                "message": "test-private-response-data",
            }
        ).encode("utf-8")
        with self.assertRaises(kvpn.KvpnError) as error:
            self.portal.send_code("alice", "email")
        self.assertNotIn("alice@example.test", str(error.exception))
        self.assertNotIn("test-private-session-token", str(error.exception))
        self.assertNotIn("test-private-response-data", str(error.exception))

    def test_verification_uses_the_selected_delivery_method(self):
        for send_type, otp_flag in (("sms", "1"), ("email", "2")):
            with self.subTest(send_type=send_type), mock.patch.object(
                self.portal,
                "_raw",
                side_effect=[
                    (302, {"Location": kvpn.PORTAL + "/vpn/test-client"}, ""),
                    (200, {}, 'var message = "test-secondary-token";'),
                ],
            ) as request:
                token = self.portal.verify("alice", "123456", send_type)
                self.assertEqual(token, "test-secondary-token")
                first_call = request.call_args_list[0]
                self.assertEqual(first_call.args[0], "POST")
                self.assertEqual(
                    first_call.args[1], kvpn.PORTAL + "/j_spring_security_check.do"
                )
                self.assertEqual(
                    first_call.args[2],
                    {
                        "j_username": "alice",
                        "j_password": "123456",
                        "otp_flag": otp_flag,
                    },
                )

    def test_failed_email_request_never_prompts_for_otp_or_claims_acceptance(self):
        self.response.read.return_value = b'{"success":"false","reason":"emailNull"}'
        output = io.StringIO()
        with mock.patch.object(
            kvpn, "load_credentials", return_value=("alice", "password", kvpn.REALMS[0])
        ), mock.patch.object(kvpn, "Ivanti") as ivanti, mock.patch.object(
            kvpn, "Portal", return_value=self.portal
        ), mock.patch.object(self.portal, "begin"), mock.patch.object(
            self.portal, "verify"
        ) as verify, mock.patch.object(
            kvpn, "choose", return_value="Email"
        ), mock.patch.object(
            kvpn, "launch_tunnel", return_value=0
        ) as launch_tunnel, mock.patch(
            "builtins.input", return_value="123456"
        ) as prompt, mock.patch.object(
            kvpn.sys, "stdout", output
        ):
            with self.assertRaises(kvpn.KvpnError):
                kvpn.main([])
            prompt.assert_not_called()
            verify.assert_not_called()
            launch_tunnel.assert_not_called()
            ivanti.return_value.finish.assert_not_called()
        self.assertNotIn("Code sent", output.getvalue())
        self.assertNotIn("Portal accepted", output.getvalue())

    def test_cli_passes_selected_method_to_verification_after_acceptance(self):
        for choice, send_type in (("Email", "email"), ("SMS", "sms")):
            with self.subTest(choice=choice):
                output = io.StringIO()
                with mock.patch.object(
                    kvpn,
                    "load_credentials",
                    return_value=("alice", "password", kvpn.REALMS[0]),
                ), mock.patch.object(kvpn, "Ivanti"), mock.patch.object(
                    kvpn, "Portal", return_value=self.portal
                ), mock.patch.object(self.portal, "begin"), mock.patch.object(
                    self.portal, "verify", return_value="test-secondary-token"
                ) as verify, mock.patch.object(
                    kvpn, "choose", return_value=choice
                ), mock.patch("builtins.input", return_value="123456"), mock.patch.object(
                    kvpn, "launch_tunnel", return_value=0
                ), mock.patch.object(kvpn.sys, "stdout", output):
                    with self.assertRaises(SystemExit) as exit_result:
                        kvpn.main([])
                    self.assertEqual(exit_result.exception.code, 0)
                    verify.assert_called_once_with(
                        "alice", "123456", send_type=send_type
                    )
                self.assertIn(
                    "Portal accepted the %s code request" % send_type.upper(),
                    output.getvalue(),
                )
                self.assertNotIn("Code sent", output.getvalue())


if __name__ == "__main__":
    unittest.main()
