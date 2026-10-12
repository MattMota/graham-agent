"""O que as ferramentas recebem de quem as chama: o usuário e o banco."""

from dataclasses import dataclass
from uuid import UUID

from psycopg_pool import AsyncConnectionPool


class ToolFailure(Exception):
    """Falha prevista, com uma mensagem para o agente ler e corrigir o pedido
    (um ticker que não existe, uma venda maior que a posição)."""


@dataclass(frozen=True)
class ToolContext:
    """Montado pelo servidor MCP a partir do token de acesso.

    Sem usuário (uma chamada em processo, sem token), as ferramentas de mercado
    funcionam e as de carteira avisam que precisam de uma conta.
    """

    pool: AsyncConnectionPool | None = None
    user_id: UUID | None = None

    @property
    def has_user(self) -> bool:
        return self.pool is not None and self.user_id is not None

    def require_user(self) -> tuple[AsyncConnectionPool, UUID]:
        if not self.has_user:
            raise ToolFailure("A carteira e a watchlist precisam de um usuário autenticado.")
        return self.pool, self.user_id
