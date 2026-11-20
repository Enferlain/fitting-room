"""Verify store-backed harnesses without downloading anything in the trial."""

from __future__ import annotations

import shlex

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.agents.installed.codex import Codex
from harbor.agents.installed.opencode_v2 import OpenCodeV2
from harbor.environments.base import BaseEnvironment

from fitting_room.environments.podman import FrPodmanEnvironment
from fitting_room.harness_store import BINARIES, version_command, version_matches


class PinnedInstall:
    async def install(self, environment: BaseEnvironment) -> None:
        if not isinstance(environment, FrPodmanEnvironment):
            # Legacy smoke tasks still use Harbor's Docker path until section 6.
            await super().install(environment)
            return
        name = self.store_harness_name
        path = environment.harness_path
        if path is None or not self._version:
            raise RuntimeError(f"{name}: a pinned harness store mount is required")
        binary = path / "bin" / BINARIES[name]
        diagnostic = shlex.quote(f"{name}: expected {binary} on the trial PATH")
        result = await self.exec_as_agent(
            environment,
            command=(
                f'if [ "$(command -v {BINARIES[name]})" != {shlex.quote(str(binary))} ]; then '
                f"printf '%s\\n' {diagnostic} >&2; exit 1; fi; "
                f"{version_command(name, path)}"
            ),
        )
        if not version_matches(name, self._version, result.stdout or ""):
            raise RuntimeError(f"{name}: expected {self._version}, got {result.stdout!r}")


class FrCodex(PinnedInstall, Codex):
    store_harness_name = "codex"


class FrClaudeCode(PinnedInstall, ClaudeCode):
    store_harness_name = "claude-code"


class FrOpenCode(PinnedInstall, OpenCodeV2):
    store_harness_name = "opencode"
