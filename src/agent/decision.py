"""Decisões tipadas com um modelo de decisão (Jev), pelo gateway do provedor.

Um modelo de decisão não escreve texto: recebe um estado e perguntas com tipo
definido e devolve probabilidades calibradas. Serve a escolhas rápidas dentro
do sistema, como julgar se duas memórias tratam da mesma coisa.

Usa o endpoint `POST /v1/evaluate` do AI Gateway da Vercel, com a mesma chave
do modelo de chat; o Jev não fala a API de chat compatível com a OpenAI.
"""

import logging
import os
from typing import Any

import httpx

from src.agent.config.settings import SETTINGS

logger = logging.getLogger("uvicorn.error")

DECISION_MODEL = SETTINGS["decision"]["model"]


def boolean(instructions: str, true: str, false: str) -> dict[str, Any]:
    """Uma pergunta de sim ou não; a resposta é a probabilidade do sim."""
    return {"type": "boolean", "instructions": instructions, "criteria": {"true": true, "false": false}}


async def decide(state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]] | None:
    """As respostas, por chave de pergunta, ou `None` se o serviço falhar.

    Todas as perguntas são avaliadas em paralelo, cada uma isolada das outras,
    contra o mesmo estado, numa única chamada.
    """
    if not questions:
        return {}
    base_url = os.environ["MODEL_PROVIDER_BASE_URL"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=SETTINGS["decision"]["timeout"]) as client:
            response = await client.post(
                f"{base_url}/evaluate",
                headers={"Authorization": f"Bearer {os.environ['MODEL_PROVIDER_API_KEY']}"},
                json={"model": DECISION_MODEL, "state": state, "questions": questions},
            )
            response.raise_for_status()
            return response.json()["answers"]
    except Exception:  # noqa: BLE001 - quem chama decide o que fazer sem a resposta
        logger.warning("Modelo de decisão indisponível", exc_info=True)
        return None
