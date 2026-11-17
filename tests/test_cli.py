from typer.testing import CliRunner

from fitting_room import __version__
from fitting_room.cli import app


def test_version_command_prints_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
