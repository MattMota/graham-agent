"""O resumo das execuções do agente: latência, tokens, custo estimado e falhas.

Cada execução grava as próprias medidas em `agent.run_metrics` (ver `runs.py`);
aqui elas são agregadas por usuário, num período.
"""

from typing import Any

from fastapi import APIRouter, Query, Request

from src.agent.config.settings import SETTINGS
from src.server.auth import require_user
from src.storage import metrics

router = APIRouter(prefix="/api/metrics")


def _int(value: Any) -> int | None:
    return None if value is None else round(float(value))


def _cost(input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Custo estimado em dólares, se os preços do modelo estiverem no settings.toml."""
    prices = SETTINGS["llm"]
    if input_tokens is None or "usd_per_million_input" not in prices:
        return None
    return round(
        (input_tokens * prices["usd_per_million_input"] + (output_tokens or 0) * prices["usd_per_million_output"])
        / 1_000_000,
        4,
    )


@router.get("")
async def summary(request: Request, days: int = Query(default=7, ge=1, le=365)) -> dict[str, Any]:
    data = await metrics.summary(request.app.state.pool, await require_user(request), days)
    totals = data["totals"]
    runs = totals["runs"] or 0
    tool_calls = int(totals["tool_calls"] or 0)
    input_tokens = _int(totals["input_tokens"])
    output_tokens = _int(totals["output_tokens"])
    return {
        "days": days,
        "runs": runs,
        "outcomes": {
            name: totals[name] for name in ("completed", "awaiting_approval", "failed", "interrupted")
        },
        "latency_ms": {
            "duration_p50": _int(totals["duration_p50_ms"]),
            "duration_p95": _int(totals["duration_p95_ms"]),
            "first_output_p50": _int(totals["first_output_p50_ms"]),
            "first_output_p95": _int(totals["first_output_p95_ms"]),
        },
        "model": {
            "calls": int(totals["model_calls"] or 0),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tokens_per_run": round((input_tokens + output_tokens) / runs) if runs and input_tokens is not None else None,
            # Execuções em que o provedor não informou o uso: os tokens ficam abaixo do real.
            "runs_without_usage": totals["runs_without_usage"],
            "estimated_cost_usd": _cost(input_tokens, output_tokens),
            "by_model": [
                {**row, "input_tokens": _int(row["input_tokens"]), "output_tokens": _int(row["output_tokens"])}
                for row in data["by_model"]
            ],
        },
        "tools": {
            "calls": tool_calls,
            "errors": int(totals["tool_errors"] or 0),
            "error_rate": round(int(totals["tool_errors"] or 0) / tool_calls, 4) if tool_calls else None,
        },
    }
