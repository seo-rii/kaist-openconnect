import http.cookiejar
import io
import unittest
import urllib.parse
from unittest import mock

from test_kvpn import kvpn


PARENT = kvpn.IVANTI + "/dana-na/auth/url_test-session/welcome.cgi"
CORRELATION = "test-correlation-token"
HANDSHAKE = "Tn2Xf8|" + CORRELATION
HANDSHAKE_PAGE = '<input type="hidden" name="code" value="%s">' % HANDSHAKE
# This models an enrolled account's required menu, not a captured authenticated response.
MENU_PAGE = '<html><script src="/js/mainMenu.js"></script></html>'
# The public /request template was observed with an empty username; use test context here.
REQUEST_PAGE = """<script>
$(function(){ post('/view/redirect', {user_name:'alice',
client_id:'rmwb8juiS8oJ5XVK',app_name:'vpn2auth',parent:'https%3A%2F%2Fkvpn.kaist.ac.kr%2F'}); });
</script>"""


class HandshakeTests(unittest.TestCase):
    # The gateway's ags_frame.js posts the full Tn2Xf8|code to login.cgi,
    # then sends only code to the portal's onepassCheck endpoint.
    def setUp(self):
        debug_env = mock.patch.dict(
            kvpn.os.environ, {"KVPN_DEBUG": "", "KVPN_DEBUG_LOG": ""}
        )
        debug_env.start()
        self.addCleanup(debug_env.stop)
        self.portal = kvpn.Portal.__new__(kvpn.Portal)
        self.portal.parent = PARENT
        self.portal.opener = mock.sentinel.portal_opener
        self.portal.raw = mock.MagicMock()
        self.ivanti = kvpn.Ivanti.__new__(kvpn.Ivanti)
        self.ivanti.opener = mock.sentinel.ivanti_opener
        self.ivanti.cj = http.cookiejar.CookieJar()
        self.ivanti.welcome_url = PARENT
        self.ivanti.login_url = PARENT.replace("welcome.cgi", "login.cgi")

    def begin_portal(self):
        with mock.patch.object(
            kvpn, "http_get", return_value=(kvpn.PORTAL + "/view/redirectVPN", HANDSHAKE_PAGE)
        ):
            return self.portal.begin("alice")

    def test_begin_returns_full_handshake_without_starting_otp_initialization(self):
        with mock.patch.object(
            kvpn, "http_get", return_value=(kvpn.PORTAL + "/view/redirectVPN", HANDSHAKE_PAGE)
        ) as get:
            self.assertEqual(self.portal.begin("alice"), HANDSHAKE)
        get.assert_called_once()
        self.assertIs(get.call_args.args[0], self.portal.opener)
        self.assertEqual(
            urllib.parse.urlsplit(get.call_args.args[1]).path, "/view/redirectVPN"
        )

    def test_malformed_or_unsupported_handshakes_are_rejected(self):
        for value in ("", "plain-correlation", "wrong-tag|private-code", "Tn2Xf8|", "Tn2Xf8|a|b"):
            with self.subTest(value=value), mock.patch.object(
                kvpn, "http_get",
                return_value=(kvpn.PORTAL + "/view/redirectVPN", '<input name="code" value="%s">' % value),
            ) as get:
                with self.assertRaises(kvpn.KvpnError) as error:
                    self.portal.begin("alice")
                self.assertNotIn("private-code", str(error.exception))
                get.assert_called_once()

    def test_primary_auth_posts_credentials_and_full_handshake_without_requiring_dsid(self):
        for final_url in (PARENT, PARENT + "?p=failed"):
            with self.subTest(final_url=final_url), mock.patch.object(
                kvpn, "http_post", return_value=(final_url, '<input name="password#2">')
            ) as post:
                self.ivanti.authenticate_primary("alice", "private-password", kvpn.REALMS[0], HANDSHAKE)
                self.assertIs(post.call_args.args[0], self.ivanti.opener)
                self.assertEqual(post.call_args.args[1], self.ivanti.login_url)
                self.assertEqual(post.call_args.args[2], {
                    "tz_offset": "540", "username": "alice", "password": "private-password",
                    "realm": kvpn.REALMS[0], "password#2": HANDSHAKE,
                })
                self.assertEqual(post.call_args.kwargs["referer"], PARENT)
                self.assertIsNone(kvpn.cookie_value(self.ivanti.cj, "DSID"))

    def test_locked_primary_auth_fails_without_exposing_response_secrets(self):
        with mock.patch.object(
            kvpn, "http_post",
            return_value=(PARENT + "?p=locked&code=private-code", "private-response-data"),
        ):
            with self.assertRaises(kvpn.KvpnError) as error:
                self.ivanti.authenticate_primary("alice", "private-password", kvpn.REALMS[0], HANDSHAKE)
        for secret in ("private-code", "private-response-data", "private-password", CORRELATION):
            self.assertNotIn(secret, str(error.exception))

    def test_prepare_otp_uses_suffix_and_emulates_request_page_post(self):
        self.begin_portal()
        with mock.patch.object(kvpn, "http_get", side_effect=[
            (kvpn.PORTAL + "/vpnInit", '<script>location.href="/oauth/authorize";</script>'),
            (kvpn.PORTAL + "/request", REQUEST_PAGE),
            (kvpn.PORTAL + "/view/mainMenu", MENU_PAGE),
        ]) as get, mock.patch.object(
            kvpn, "http_post",
            return_value=(kvpn.PORTAL + "/view/redirect", "<script>location.href='/view/mainMenu';</script>"),
        ) as post:
            request_order = mock.Mock()
            request_order.attach_mock(get, "get")
            request_order.attach_mock(post, "post")
            self.portal.prepare_otp("alice")
        self.assertEqual(
            [call[0] for call in request_order.mock_calls], ["get", "get", "post", "get"]
        )
        first_url = get.call_args_list[0].args[1]
        self.assertEqual(urllib.parse.urlsplit(first_url).path, "/view/onepassCheck")
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(first_url).query), {
            "user_name": ["alice"], "code": [CORRELATION], "parent": [PARENT],
        })
        self.assertNotIn("Tn2Xf8", first_url)
        for call in get.call_args_list:
            self.assertIs(call.args[0], self.portal.opener)
        authorize = urllib.parse.urlsplit(get.call_args_list[1].args[1])
        self.assertEqual(authorize.path, "/oauth/authorize")
        authorize_fields = urllib.parse.parse_qs(authorize.query)
        self.assertEqual(authorize_fields["client_id"], [kvpn.CLIENT_ID])
        self.assertEqual(authorize_fields["user_name"], ["alice"])
        self.assertEqual(authorize_fields["redirect_uri"], [kvpn.PORTAL + "/vpn/" + kvpn.CLIENT_ID])
        self.assertEqual(get.call_args_list[2].args[1], kvpn.PORTAL + "/view/mainMenu")
        post.assert_called_once()
        self.assertIs(post.call_args.args[0], self.portal.opener)
        self.assertEqual(post.call_args.args[1], kvpn.PORTAL + "/view/redirect")
        self.assertEqual(post.call_args.args[2], {
            "user_name": "alice", "client_id": kvpn.CLIENT_ID, "app_name": kvpn.APP_NAME,
            "parent": urllib.parse.quote(PARENT, safe=""),
        })

    def test_prepare_otp_accepts_menu_returned_directly_by_redirect_post(self):
        self.begin_portal()
        with mock.patch.object(kvpn, "http_get", side_effect=[
            (kvpn.PORTAL + "/vpnInit", "<html>Initialized</html>"),
            (kvpn.PORTAL + "/request", REQUEST_PAGE),
        ]) as get, mock.patch.object(
            kvpn, "http_post", return_value=(kvpn.PORTAL + "/view/mainMenu", MENU_PAGE),
        ):
            self.portal.prepare_otp("alice")
        self.assertEqual(get.call_count, 2)

    def test_onepass_errors_stop_before_oauth_or_request_post(self):
        self.begin_portal()
        for script in ("invalidAccess.js", "timeOut.js"):
            with self.subTest(script=script), mock.patch.object(
                kvpn, "http_get",
                return_value=(kvpn.PORTAL + "/vpnInit", '<script src="/js/%s"></script>' % script),
            ) as get, mock.patch.object(kvpn, "http_post") as post:
                with self.assertRaises(kvpn.KvpnError):
                    self.portal.prepare_otp("alice")
                get.assert_called_once()
                post.assert_not_called()

    def test_unexpected_onepass_response_stops_before_oauth(self):
        self.begin_portal()
        for body in ("", "<html>Unrecognized page</html>"):
            with self.subTest(body=body), mock.patch.object(
                kvpn, "http_get", return_value=(kvpn.PORTAL + "/view/onepassCheck", body)
            ) as get, mock.patch.object(kvpn, "http_post") as post:
                with self.assertRaises(kvpn.KvpnError):
                    self.portal.prepare_otp("alice")
                get.assert_called_once()
                post.assert_not_called()

    def test_request_page_without_known_post_handoff_is_rejected(self):
        self.begin_portal()
        for body in ("", '<form action="/unknown">Unrecognized page</form>'):
            with self.subTest(body=body), mock.patch.object(kvpn, "http_get", side_effect=[
                (kvpn.PORTAL + "/vpnInit", "<html>Initialized</html>"),
                (kvpn.PORTAL + "/request", body),
            ]) as get, mock.patch.object(kvpn, "http_post") as post:
                with self.assertRaises(kvpn.KvpnError):
                    self.portal.prepare_otp("alice")
                self.assertEqual(get.call_count, 2)
                post.assert_not_called()

    def test_error_pages_during_oauth_or_redirect_are_rejected(self):
        self.begin_portal()
        for stage in ("oauth", "redirect"):
            for script in ("invalidAccess.js", "timeOut.js"):
                error_page = '<script src="/js/%s"></script>' % script
                with self.subTest(stage=stage, script=script), mock.patch.object(
                    kvpn, "http_get", side_effect=[
                        (kvpn.PORTAL + "/vpnInit", "<html>Initialized</html>"),
                        (kvpn.PORTAL + "/request", error_page if stage == "oauth" else REQUEST_PAGE),
                    ]
                ) as get, mock.patch.object(
                    kvpn, "http_post", return_value=(kvpn.PORTAL + "/view/redirect", error_page)
                ) as post:
                    with self.assertRaises(kvpn.KvpnError):
                        self.portal.prepare_otp("alice")
                    self.assertEqual(get.call_count, 2)
                    self.assertEqual(post.call_count, 0 if stage == "oauth" else 1)

    def test_enrollment_and_unknown_responses_are_not_otp_readiness(self):
        self.begin_portal()
        for response in (
            "<script>location.href='/view/provisionStart';</script>",
            "", "<html>Unrecognized page</html>",
        ):
            with self.subTest(response=response), mock.patch.object(kvpn, "http_get", side_effect=[
                (kvpn.PORTAL + "/vpnInit", "<html>Initialized</html>"),
                (kvpn.PORTAL + "/request", REQUEST_PAGE),
            ]) as get, mock.patch.object(
                kvpn, "http_post", return_value=(kvpn.PORTAL + "/view/redirect", response),
            ):
                with self.assertRaises(kvpn.KvpnError):
                    self.portal.prepare_otp("alice")
                self.assertEqual(get.call_count, 2)

    def test_followed_mainmenu_route_still_requires_actual_otp_menu(self):
        self.begin_portal()
        with mock.patch.object(kvpn, "http_get", side_effect=[
            (kvpn.PORTAL + "/vpnInit", "<html>Initialized</html>"),
            (kvpn.PORTAL + "/request", REQUEST_PAGE),
            (kvpn.PORTAL + "/view/mainMenu", "<html>Login required</html>"),
        ]), mock.patch.object(
            kvpn, "http_post",
            return_value=(kvpn.PORTAL + "/view/redirect", "<script>location.href='/view/mainMenu';</script>"),
        ):
            with self.assertRaises(kvpn.KvpnError):
                self.portal.prepare_otp("alice")

    def test_cli_completes_primary_handshake_before_otp_initialization_and_send(self):
        flow = mock.Mock()
        flow.ivanti.begin.return_value = PARENT
        flow.portal.begin.return_value = HANDSHAKE
        flow.portal.verify.return_value = "test-secondary-token"
        with mock.patch.object(kvpn, "load_credentials", return_value=("alice", "password", kvpn.REALMS[0])), \
                mock.patch.object(kvpn, "Ivanti", return_value=flow.ivanti), \
                mock.patch.object(kvpn, "Portal", return_value=flow.portal), \
                mock.patch.object(kvpn, "choose", return_value="SMS"), \
                mock.patch("builtins.input", return_value="123456"), \
                mock.patch.object(kvpn, "launch_tunnel", return_value=0), \
                mock.patch.object(kvpn.sys, "stdout", io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                kvpn.main([])
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(flow.mock_calls, [
            mock.call.ivanti.begin(),
            mock.call.portal.begin("alice"),
            mock.call.ivanti.authenticate_primary("alice", "password", kvpn.REALMS[0], HANDSHAKE),
            mock.call.portal.prepare_otp("alice"),
            mock.call.portal.send_code("alice", "sms"),
            mock.call.portal.verify("alice", "123456", send_type="sms"),
            mock.call.ivanti.finish("alice", "password", kvpn.REALMS[0], "test-secondary-token"),
        ])

    def test_handshake_diagnostics_do_not_expose_authentication_material(self):
        output = io.StringIO()
        with mock.patch.dict(kvpn.os.environ, {"KVPN_DEBUG": "1"}), \
                mock.patch.object(kvpn.sys, "stderr", output):
            self.begin_portal()
            with mock.patch.object(kvpn, "http_post", return_value=(PARENT + "?p=failed", "")):
                self.ivanti.authenticate_primary(
                    "alice", "private-primary-password", kvpn.REALMS[0], HANDSHAKE
                )
            with mock.patch.object(kvpn, "http_get", side_effect=[
                (kvpn.PORTAL + "/vpnInit", "<html>Initialized</html>"),
                (kvpn.PORTAL + "/view/mainMenu", MENU_PAGE),
            ]):
                self.portal.prepare_otp("alice")
        diagnostic = output.getvalue()
        self.assertIn("primary-auth", diagnostic)
        self.assertIn("otp-ready", diagnostic)
        for secret in (HANDSHAKE, CORRELATION, "private-primary-password", "alice"):
            self.assertNotIn(secret, diagnostic)

    def test_cli_invalid_initialization_never_sends_code_or_prompts_for_otp(self):
        with mock.patch.object(kvpn, "load_credentials", return_value=("alice", "password", kvpn.REALMS[0])), \
                mock.patch.object(kvpn, "Ivanti") as ivanti, \
                mock.patch.object(kvpn, "Portal", return_value=self.portal), \
                mock.patch.object(kvpn, "http_get", side_effect=[
                    (kvpn.PORTAL + "/view/redirectVPN", HANDSHAKE_PAGE),
                    (kvpn.PORTAL + "/vpnInit", '<script src="/js/invalidAccess.js"></script>'),
                ]), mock.patch.object(self.portal, "send_code") as send, \
                mock.patch.object(kvpn, "choose", return_value="SMS"), \
                mock.patch("builtins.input") as prompt, \
                mock.patch.object(kvpn.sys, "stdout", io.StringIO()):
            ivanti.return_value.begin.return_value = PARENT
            with self.assertRaises(kvpn.KvpnError):
                kvpn.main([])
            send.assert_not_called()
            prompt.assert_not_called()
            ivanti.return_value.authenticate_primary.assert_called_once_with(
                "alice", "password", kvpn.REALMS[0], HANDSHAKE
            )


if __name__ == "__main__":
    unittest.main()
