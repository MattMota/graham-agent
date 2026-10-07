"""Embeddings pelo gateway do provedor, na API compatível com a da OpenAI."""

import logging
import os

from openai import AsyncOpenAI

from src.agent.config.settings import SETTINGS

logger = logging.getLogger("uvicorn.error")

EMBEDDING_MODEL = SETTINGS["embedding"]["model"]

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=os.getenv("MODEL_PROVIDER_BASE_URL"),
            api_key=os.getenv("MODEL_PROVIDER_API_KEY"),
            timeout=SETTINGS["embedding"]["timeout"],
        )
    return _client


async def embed(texts: list[str]) -> list[list[float]] | None:
    """Um vetor por texto, na mesma ordem, ou `None` se o provedor falhar.

    Sem embedding a memória continua existindo e sendo achada pela busca
    lexical; o backfill da subida do servidor completa o que faltou.
    """
    if not texts:
        return []
    try:
        response = await _get_client().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    except Exception:  # noqa: BLE001 - falhar aqui não pode derrubar o turno
        logger.warning("Embedding indisponível; a memória fica só com a busca lexical", exc_info=True)
        return None
    return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


def to_halfvec(vector: list[float]) -> str:
    """O vetor no formato de texto que o pgvector aceita (`'[1,2,3]'::halfvec`).

    Os valores são inteiros (INT8), então o texto é curto e exato.
    """
    return "[" + ",".join(f"{value:g}" for value in vector) + "]"
