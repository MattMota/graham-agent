"""Alocação-alvo, enquadramento e rebalanceamento, pelo MCP e pelo cartão de confirmação."""

import uuid

import pytest

from tests.fakes import calls, says
from tests.integration.test_agent_turn import of, run
from tests.integration.test_mcp import connect, key, output

pytestmark = pytest.mark.integration


async def buy(client, ticker, quantity, price):
    output(await client.call_tool("registrar_compra", {
        "ticker_name": ticker, "quantity": quantity, "unit_price": price, "traded_on": "2026-10-01",
    }))


async def test_alvo_que_nao_soma_100_e_recusado(server, user):
    async with connect(server, key(user, can_write=True)) as client:
        result = await client.call_tool("definir_alocacao", {
            "acoes_br": 50, "fundos": 30, "etfs": 10, "exterior": 0, "cripto": 0,
        })

    assert result.is_error
    assert "somam 90%" in result.content[0].text


async def test_chave_de_leitura_nao_define_alvo(server, user):
    async with connect(server, key(user)) as client:
        result = await client.call_tool("definir_alocacao", {
            "acoes_br": 100, "fundos": 0, "etfs": 0, "exterior": 0, "cripto": 0,
        })

    assert result.is_error and "permissão de leitura" in result.content[0].text


async def test_enquadramento_e_rebalanceamento_com_aporte(server, user):
    async with connect(server, key(user, can_write=True)) as client:
        # 60% em ações (PETR4), 20% em fundos (MXRF11), 20% em ETFs (BOVA11), a preço de hoje.
        await buy(client, "PETR4.SA", 1000, 30)
        await buy(client, "MXRF11.SA", 1040, 10)
        await buy(client, "BOVA11.SA", 104, 100)

        before = output(await client.call_tool("ver_enquadramento", {}))
        assert before["has_targets"] is False
        assert [item["weight_percent"] for item in before["classes"][:3]] == [60.0, 20.0, 20.0]

        no_target = await client.call_tool("sugerir_rebalanceamento", {"contribution": 1000})
        assert no_target.is_error and "definir_alocacao" in no_target.content[0].text

        output(await client.call_tool("definir_alocacao", {
            "acoes_br": 50, "fundos": 30, "etfs": 20, "exterior": 0, "cripto": 0, "tolerance": 5,
        }))
        framed = output(await client.call_tool("ver_enquadramento", {}))
        suggestion = output(await client.call_tool("sugerir_rebalanceamento", {"contribution": 5200}))

    status = {item["asset_class"]: item["status"] for item in framed["classes"][:3]}
    assert status == {"acoes_br": "acima", "fundos": "abaixo", "etfs": "dentro"}
    assert framed["in_range"] is False

    # Total de 57.200: faltam 6.760 em fundos e 1.040 em ETFs; o aporte de 5.200
    # se divide nessa proporção (4.506,67 e 693,33), e as ações, acima do alvo,
    # não recebem nada.
    orders = {order["ticker_name"]: (order["side"], order["quantity"]) for order in suggestion["orders"]}
    assert orders == {"MXRF11.SA": ("compra", 450.0), "BOVA11.SA": ("compra", 6.0)}
    assert suggestion["cash_left"] == pytest.approx(100.0)  # 5.200 − 4.500 − 600


def test_cartao_do_alvo_grava_os_pesos_corrigidos(user, model, database):
    proposed = {"acoes_br": 60, "fundos": 40, "etfs": 0, "exterior": 0, "cripto": 0, "tolerance": 5}
    model.script = [calls(("definir_alocacao", proposed)), says("Alocação-alvo gravada.")]
    thread_id = str(uuid.uuid4())

    [interrupt] = run(user, thread_id, text="Quero 60% em ações e 40% em fundos.")[-1]["outcome"]["interrupts"]
    assert interrupt["message"] == "Definir a alocação-alvo"

    edited = {**proposed, "acoes_br": 50, "fundos": 30, "etfs": 20}
    resumed = run(user, thread_id, resume=[{
        "interruptId": interrupt["id"], "status": "resolved", "payload": {"approved": True, "editedArgs": edited},
    }])

    assert of(resumed, "TOOL_CALL_RESULT")[0]["metadata"]["graham"]["status"] == "completed"
    row = database.execute(
        """
        select a.acoes_br, a.fundos, a.etfs, a.tolerance
        from core.allocation_targets a join core.users u on u.id = a.user_id where u.email = %s
        """,
        (user.email,),
    ).fetchone()
    assert tuple(map(float, row)) == (50.0, 30.0, 20.0, 5.0)
