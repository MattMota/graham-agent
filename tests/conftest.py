"""Isola os testes do `.env` de uso.

Roda antes de qualquer import de `src`: o `load_dotenv()` das configurações não
sobrescreve variáveis que já existem, então o que fica definido aqui vale mais
do que o `.env`. Sem isso, os testes gravariam no cache de uso, mandariam
traces para a LangSmith e chamariam o modelo de verdade.
"""

import asyncio
import os
import sys

os.environ.update({
    # Vazia, o cache de mercado fica desligado (`cache._sync`).
    "REDIS_URL": "",
    # Vazia, um teste que abra o banco sem querer falha em vez de tocar o de uso.
    "DATABASE_URL": "",
    "LANGSMITH_TRACING": "false",
    # Uma porta onde nada responde: uma chamada esquecida ao provedor falha na hora.
    "MODEL_PROVIDER_BASE_URL": "http://127.0.0.1:9/v1",
    "MODEL_PROVIDER_API_KEY": "teste",
})


def pytest_asyncio_loop_factories(config, item):
    # O psycopg assíncrono não roda no ProactorEventLoop, o padrão do Windows.
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}
