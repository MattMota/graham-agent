"""O Graham inteiro de pé, contra um Postgres e um Redis de teste.

Precisa de `TEST_DATABASE_URL` (um banco cujo nome termina em `_test`, recriado
a cada sessão) e `TEST_REDIS_URL` (um banco do Redis diferente do 0, esvaziado
no começo e no fim). Sem as duas, os testes desta pasta são pulados.

O servidor roda numa thread deste processo, então as fontes externas são
trocadas por versões fixas: o modelo segue um roteiro, a cotação, a classe e as datas
de eventos vêm de tabelas, e os embeddings são vetores fixos. A Yahoo e o
provedor do modelo nunca são chamados.
"""

import asyncio
import os
import socket
import sys
import threading
import time
from datetime import date, timedelta
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
import pytest
import redis

from tests.fakes import ScriptedModel

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REDIS_URL = os.getenv("TEST_REDIS_URL")

pytestmark = pytest.mark.integration


def pytest_collection_modifyitems(config, items):
    if DATABASE_URL and REDIS_URL:
        return
    skip = pytest.mark.skip(reason="defina TEST_DATABASE_URL e TEST_REDIS_URL para os testes de integração")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def _recreate_database(url: str) -> None:
    name = urlsplit(url).path.lstrip("/")
    # Uma trava contra apontar os testes para o banco de uso.
    assert name.endswith("_test"), f"O banco dos testes precisa terminar em _test, não '{name}'."
    admin = urlunsplit(urlsplit(url)._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')


def _clean_redis(url: str) -> None:
    client = redis.Redis.from_url(url)
    assert client.connection_pool.connection_kwargs.get("db", 0) != 0, "O Redis dos testes não pode ser o banco 0."
    client.flushdb()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


TODAY = date.today()

QUOTES = {
    "PETR4.SA": {"company_name": "Petrobras", "currency": "BRL", "price": 31.2},
    "VALE3.SA": {"company_name": "Vale", "currency": "BRL", "price": 60.5},
    "MXRF11.SA": {"company_name": "Maxi Renda Fundo De Investimento Imobiliaro - FII", "currency": "BRL", "price": 10.0},
    "BOVA11.SA": {"company_name": "ISHARES IBOVESPA CLASSE DE ÍNDICE", "currency": "BRL", "price": 100.0},
}

EVENTS = {
    "VALE3.SA": {"earnings_from": (TODAY + timedelta(days=10)).isoformat()},
    "PETR4.SA": {"ex_date": (TODAY + timedelta(days=20)).isoformat()},
}


def fake_quote(ticker_name: str) -> dict:
    if ticker_name not in QUOTES:
        raise ValueError(f"Nenhum dado encontrado para o ticker '{ticker_name}'.")
    quote = QUOTES[ticker_name]
    return {
        "ticker_name": ticker_name, **quote, "change": 0.1, "change_percent": 0.3,
        "quoted_at": "2026-10-19T20:00:00Z",
    }


async def fake_embed(texts: list[str]) -> list[list[float]]:
    # Vetores INT8 de 1.024 dimensões, como os do modelo de verdade, sem o provedor.
    return [[float((len(text) + index) % 7 - 3) for index in range(1024)] for text in texts]


def fake_asset_info(ticker: str) -> dict:
    quote = QUOTES.get(ticker)
    return {"quote_type": "EQUITY" if quote else None, "name": quote and quote["company_name"]}


def fake_events(ticker: str) -> dict:
    return {
        "found": ticker in QUOTES, "ex_date": None, "payment_date": None,
        "earnings_from": None, "earnings_to": None, "earnings_estimated": False,
        **EVENTS.get(ticker, {}),
    }


@pytest.fixture(scope="session")
def model() -> ScriptedModel:
    return ScriptedModel()


@pytest.fixture(scope="session")
def server(model):
    _recreate_database(DATABASE_URL)
    _clean_redis(REDIS_URL)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    os.environ.update({
        "DATABASE_URL": DATABASE_URL,
        "REDIS_URL": REDIS_URL,
        "PUBLIC_URL": base,
        "MCP_INTERNAL_URL": f"{base}/mcp",
    })

    from db import migrate

    migrate.main()

    import uvicorn

    from src.agent.memory import processing
    from src.agent.runtime import state_graph
    from src.tools import allocation, analysis, market

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(state_graph, "bind_model", lambda tools: model)
        patch.setattr(market, "get_current_stock_price", fake_quote)
        patch.setattr(analysis, "_events", fake_events)
        patch.setattr(processing, "embed", fake_embed)
        patch.setattr(allocation, "_asset_info", fake_asset_info)

        from src.server.app import app

        uvicorn_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
        thread = threading.Thread(
            target=lambda: asyncio.run(uvicorn_server.serve(), loop_factory=loop_factory), daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 60
        while not uvicorn_server.started:
            assert thread.is_alive(), "O servidor de teste não subiu; veja o log acima."
            assert time.monotonic() < deadline, "O servidor de teste não subiu em 60 s."
            time.sleep(0.1)

        yield base

        uvicorn_server.should_exit = True
        thread.join(timeout=30)
    _clean_redis(REDIS_URL)


@pytest.fixture
def database():
    """Conexão direta com o banco de teste, para conferir o que foi gravado."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        yield conn


_accounts = iter(range(10_000))


@pytest.fixture
def user(server):
    """Um cliente HTTP já autenticado, com uma conta nova a cada teste."""
    with httpx.Client(base_url=server, timeout=60) as client:
        email = f"teste{next(_accounts)}-{int(time.time() * 1000)}@teste.com"
        response = client.post("/api/auth/signup", json={"email": email, "password": "senha-segura-1"})
        assert response.status_code == 201, response.text
        client.email = email
        yield client
