"""Oh My Pi adapter: a thin subclass of Harbor's built-in Pi agent (design D5).

Oh My Pi (``@oh-my-pi/pi-coding-agent``, binary ``omp``) is a Pi fork that keeps Pi's
CLI (``-p --mode json --session-dir --provider --model --thinking``), its config
directory variable (``PI_CODING_AGENT_DIR``) and its session event format, so Harbor's
Pi trajectory and usage parsing is reused unchanged. Differences handled here:

- runtime is Bun (the package declares ``engines.bun``), installed at a pinned version;
- the binary is ``omp``, and it needs ``--approval-mode yolo`` to never wait for approval.
"""

from __future__ import annotations

import shlex

from harbor.agents.installed.pi import Pi
from harbor.environments.base import BaseEnvironment

OMP_PACKAGE = "@oh-my-pi/pi-coding-agent"
BUN_VERSION = "1.3.14"  # minimum declared by the omp package's engines field
_BUN_PATH = 'export PATH="$HOME/.bun/bin:$PATH"; '


class OhMyPi(Pi):
    @staticmethod
    def name() -> str:
        return "omp"

    def get_version_command(self) -> str | None:
        return f"{_BUN_PATH}omp --version"

    def parse_version(self, stdout: str) -> str:
        # `omp --version` prints e.g. "omp/18.12.6"
        return stdout.strip().splitlines()[-1].strip().removeprefix("omp/")

    async def install(self, environment: BaseEnvironment) -> None:
        if self.mcp_servers:
            raise ValueError("MCP servers for Oh My Pi are not wired up yet (toolkits, task 4.6)")
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

    async def exec_as_agent(self, environment: BaseEnvironment, command: str, **kwargs):
        """Rewrite Pi's run command for omp: Bun instead of nvm, `omp` instead of `pi`."""
        command = command.replace(". ~/.nvm/nvm.sh; ", _BUN_PATH)
        command = command.replace(
            "pi --print --mode json ", "omp --print --mode json --approval-mode yolo "
        )
        return await super().exec_as_agent(environment, command=command, **kwargs)
