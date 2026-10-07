"""Trabalho de memória que não precisa travar a resposta: embeddings, a checagem
de substituição, a indexação dos turnos e o backfill da subida do servidor."""

import asyncio
import logging
from collections.abc import Awaitable
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from src.agent import decision
from src.agent.config.settings import SETTINGS
from src.agent.memory.embeddings import EMBEDDING_MODEL, embed, to_halfvec
from src.storage import conversations, memories

logger = logging.getLogger("uvicorn.error")

# Tarefas em andamento, guardadas até terminarem (sem referência, o asyncio
# pode descartá-las no meio).
_tasks: set[asyncio.Task] = set()


def spawn(work: Awaitable[None]) -> None:
    """Roda em segundo plano; uma falha vira log, nunca derruba o turno."""

    async def guarded() -> None:
        try:
            await work
        except Exception:  # noqa: BLE001
            logger.exception("Falha no processamento de memória")

    task = asyncio.create_task(guarded())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain(timeout: float | None = None) -> None:
    """Espera o que estiver em andamento (no fim dos testes e ao desligar).

    Com `timeout`, desiste depois dele: ao desligar, o que ficar para trás é um
    embedding, que o backfill da próxima subida completa.
    """
    if _tasks:
        await asyncio.wait(list(_tasks), timeout=timeout)


# Substituição ───────────────────────────────────────────────────────────────
#
# O embedding só ordena: as memórias de fato mais parecidas com a nova vão,
# juntas, a um modelo de decisão (Jev), que responde para cada uma se a nova a
# torna dispensável. Um limiar de cosseno não serviria para decidir: na
# calibração (2026-10-06), "conservador → arrojado" ficou em 0,61 e "bancos x
# energia", em 0,60. O Jev deu 0,72–0,94 aos pares que tratam da mesma coisa e
# 0,03–0,08 aos de assuntos diferentes.
#
# A pergunta é "dispensável", e não "mesmo assunto", por causa dos fatos
# compostos: "conservador, aposentadoria em 25 anos" → "arrojado" é o mesmo
# assunto, mas substituir apagaria o horizonte (0,26 com a pergunta estrita,
# acima de 0,5 com a ampla). Os casos de fronteira ficam perto de 0,5; por isso
# o agente também é instruído a guardar um fato por memória.

DISPENSABLE = (
    "A memória nova torna a memória existente {key} dispensável? Sim quando a nova diz a mesma "
    "coisa de outra forma, ou atualiza o mesmo assunto, e não sobra na existente nenhuma "
    "informação que continue valendo. Não quando tratam de assuntos diferentes, mesmo parecidos, "
    "ou quando a existente traz outra informação que a nova não cobre."
)


async def superseded_by(new: str, candidates: list[dict]) -> list[UUID]:
    """As candidatas que a memória nova torna dispensáveis.

    Uma pergunta por candidata, avaliadas em paralelo e isoladas umas das outras
    contra o mesmo estado, numa única chamada. Sem resposta do modelo, nada é
    substituído: melhor uma duplicata do que um fato apagado por engano.
    """
    keys = {f"m{index}": candidate for index, candidate in enumerate(candidates, start=1)}
    answers = await decision.decide(
        {"memoria_nova": new, "memorias_existentes": {key: c["content"] for key, c in keys.items()}},
        {
            key: decision.boolean(
                DISPENSABLE.format(key=key),
                true="tudo o que a existente diz está repetido ou desatualizado pela nova",
                false="assunto diferente, ou a existente ainda traz alguma informação que vale",
            )
            for key in keys
        },
    )
    threshold = SETTINGS["memory"]["supersede_probability"]
    return [
        keys[key]["id"]
        for key, answer in (answers or {}).items()
        if key in keys and answer.get("probability", 0) >= threshold
    ]


# Processamento de uma memória ───────────────────────────────────────────────


async def process_memory(
    pool: AsyncConnectionPool, user_id: UUID, memory_id: UUID, category: str, content: str
) -> None:
    """Calcula o embedding e, para fatos sobre o usuário, aposenta as memórias que
    a nova substitui."""
    vectors = await embed([content])
    if not vectors:
        return  # o backfill tenta de novo na próxima subida
    vector = to_halfvec(vectors[0])
    await memories.set_embedding(pool, memory_id, vector, EMBEDDING_MODEL)

    if category == "conversa":
        return  # turnos são substituídos pela regeneração, não por semelhança
    candidates = await memories.similar(
        pool, user_id, vector, memory_id, SETTINGS["memory"]["supersede_candidates"]
    )
    for old_id in await superseded_by(content, candidates):
        await memories.supersede(pool, old_id, memory_id)


async def backfill(pool: AsyncConnectionPool) -> None:
    """Completa os embeddings que ficaram para trás (o servidor caiu, o provedor falhou)."""
    pending = await memories.pending_embeddings(pool)
    if not pending:
        return
    vectors = await embed([row["content"] for row in pending])
    if not vectors:
        return
    for row, vector in zip(pending, vectors):
        await memories.set_embedding(pool, row["id"], to_halfvec(vector), EMBEDDING_MODEL)
    logger.info("%d memória(s) sem embedding completada(s)", len(pending))


# Turnos de conversa ─────────────────────────────────────────────────────────

# Ferramentas que não entram na linha de consultas de um turno indexado: buscar
# na memória não diz nada sobre o assunto da conversa.
_UNINDEXED_TOOLS = {"guardar_memoria", "buscar_memorias", "ver_memoria", "esquecer_memoria"}


def _call_summary(call: dict) -> str:
    values = [str(value) for value in (call.get("args") or {}).values() if value not in (None, "", [])]
    return f"{call['name']}({', '.join(values)})"


async def index_turn(pool: AsyncConnectionPool, user_id: UUID, title: str | None, final_id: UUID) -> None:
    """Guarda um turno concluído como memória `conversa`, para ser reencontrado.

    O texto leva o título da conversa (contexto para perguntas soltas como "e a
    Petrobras?"), a pergunta, as consultas feitas (os tickers ficam buscáveis) e
    a resposta final, sem os JSONs das ferramentas. As origens são a pergunta e
    a resposta. Se a pergunta já tinha uma resposta indexada, ela foi regerada:
    a memória antiga passa a apontar para a nova.
    """
    path = await conversations.message_path(pool, final_id)
    start = max((index for index, row in enumerate(path) if row["role"] == "user"), default=None)
    if start is None:
        return
    turn = path[start:]
    question, final = turn[0], turn[-1]
    if final["role"] != "assistant" or final["state"] != "completed" or not final["content"]:
        return

    calls = [
        _call_summary(call)
        for row in turn
        if row["role"] == "assistant"
        for call in (row["payload"] or {}).get("tool_calls") or []
        if call["name"] not in _UNINDEXED_TOOLS
    ]
    lines = [title] if title else []
    lines.append(f"Pergunta: {question['content']}")
    if calls:
        lines.append(f"Consultas: {'; '.join(calls)}")
    lines.append(f"Resposta: {final['content']}")
    content = "\n".join(lines)

    row = await memories.add_memory(pool, user_id, "conversa", content)
    await memories.add_sources(pool, row["id"], [question["id"], final["id"]])
    for older in await memories.turn_versions(pool, user_id, question["id"], row["id"]):
        await memories.supersede(pool, older["id"], row["id"])
    await process_memory(pool, user_id, row["id"], "conversa", content)


def profile_limit() -> int:
    return SETTINGS["memory"]["profile_limit"]
