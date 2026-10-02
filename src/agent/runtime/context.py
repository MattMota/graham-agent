"""Contexto de uma execução do grafo: o que as ferramentas precisam e o modelo não vê."""

from dataclasses import dataclass
from uuid import UUID

from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class AgentContext:
    """Passado a cada execução pelo servidor. Não entra nos checkpoints.

    O REPL roda sem contexto; as ferramentas que dependem dele avisam que só
    funcionam na interface web.
    """

    user_id: UUID
    pool: AsyncConnectionPool
