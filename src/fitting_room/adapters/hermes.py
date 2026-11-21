"""Hermes adapter: a thin subclass of Harbor's built-in Hermes agent (design D5, task 4.4).

Harbor's agent already runs a one-shot ``hermes --yolo chat -q`` with a fresh
``HERMES_HOME=/tmp/hermes`` (no host config, memory off), exports the session and converts
it to ATIF with token counts. Differences handled here:

- the store provides a commit-pinned CLI without browser or computer-use dependencies;
- token counts: Harbor sums per-message usage, which local (llama.cpp) runs leave empty;
  the session export's own totals are used when Harbor finds none;
- reasoning effort: Harbor never sets one; GLM must not run with thinking off, so the
  level goes into ``agent.reasoning_effort`` and ``--reasoning``, and ``none`` is refused.
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Literal

import yaml
from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.hermes import Hermes, HermesOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from pydantic import Field

from fitting_room.adapters.pinned import PinnedInstall


class FrHermesOptions(HermesOptions):
    # No "none": thinking off is never allowed for GLM (and pointless to benchmark here).
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh", "max"] = Field(
        description="Hermes reasoning effort (agent.reasoning_effort and --reasoning)."
    )


class FrHermes(PinnedInstall, Hermes):
    store_harness_name = "hermes"

    capabilities = AgentCapabilities(
        base_url=True,
        reasoning_effort=True,
        atif=True,
        resume=True,
        skills=True,
        mcp_servers=True,
    )
    options_model = FrHermesOptions
    options: FrHermesOptions

    @property
    def _reasoning_effort(self) -> str:
        return self.options.reasoning_effort

    def get_version_command(self) -> str | None:
        # This release has no `hermes version` subcommand (Harbor's default).
        return 'export PATH="$HOME/.local/bin:$PATH"; hermes --version'

    def parse_version(self, stdout: str) -> str:
        # "Hermes Agent v0.0.0 (2026.9.24) · upstream 27e38935" -> "2026.9.24"
        m = re.search(r"\((\d{4}\.\d+\.\d+)\)", stdout)
        return m.group(1) if m else stdout.strip().splitlines()[0] if stdout.strip() else ""

    def _build_config_yaml(self, model, max_turns=None, *, connection=None) -> str:  # type: ignore[override]
        config = yaml.safe_load(Hermes._build_config_yaml(model, max_turns, connection=connection))
        config.setdefault("agent", {})["reasoning_effort"] = self._reasoning_effort
        # Keep the local title and skip the auxiliary model call, which disables GLM thinking.
        config.setdefault("auxiliary", {}).setdefault("title_generation", {})[
            "model_upgrade_enabled"
        ] = False
        return yaml.dump(config, default_flow_style=False)

    async def exec_as_agent(self, environment: BaseEnvironment, command: str, **kwargs):
        if "hermes --yolo chat" in command:
            command = command.replace(
                "hermes --yolo chat",
                f"hermes --yolo chat --reasoning {shlex.quote(self._reasoning_effort)}",
            )
        return await super().exec_as_agent(environment, command=command, **kwargs)

    def populate_context_post_run(self, context: AgentContext) -> None:
        super().populate_context_post_run(context)
        if context.n_input_tokens or self._resume:
            return
        path = self.logs_dir / "hermes-session.jsonl"
        try:
            session = json.loads(path.read_text().splitlines()[0])
        except (OSError, IndexError, json.JSONDecodeError):
            return
        if session.get("input_tokens"):
            context.n_input_tokens = int(session["input_tokens"])
            context.n_output_tokens = int(session.get("output_tokens") or 0)
            context.n_cache_tokens = int(session.get("cache_read_tokens") or 0)
