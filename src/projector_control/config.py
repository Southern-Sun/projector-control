"""Load and initialize the per-user TOML configuration."""

import math
import os
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
import tomllib


class ConfigurationError(Exception):
    """Indicate missing or invalid configuration."""


@dataclass(frozen=True)
class Configuration:
    """Validated connection settings."""

    host: str
    port: int = 4352
    timeout: float = 5.0
    password: str | None = field(default=None, repr=False)


def config_path() -> Path:
    """Return the user configuration path."""
    return Path.home() / ".config" / "projector-control" / "config.toml"


def initialize(path: Path | None = None) -> bool:
    """Create a private example config, returning false if it exists."""
    path = path if path is not None else config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(files("projector_control").joinpath("config.example.toml").read_text())
    except FileExistsError:
        return False
    except OSError:
        raise ConfigurationError(f"Cannot create {path}; check directory permissions.") from None
    return True


def load_configuration(
    path: Path | None = None, *, host: str | None = None, port: int | None = None
) -> Configuration:
    """Read TOML and resolve environment credentials before file credentials."""
    path = path if path is not None else config_path()
    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
    except FileNotFoundError:
        raise ConfigurationError(f"Configuration missing: {path}. Run 'projector init' and edit it.") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        raise ConfigurationError(f"Invalid TOML in {path}; check its syntax.") from None
    except OSError:
        raise ConfigurationError(f"Cannot read {path}; check file permissions.") from None
    projector = data.get("projector", {})
    authentication = data.get("authentication", {})
    if not isinstance(projector, dict) or not isinstance(authentication, dict):
        raise ConfigurationError("projector and authentication must be TOML tables.")
    resolved_host = host if host is not None else projector.get("host")
    resolved_port = port if port is not None else projector.get("port", 4352)
    timeout = projector.get("timeout", 5.0)
    if not isinstance(resolved_host, str) or not resolved_host.strip() or any(character.isspace() for character in resolved_host):
        raise ConfigurationError("Set projector.host to a nonempty IP address or hostname without whitespace.")
    if type(resolved_port) is not int or not 1 <= resolved_port <= 65535:
        raise ConfigurationError("projector.port must be an integer from 1 to 65535.")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ConfigurationError("projector.timeout must be a positive finite number of seconds.")
    environment_name = authentication.get("password_env", "PROJECTOR_PJLINK_PASSWORD")
    password = authentication.get("password")
    if not isinstance(environment_name, str) or not environment_name or "=" in environment_name or "\0" in environment_name:
        raise ConfigurationError("authentication.password_env must be a valid environment variable name.")
    if password is not None and not isinstance(password, str):
        raise ConfigurationError("authentication.password must be a string.")
    password = os.environ.get(environment_name, password)
    if password is not None and (not password.isascii() or len(password) > 32 or any(ord(character) < 32 or ord(character) == 127 for character in password)):
        raise ConfigurationError("PJLink passwords must contain at most 32 printable ASCII characters.")
    return Configuration(resolved_host, resolved_port, float(timeout), password)
