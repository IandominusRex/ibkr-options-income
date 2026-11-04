"""The value book's analyst: one ``claude -p`` read per request (spec §8.1, §8.5).

Never raises: a CLI failure, an unreadable reply or a crashing context source comes back as an
``AnalystResult`` with no reply and the error named. With ``value.claude.ollama_fallback`` on, a
failed CLI call (anything but a timeout) is answered by the local Ollama model instead; that
reply is labelled ``backend="ollama"`` and ``src/value/`` never lets it decide anything (spec
§8.5, the ``claude_cut`` rule). When ``claude.backend`` is ``ollama`` every read is Ollama's.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from src.claude.cli import CliResult, OllamaSettings, run_claude, run_ollama, should_fall_back
from src.common.config import Config
from src.common.value_ai_types import AnalystCall, AnalystRequest, AnalystResult
from src.value_ai.context import AnalystContext, gather
from src.value_ai.parse import parse_reply
from src.value_ai.prompts import OUTPUT_SCHEMA, PROMPT_VERSION, build_prompt

log = logging.getLogger(__name__)

Runner = Callable[..., Awaitable[CliResult]]
Gatherer = Callable[[str, datetime, int], AnalystContext]


class Analyst:
    def __init__(
        self,
        *,
        cli_command: str,
        disallowed_tools: str,
        workdir: Path,
        slim: bool = True,
        max_headlines: int = 12,
        ollama: OllamaSettings | None = None,
        ollama_only: bool = False,
        run: Runner = run_claude,
        ollama_run: Runner = run_ollama,
        context: Gatherer = gather,
    ) -> None:
        self.cli_command = cli_command
        self.disallowed_tools = disallowed_tools
        self.workdir = workdir
        self.slim = slim
        self.max_headlines = max_headlines
        self.ollama = ollama
        self.ollama_only = ollama_only and ollama is not None
        self._run = run
        self._ollama_run = ollama_run
        self._context = context

    @classmethod
    def from_config(cls, cfg: Config) -> Analyst:
        c, v = cfg.claude, cfg.value.claude
        only = c.backend == "ollama"
        ollama = (
            OllamaSettings(
                c.ollama_host,
                c.ollama_model,
                c.ollama_keep_alive,
                c.ollama_temperature,
                c.ollama_num_ctx,
            )
            if v.ollama_fallback or only
            else None
        )
        return cls(
            cli_command=c.cli_command,
            disallowed_tools=c.disallowed_tools,
            workdir=cfg.value_ai_workdir(),
            slim=c.slim_context,
            max_headlines=v.max_headlines,
            ollama=ollama,
            ollama_only=only,
        )

    async def read(self, req: AnalystRequest, now: datetime) -> AnalystResult:
        prompt = ""
        try:
            ctx = await asyncio.to_thread(self._context, req.symbol, now, self.max_headlines)
            prompt = build_prompt(req, ctx)
            if self.ollama_only:
                res = CliResult(None, "disabled", 0)
            else:
                res = await self._run(
                    prompt,
                    cli_command=self.cli_command,
                    model=req.model,
                    effort=req.effort,
                    timeout_seconds=req.timeout_seconds,
                    cwd=self.workdir,
                    disallowed_tools=self.disallowed_tools,
                    slim=self.slim,
                    usage_kind=f"value_{req.kind}",
                )
            backend, model = "cli", req.model
            if self.ollama is not None and (self.ollama_only or should_fall_back(res.error)):
                log.warning("value_ai: %s answered by ollama (%s)", req.symbol, res.error)
                alt = await self._ollama_run(
                    prompt,
                    settings=self.ollama,
                    schema=OUTPUT_SCHEMA,
                    timeout_seconds=req.timeout_seconds,
                )
                res = CliResult(
                    alt.text, alt.error, res.latency_ms + alt.latency_ms, res.cost_usd, alt.raw
                )
                backend, model = "ollama", f"ollama:{self.ollama.model}"
            reply = parse_reply(res.text, req) if res.text is not None else None
            error = res.error or (None if reply is not None else "unparseable")
            return AnalystResult(
                read_id=req.read_id,
                reply=reply,
                call=AnalystCall(
                    model=model,
                    backend=backend,  # type: ignore[arg-type]  # "cli" | "ollama"
                    latency_ms=res.latency_ms,
                    cost_usd=res.cost_usd,
                    error=error,
                    prompt_version=PROMPT_VERSION,
                    prompt=prompt,
                    raw=(res.text if res.text is not None else res.raw)[:20000],
                ),
            )
        except Exception:  # noqa: BLE001 - the analyst never takes the value process down
            log.exception("value_ai: read of %s failed", req.symbol)
            return AnalystResult(
                read_id=req.read_id,
                call=AnalystCall(
                    model=req.model,
                    error="analyst_error",
                    prompt_version=PROMPT_VERSION,
                    prompt=prompt,
                ),
            )
