"""Verify configuration handling and the shell interface."""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from projector_control.cli import main
from projector_control.client import AuthenticationError, ConnectionError, PJLinkError, PowerState
from projector_control.config import Configuration, ConfigurationError, initialize, load_configuration


class ConfigurationTests(unittest.TestCase):
    """Validate private initialization, TOML types, and credential precedence."""

    def setUp(self):
        """Create an isolated config path."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "nested" / "config.toml"

    def test_initialize_no_overwrite(self):
        """Create private configuration and preserve existing content."""
        self.assertTrue(initialize(self.path))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        original = self.path.read_bytes()
        self.assertFalse(initialize(self.path))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(load_configuration(self.path).host, "192.168.88.50")
        self.assertEqual(original, Path("config.example.toml").read_bytes())

    def test_missing_and_invalid(self):
        """Reject missing files, invalid syntax, and invalid field types."""
        with self.assertRaises(ConfigurationError):
            load_configuration(self.path)
        self.path.parent.mkdir()
        for content in (
            "broken = [", "", 'projector = "bad"',
            '[projector]\nhost = " "', '[projector]\nhost = 1',
            '[projector]\nhost = "host"\nport = true',
            '[projector]\nhost = "host"\nport = 65536',
            '[projector]\nhost = "host"\ntimeout = nan',
            '[projector]\nhost = "host"\ntimeout = 0',
            '[projector]\nhost = "host"\n[authentication]\npassword = 123',
            '[projector]\nhost = "host"\n[authentication]\npassword_env = ""',
        ):
            with self.subTest(content=content):
                self.path.write_text(content)
                with self.assertRaises(ConfigurationError):
                    load_configuration(self.path)

    def test_password_and_overrides(self):
        """Prefer the environment password and accept connection overrides."""
        initialize(self.path)
        with self.path.open("a") as output:
            output.write('password = "fallback"\n')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_configuration(self.path).password, "fallback")
        with patch.dict(os.environ, {"PROJECTOR_PJLINK_PASSWORD": "secret"}):
            configuration = load_configuration(self.path, host="localhost", port=1234)
            self.assertEqual(configuration.password, "secret")
            self.assertNotIn("secret", repr(configuration))
            self.assertEqual((configuration.host, configuration.port), ("localhost", 1234))


class CLITests(unittest.TestCase):
    """Check output, safe testing, overrides and stable exit statuses."""

    def test_safe_test_and_status(self):
        """The integration test only queries status."""
        for command in ("test", "status"):
            with patch("projector_control.cli.load_configuration", return_value=Configuration("host")), patch("projector_control.cli.PJLinkClient") as client, redirect_stdout(io.StringIO()) as output:
                client.return_value.power_status.return_value = PowerState.WARMING
                self.assertEqual(main([command]), 0)
                self.assertIn("Warming", output.getvalue())
                client.return_value.set_power.assert_not_called()

    def test_errors_and_credential_redaction(self):
        """Send actionable errors to stderr with predictable codes."""
        for exception, code in ((ConfigurationError("config problem"), 2), (ConnectionError("network problem"), 3), (AuthenticationError("auth problem"), 4), (PJLinkError("protocol problem"), 5)):
            with patch("projector_control.cli.load_configuration", side_effect=exception), redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(["status"]), code)
                self.assertIn(str(exception), output.getvalue())

    def test_power_and_overrides(self):
        """Accept host/port options before or after the subcommand."""
        for arguments, enabled in ((["--host", "local", "on", "--port", "1234"], True), (["off", "--host", "local", "--port", "1234"], False)):
            with patch("projector_control.cli.load_configuration", return_value=Configuration("local")) as load, patch("projector_control.cli.PJLinkClient") as client, redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments), 0)
                load.assert_called_once_with(host="local", port=1234)
                client.return_value.set_power.assert_called_once_with(enabled)


if __name__ == "__main__":
    unittest.main()
