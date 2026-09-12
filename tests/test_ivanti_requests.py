from types import SimpleNamespace
import unittest
import urllib.parse
from unittest import mock

from test_kvpn import kvpn


class IvantiRequestTests(unittest.TestCase):
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
        self.response.read.return_value = b"<html>test-response</html>"

    def test_primary_uses_same_origin_ajax_request(self):
        self.ivanti.authenticate_primary("alice", "password", kvpn.REALMS[0], "Tn2Xf8|test-code")
        self.ivanti.opener.open.assert_called_once()
        request = self.ivanti.opener.open.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["origin"], kvpn.IVANTI)
        self.assertEqual(headers["x-requested-with"], "XMLHttpRequest")
        self.assertEqual(headers["accept"], "*/*")
        self.assertEqual(headers["referer"], self.ivanti.welcome_url)
        self.assertEqual(headers["content-type"], "application/x-www-form-urlencoded")
        self.assertEqual(request.full_url, self.ivanti.login_url)
        self.assertEqual(urllib.parse.parse_qs(request.data.decode("utf-8")), {
            "username": ["alice"], "password": ["password"], "realm": [kvpn.REALMS[0]],
            "tz_offset": ["540"], "password#2": ["Tn2Xf8|test-code"],
        })

    def test_final_login_has_origin_without_ajax_header(self):
        self.ivanti.cj = [SimpleNamespace(name="DSID", value="test-dsid")]
        self.assertEqual(
            self.ivanti.finish("alice", "password", kvpn.REALMS[0], "test-otp-token"),
            "test-dsid",
        )
        request = self.ivanti.opener.open.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["origin"], kvpn.IVANTI)
        self.assertNotIn("x-requested-with", headers)
        self.assertEqual(
            urllib.parse.parse_qs(request.data.decode("utf-8"))["password#2"], ["test-otp-token"]
        )

    def test_http_post_preserves_explicit_headers_and_response(self):
        result = kvpn.http_post(
            self.ivanti.opener, self.ivanti.login_url, {"field": "value"},
            referer=self.ivanti.welcome_url, headers={"Origin": kvpn.IVANTI},
        )
        self.assertEqual(result, (self.ivanti.login_url, "<html>test-response</html>"))
        request = self.ivanti.opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Origin"), kvpn.IVANTI)
        self.assertEqual(request.get_method(), "POST")


if __name__ == "__main__":
    unittest.main()
