"""Implement the PJLink Class 1 power commands using one connection per command."""

import hashlib
import re
import socket
import time
from enum import Enum

from .config import Configuration


class PJLinkError(Exception):
    """Indicate a PJLink communication or protocol failure."""


class ConnectionError(PJLinkError):
    """Indicate a network connection failure or timeout."""


class AuthenticationError(PJLinkError):
    """Indicate missing or rejected credentials."""


class PowerState(Enum):
    """Represent the four PJLink power states."""

    OFF = "0"
    ON = "1"
    COOLING = "2"
    WARMING = "3"

    @property
    def label(self) -> str:
        """Return the human-readable state."""
        return self.name.capitalize()


ERRORS = {
    "ERR1": "Undefined command; verify PJLink Class 1 support.",
    "ERR2": "Invalid parameter; the projector rejected the power command.",
    "ERR3": "Command unavailable now; wait for warming or cooling to finish and retry.",
    "ERR4": "Projector failure; check the projector's error indicators and manual.",
}


class PJLinkClient:
    """Send power commands with bounded, complete CR-terminated reads."""

    def __init__(self, configuration: Configuration) -> None:
        """Store validated connection settings."""
        self.configuration = configuration

    def power_status(self) -> PowerState:
        """Query power without changing it, authenticating when required."""
        response = self._command("?")
        try:
            return PowerState(response)
        except ValueError:
            raise PJLinkError("Unexpected power status; expected a value from 0 to 3.") from None

    def set_power(self, enabled: bool) -> None:
        """Request power on or off and require acknowledgement."""
        if self._command("1" if enabled else "0") != "OK":
            raise PJLinkError("Unexpected power command acknowledgement; expected OK.")

    def _command(self, parameter: str) -> str:
        settings = self.configuration
        try:
            with socket.create_connection((settings.host, settings.port), settings.timeout) as connection:
                deadline = time.monotonic() + settings.timeout
                greeting = self._read_line(connection, deadline)
                prefix = ""
                if greeting == "PJLINK 0":
                    pass
                elif re.fullmatch(r"PJLINK 1 [0-9a-fA-F]{8}", greeting):
                    if not settings.password:
                        raise AuthenticationError("Projector requires authentication; set the configured password environment variable or authentication.password.")
                    prefix = hashlib.md5((greeting[9:] + settings.password).encode("ascii"), usedforsecurity=False).hexdigest()
                elif greeting.startswith("PJLINK 1"):
                    raise PJLinkError("Malformed PJLink authentication challenge.")
                else:
                    raise PJLinkError("Unexpected PJLink greeting or unsupported authentication mode; verify host and port.")
                connection.settimeout(self._remaining(deadline))
                connection.sendall(f"{prefix}%1POWR {parameter}\r".encode("ascii"))
                response = self._read_line(connection, deadline)
                if response == "PJLINK ERRA":
                    raise AuthenticationError("Authentication rejected; check the PJLink password on the projector and in your environment/configuration.")
                if not response.startswith("%1POWR="):
                    raise PJLinkError("Unexpected PJLink response; expected %1POWR=.")
                value = response[7:]
                if value in ERRORS:
                    raise PJLinkError(f"{value}: {ERRORS[value]}")
                return value
        except TimeoutError:
            raise ConnectionError(f"Timed out communicating with {settings.host}:{settings.port}; check LAN access, standby network settings, or increase timeout.") from None
        except OSError:
            raise ConnectionError(f"Cannot communicate with {settings.host}:{settings.port}; check the address, PJLink service, LAN connection, and firewall.") from None

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return remaining

    @classmethod
    def _read_line(cls, connection: socket.socket, deadline: float) -> str:
        # A byte at a time avoids consuming bytes belonging to a subsequent line.
        response = bytearray()
        while len(response) <= 512:
            connection.settimeout(cls._remaining(deadline))
            chunk = connection.recv(1)
            if not chunk:
                raise PJLinkError("Projector closed the connection before a complete response arrived.")
            if chunk == b"\r":
                try:
                    return response.decode("ascii")
                except UnicodeDecodeError:
                    raise PJLinkError("Projector returned a non-ASCII response.") from None
            response.extend(chunk)
        raise PJLinkError("Projector response exceeded the 512-byte safety limit.")
