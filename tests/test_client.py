"""Exercise protocol behavior without accessing a projector."""

import unittest
from unittest.mock import MagicMock, patch

from projector_control.client import AuthenticationError, ConnectionError, PJLinkClient, PJLinkError, PowerState
from projector_control.config import Configuration


class ClientTests(unittest.TestCase):
    """Check wire commands, authentication, errors, and cleanup."""

    def run_exchange(self, greeting=b"PJLINK 0\r", response=b"%1POWR=0\r", password=None, enabled=None):
        """Supply fragmented socket data and execute a single command."""
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.side_effect = [bytes([value]) for value in greeting + response]
        with patch("projector_control.client.socket.create_connection", return_value=connection):
            client = PJLinkClient(Configuration("example.test", password=password))
            try:
                result = client.power_status() if enabled is None else client.set_power(enabled)
            finally:
                connection.__exit__.assert_called_once()
        return result, connection

    def test_all_power_states_and_partial_reads(self):
        """Read each state correctly from byte-sized TCP fragments."""
        for state in PowerState:
            with self.subTest(state=state):
                result, connection = self.run_exchange(response=f"%1POWR={state.value}\r".encode())
                self.assertEqual(result, state)
                connection.sendall.assert_called_once_with(b"%1POWR ?\r")

    def test_authenticated_query(self):
        """Match the published PJLink challenge-response test vector."""
        _, connection = self.run_exchange(greeting=b"PJLINK 1 498e4a67\r", password="JBMIAProjectorLink")
        connection.sendall.assert_called_once_with(b"5d8409bc1c3fa39749434aa3a5c38682%1POWR ?\r")

    def test_authentication_failure(self):
        """Reject invalid credentials explicitly."""
        with self.assertRaises(AuthenticationError):
            self.run_exchange(greeting=b"PJLINK 1 12345678\r", response=b"PJLINK ERRA\r", password="wrong")

    def test_missing_password(self):
        """Stop before issuing a command when credentials are absent."""
        with self.assertRaises(AuthenticationError):
            self.run_exchange(greeting=b"PJLINK 1 12345678\r")

    def test_on_off(self):
        """Send exact power commands and require OK."""
        for enabled in (True, False):
            _, connection = self.run_exchange(response=b"%1POWR=OK\r", enabled=enabled)
            connection.sendall.assert_called_once_with(f"%1POWR {int(enabled)}\r".encode())

    def test_protocol_errors(self):
        """Report all four Class 1 error codes."""
        for code in ("ERR1", "ERR2", "ERR3", "ERR4"):
            with self.subTest(code=code), self.assertRaisesRegex(PJLinkError, code):
                self.run_exchange(response=f"%1POWR={code}\r".encode())

    def test_unexpected_data(self):
        """Reject unsupported greetings, malformed responses and invalid states."""
        for greeting in (b"PJLINK 2\r", b"PJLINK 1 invalid\r", b"HTTP\r"):
            with self.subTest(greeting=greeting), self.assertRaises(PJLinkError):
                self.run_exchange(greeting=greeting)
        for response in (b"%1INPT=0\r", b"%1POWR=9\r", b"\xff\r", b"x" * 514):
            with self.subTest(response=response), self.assertRaises(PJLinkError):
                self.run_exchange(response=response)
        with self.assertRaises(PJLinkError):
            self.run_exchange(response=b"%1POWR=1\r", enabled=True)

    def test_connection_refused_and_timeout(self):
        """Translate connection failures into actionable network errors."""
        for error in (ConnectionRefusedError(), TimeoutError()):
            with patch("projector_control.client.socket.create_connection", side_effect=error):
                with self.assertRaises(ConnectionError):
                    PJLinkClient(Configuration("example.test")).power_status()

    def test_receive_failure_cleanup(self):
        """Close sockets after timeouts or premature EOF."""
        for failure in (TimeoutError(), b""):
            connection = MagicMock()
            connection.__enter__.return_value = connection
            connection.recv.side_effect = [failure]
            with patch("projector_control.client.socket.create_connection", return_value=connection):
                with self.assertRaises(PJLinkError):
                    PJLinkClient(Configuration("example.test")).power_status()
            connection.__exit__.assert_called_once()
