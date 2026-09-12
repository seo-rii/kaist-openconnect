import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader("kvpn", str(ROOT / "kvpn"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
kvpn = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(kvpn)


class CliTests(unittest.TestCase):
    def test_help_smoke_test(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "kvpn"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: kvpn", result.stdout)


class PlatformTests(unittest.TestCase):
    def test_windows_config_uses_appdata(self):
        with mock.patch.object(kvpn.sys, "platform", "win32"), mock.patch.dict(
            kvpn.os.environ, {"APPDATA": r"C:\Users\test\AppData\Roaming"}
        ):
            self.assertEqual(
                kvpn.config_path(),
                os.path.join(r"C:\Users\test\AppData\Roaming", "kvpn", "config.json"),
            )

    def test_non_windows_config_uses_xdg_config_home(self):
        with mock.patch.object(kvpn.sys, "platform", "linux"), mock.patch.dict(
            kvpn.os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg"}
        ):
            self.assertEqual(
                kvpn.config_path(), os.path.join("/tmp/xdg", "kvpn", "config.json")
            )

    def test_windows_finds_openconnect_in_default_install_dir(self):
        program_files = r"C:\Program Files"
        expected = os.path.join(program_files, "OpenConnect", "openconnect.exe")
        with mock.patch.object(kvpn.sys, "platform", "win32"), mock.patch.dict(
            kvpn.os.environ, {"ProgramFiles": program_files}, clear=True
        ), mock.patch.object(kvpn.shutil, "which", return_value=None), mock.patch.object(
            kvpn.os.path, "isfile", side_effect=lambda path: path == expected
        ):
            self.assertEqual(kvpn.find_openconnect(), expected)

    def test_openconnect_override_must_exist(self):
        with mock.patch.dict(
            kvpn.os.environ, {"KVPN_OPENCONNECT": "/missing/openconnect"}, clear=True
        ), mock.patch.object(kvpn.shutil, "which", return_value=None), mock.patch.object(
            kvpn.os.path, "isfile", return_value=False
        ):
            with self.assertRaisesRegex(kvpn.KvpnError, "KVPN_OPENCONNECT"):
                kvpn.find_openconnect()

    def test_windows_tunnel_command_does_not_use_sudo(self):
        with mock.patch.object(kvpn.sys, "platform", "win32"):
            self.assertEqual(
                kvpn.tunnel_command(r"C:\OpenConnect\openconnect.exe"),
                [
                    r"C:\OpenConnect\openconnect.exe",
                    "--protocol=nc",
                    "--cookie-on-stdin",
                    "kvpn.kaist.ac.kr",
                ],
            )

    def test_non_root_linux_tunnel_command_uses_sudo(self):
        with mock.patch.object(kvpn.sys, "platform", "linux"), mock.patch.object(
            kvpn.os, "geteuid", return_value=1000, create=True
        ), mock.patch.object(kvpn.shutil, "which", return_value="/usr/bin/sudo"):
            self.assertEqual(
                kvpn.tunnel_command("/usr/bin/openconnect")[:2],
                ["/usr/bin/sudo", "/usr/bin/openconnect"],
            )

    def test_windows_launch_requires_administrator(self):
        with mock.patch.object(kvpn.sys, "platform", "win32"), mock.patch.object(
            kvpn, "find_openconnect", return_value=r"C:\OpenConnect\openconnect.exe"
        ), mock.patch.object(kvpn, "windows_is_admin", return_value=False), mock.patch.object(
            kvpn.subprocess, "Popen"
        ) as popen:
            with self.assertRaisesRegex(kvpn.KvpnError, "Administrator"):
                kvpn.launch_tunnel("secret")
            popen.assert_not_called()


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

    def test_windows_password_uses_credential_manager(self):
        path = os.path.join(self.tempdir.name, "config.json")
        with mock.patch.object(kvpn.sys, "platform", "win32"), mock.patch.object(
            kvpn, "config_path", return_value=path
        ), mock.patch.object(kvpn, "windows_credential_set") as credential_set:
            where = kvpn.save_credentials("alice", "not-in-json", kvpn.REALMS[0])
            credential_set.assert_called_once_with("alice", "not-in-json")
            self.assertIn("Windows Credential Manager", where)
            self.assertNotIn("not-in-json", Path(path).read_text())

    def test_windows_password_loads_from_credential_manager(self):
        path = os.path.join(self.tempdir.name, "config.json")
        Path(path).write_text('{"username": "alice", "realm": "KAIST Members"}')
        with mock.patch.object(kvpn.sys, "platform", "win32"), mock.patch.object(
            kvpn, "config_path", return_value=path
        ), mock.patch.object(
            kvpn, "windows_credential_get", return_value="password"
        ) as credential_get:
            self.assertEqual(
                kvpn.load_credentials(), ("alice", "password", "KAIST Members")
            )
            credential_get.assert_called_once_with("alice")

    @unittest.skipUnless(sys.platform == "win32", "Windows API test")
    def test_windows_credential_manager_api_smoke_test(self):
        target = "kaist-openconnect/kvpn-test-%s" % os.getpid()
        with mock.patch.object(kvpn, "WINDOWS_CREDENTIAL_TARGET", target):
            self.assertIsNone(kvpn.windows_credential_get("nobody"))

    @unittest.skipIf(os.name == "nt", "POSIX permission test")
    def test_linux_config_file_permissions_are_private(self):
        path = os.path.join(self.tempdir.name, "kvpn", "config.json")
        with mock.patch.object(kvpn.sys, "platform", "linux"), mock.patch.object(
            kvpn, "config_path", return_value=path
        ), mock.patch.object(kvpn, "keychain_available", return_value=False):
            kvpn.save_credentials("alice", "password", kvpn.REALMS[0])
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
