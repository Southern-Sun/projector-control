"""Provide the noninteractive projector command-line interface."""

import argparse
import sys

from .client import AuthenticationError, ConnectionError, PJLinkClient, PJLinkError
from .config import ConfigurationError, config_path, initialize, load_configuration


def main(argv: list[str] | None = None) -> int:
    """Run a command and return a predictable shell exit status."""
    parser = argparse.ArgumentParser(description="Control PJLink projector power over LAN.")
    parser.add_argument("--host", help="Override the configured host")
    parser.add_argument("--port", type=int, help="Override the configured TCP port")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, description in (
        ("init", "Create configuration without overwriting an existing file"),
        ("test", "Safely test TCP, authentication, and current power status"),
        ("status", "Show Off, On, Cooling, or Warming"),
        ("on", "Request power on"),
        ("off", "Request power off"),
    ):
        command = commands.add_parser(name, help=description, description=description)
        command.add_argument("--host", default=argparse.SUPPRESS, help="Override the configured host")
        command.add_argument("--port", type=int, default=argparse.SUPPRESS, help="Override the configured TCP port")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "init":
            created = initialize()
            print(f"{'Created' if created else 'Already exists; kept'} {config_path()}")
            return 0
        configuration = load_configuration(host=arguments.host, port=arguments.port)
        client = PJLinkClient(configuration)
        if arguments.command in ("test", "status"):
            state = client.power_status()
            if arguments.command == "test":
                print(f"PJLink test passed for {configuration.host}:{configuration.port}: TCP, authentication (if required), and power query succeeded. Power: {state.label}")
            else:
                print(state.label)
        else:
            client.set_power(arguments.command == "on")
            print(f"Power {arguments.command} request accepted.")
        return 0
    except (ConfigurationError, PJLinkError) as error:
        print(f"Error: {error}", file=sys.stderr)
        if isinstance(error, ConfigurationError):
            return 2
        if isinstance(error, AuthenticationError):
            return 4
        if isinstance(error, ConnectionError):
            return 3
        return 5
