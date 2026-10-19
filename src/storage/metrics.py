"""Métricas das execuções do agente, em `agent.run_metrics`."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from psycopg_pool import AsyncConnectionPool


@dataclass
class RunMetrics:
    """O que uma execução mediu de si mesma, preenchido enquanto ela acontece."""

    run_id: str
    thread_id: UUID
    user_id: UUID
    model: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    outcome: str = "interrupted"
    duration_ms: int = 0
    first_output_ms: int | None = None
    model_calls: int = 0
    # Nulos quando o provedor não informa o uso.
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls: int = 0
    tool_errors: int = 0

    def add_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        self.input_tokens = (self.input_tokens or 0) + int(usage.get("input_tokens") or 0)
        self.output_tokens = (self.output_tokens or 0) + int(usage.get("output_tokens") or 0)


async def record(pool: AsyncConnectionPool, metrics: RunMetrics) -> None:
    row = asdict(metrics)
    columns = ", ".join(row)
    async with pool.connection() as conn:
        await conn.execute(
            f"INSERT INTO agent.run_metrics ({columns}) VALUES ({', '.join(['%s'] * len(row))})"
            " ON CONFLICT (run_id) DO NOTHING",
            tuple(row.values()),
        )


async def summary(pool: AsyncConnectionPool, user_id: UUID, days: int) -> dict[str, Any]:
    """O resumo das execuções do usuário nos últimos `days` dias."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT
                count(*)                                                        AS runs,
                count(*) FILTER (WHERE outcome = 'completed')                   AS completed,
                count(*) FILTER (WHERE outcome = 'awaiting_approval')           AS awaiting_approval,
                count(*) FILTER (WHERE outcome = 'failed')                      AS failed,
                count(*) FILTER (WHERE outcome = 'interrupted')                 AS interrupted,
                percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ms)       AS duration_p50_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)       AS duration_p95_ms,
                percentile_cont(0.5)  WITHIN GROUP (ORDER BY first_output_ms)   AS first_output_p50_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY first_output_ms)   AS first_output_p95_ms,
                sum(model_calls)                                                AS model_calls,
                sum(input_tokens)                                               AS input_tokens,
                sum(output_tokens)                                              AS output_tokens,
                count(*) FILTER (WHERE input_tokens IS NULL AND model_calls > 0) AS runs_without_usage,
                sum(tool_calls)                                                 AS tool_calls,
                sum(tool_errors)                                                AS tool_errors
            FROM agent.run_metrics
            WHERE user_id = %s AND started_at >= %s
            """,
            (user_id, since),
        )
        totals = await cursor.fetchone()
        cursor = await conn.execute(
            """
            SELECT model, count(*) AS runs, sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens
            FROM agent.run_metrics
            WHERE user_id = %s AND started_at >= %s
            GROUP BY model ORDER BY runs DESC
            """,
            (user_id, since),
        )
        by_model = await cursor.fetchall()
    return {"totals": totals, "by_model": by_model}
