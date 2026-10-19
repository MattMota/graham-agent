"""O servidor MCP de fora: chaves de acesso, permissões e as ferramentas do usuário."""

import json

import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

pytestmark = pytest.mark.integration


def key(user, *, can_write=False) -> str:
    response = user.post("/api/keys", json={"name": "teste", "can_write": can_write})
    assert response.status_code == 201, response.text
    return response.json()["token"]


def connect(server, token):
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    return Client(streamable_http_client(f"{server}/mcp", http_client=http))


def output(result) -> dict:
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


def test_sem_chave_o_mcp_responde_401_com_os_metadados_do_recurso(server):
    response = httpx.post(f"{server}/mcp", json={})

    assert response.status_code == 401
    assert "oauth-protected-resource" in response.headers["www-authenticate"]


async def test_ferramentas_publicadas_com_as_anotacoes(server, user):
    async with connect(server, key(user)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert {"agenda_eventos", "ver_carteira", "registrar_compra"} <= set(tools)
    assert tools["agenda_eventos"].annotations.read_only_hint is True
    assert tools["registrar_compra"].annotations.destructive_hint is True
    # A memória é do Graham e não sai dele.
    assert not any("memoria" in name for name in tools)


async def test_chave_de_leitura_nao_grava(server, user):
    async with connect(server, key(user)) as client:
        result = await client.call_tool("registrar_compra", {
            "ticker_name": "PETR4.SA", "quantity": 10, "unit_price": 30, "traded_on": "2026-10-01",
        })

    assert result.is_error
    assert "permissão de leitura" in result.content[0].text


async def test_compra_com_chave_de_escrita_aparece_na_carteira_e_na_agenda(server, user):
    async with connect(server, key(user, can_write=True)) as client:
        output(await client.call_tool("registrar_compra", {
            "ticker_name": "petr4.sa", "quantity": 10, "unit_price": 30, "traded_on": "2026-10-01",
        }))
        portfolio = output(await client.call_tool("ver_carteira", {}))
        agenda = output(await client.call_tool("agenda_eventos", {}))

    [position] = portfolio["positions"]
    assert (position["ticker_name"], position["quantity"], position["current_price"]) == ("PETR4.SA", 10.0, 31.2)
    assert position["result"] == pytest.approx(12.0)
    [event] = agenda["events"]
    assert (event["ticker_name"], event["type"], event["origin"], event["quantity"]) == (
        "PETR4.SA", "data_ex", ["carteira"], 10.0,
    )


async def test_cada_chave_ve_so_a_carteira_do_proprio_dono(server, user):
    with httpx.Client(base_url=server, timeout=60) as other:
        assert other.post("/api/auth/signup", json={"email": f"outro-{user.email}", "password": "senha-segura-1"}).status_code == 201
        async with connect(server, key(other, can_write=True)) as client:
            output(await client.call_tool("registrar_compra", {
                "ticker_name": "VALE3.SA", "quantity": 1, "unit_price": 60, "traded_on": "2026-10-01",
            }))

    async with connect(server, key(user)) as client:
        portfolio = output(await client.call_tool("ver_carteira", {}))

    assert portfolio["positions"] == []


async def test_venda_maior_que_a_posicao_volta_como_erro_legivel(server, user):
    async with connect(server, key(user, can_write=True)) as client:
        result = await client.call_tool("registrar_venda", {
            "ticker_name": "VALE3.SA", "quantity": 5, "unit_price": 60, "traded_on": "2026-10-01",
        })

    assert result.is_error
    assert "menos que os 5" in result.content[0].text
