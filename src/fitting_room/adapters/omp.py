"""Oh My Pi adapter: a thin subclass of Harbor's built-in Pi agent (design D5).

Oh My Pi (``@oh-my-pi/pi-coding-agent``, binary ``omp``) is a Pi fork that keeps Pi's
CLI (``-p --mode json --session-dir --provider --model --thinking``), its config
directory variable (``PI_CODING_AGENT_DIR``) and its session event format, so Harbor's
Pi trajectory and usage parsing is reused unchanged. Differences handled here:

- runtime is Bun (the package declares ``engines.bun``), installed at a pinned version;
- the binary is ``omp``, and it needs ``--approval-mode yolo`` to never wait for approval;
- MCP: omp reads ``mcp.json`` from its agent dir natively (Pi needs the
  ``pi-mcp-adapter`` extension, which Harbor installs and loads with ``--extension``).
  Harbor already writes ``mcp.json`` into the isolated ``PI_CODING_AGENT_DIR``; this
  adapter writes it in omp's format and drops the adapter's ``--extension`` flag.
"""

from __future__ import annotations

import shlex
from typing import Any

from harbor.agents.installed.pi import _REMOTE_PI_MCP_ADAPTER_EXTENSION, Pi
from harbor.environments.base import BaseEnvironment

from fitting_room.adapters.pinned import PinnedInstall
from fitting_room.environments.podman import FrPodmanEnvironment

OMP_PACKAGE = "@oh-my-pi/pi-coding-agent"
BUN_VERSION = "1.3.14"  # minimum declared by the omp package's engines field
_BUN_PATH = 'export PATH="$HOME/.bun/bin:$PATH"; '


class OhMyPi(PinnedInstall, Pi):
    store_harness_name = "omp"

    @staticmethod
    def name() -> str:
        return "omp"

    def get_version_command(self) -> str | None:
        return f"{_BUN_PATH}omp --version"

    def parse_version(self, stdout: str) -> str:
        # `omp --version` prints e.g. "omp/18.12.6"
        return stdout.strip().splitlines()[-1].strip().removeprefix("omp/")

    async def install(self, environment: BaseEnvironment) -> None:
        if isinstance(environment, FrPodmanEnvironment):
            await super().install(environment)
            return
        await self.ensure_system_dependencies(environment, ("curl", "unzip"))
        version = f"@{self._version}" if self._version else "@latest"
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f"curl -fsSL https://bun.sh/install | bash -s {shlex.quote('bun-v' + BUN_VERSION)}"
                f" >/dev/null && {_BUN_PATH}"
                f"bun add -g {shlex.quote(OMP_PACKAGE + version)} >/dev/null && "
                "omp --version"
            ),
        )

    def _build_mcp_config(self) -> dict[str, Any]:
        """omp's native mcp.json: {"mcpServers": {name: {type, command, args | url}}}."""
        servers: dict[str, dict[str, Any]] = {}
        for server in self.mcp_servers:
            if server.transport == "stdio":
                servers[server.name] = {
                    "type": "stdio",
                    "command": server.command,
                    "args": list(server.args),
                }
            else:
                servers[server.name] = {"type": server.transport, "url": server.url}
        return {"mcpServers": servers}

    async def exec_as_agent(self, environment: BaseEnvironment, command: str, **kwargs):
        """Rewrite Pi's run command for omp: Bun instead of nvm, `omp` instead of `pi`,
        and no Pi MCP adapter extension (omp has MCP built in)."""
        command = command.replace(
            f"--extension {shlex.quote(_REMOTE_PI_MCP_ADAPTER_EXTENSION.as_posix())} ", ""
        )
        command = command.replace(". ~/.nvm/nvm.sh; ", _BUN_PATH)
        command = command.replace(
            "pi --print --mode json ", "omp --print --mode json --approval-mode yolo "
        )
        return await super().exec_as_agent(environment, command=command, **kwargs)
