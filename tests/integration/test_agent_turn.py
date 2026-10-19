"""Um turno do agente pelo AG-UI, de ponta a ponta, com o modelo roteirizado."""

import json
import time
import uuid

import pytest

from tests.fakes import calls, says

pytestmark = pytest.mark.integration


def run(user, thread_id, *, text=None, resume=None) -> list[dict]:
    body = {"threadId": thread_id, "runId": str(uuid.uuid4()), "state": None, "tools": [], "context": [], "messages": []}
    if text is not None:
        body["messages"] = [{"id": str(uuid.uuid4()), "role": "user", "content": text}]
    if resume is not None:
        body["resume"] = resume
    with user.stream("POST", "/api/agent", json=body) as response:
        assert response.status_code == 200, response.read()
        return [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]


def types(events):
    return [event["type"] for event in events]


def of(events, kind):
    return [event for event in events if event["type"] == kind]


def test_consulta_transmite_ferramenta_texto_e_cartoes(user, model):
    model.script = [
        calls(("agenda_eventos", {"tickers": ["VALE3.SA"], "days": 30})),
        says("A VALE3 divulga o resultado em dez dias."),
    ]
    thread_id = str(uuid.uuid4())

    events = run(user, thread_id, text="Quando sai o resultado da Vale?")

    assert types(events)[0] == "RUN_STARTED" and types(events)[-1] == "RUN_FINISHED"
    [start] = of(events, "TOOL_CALL_START")
    assert start["toolCallName"] == "agenda_eventos"
    args = "".join(event["delta"] for event in of(events, "TOOL_CALL_ARGS"))
    assert json.loads(args) == {"tickers": ["VALE3.SA"], "days": 30}
    [result] = of(events, "TOOL_CALL_RESULT")
    assert json.loads(result["content"])["events"][0]["type"] == "resultado"
    assert "".join(event["delta"] for event in of(events, "TEXT_MESSAGE_CONTENT")) == "A VALE3 divulga o resultado em dez dias."
    [cards] = [event for event in of(events, "CUSTOM") if event["name"] == "graham.tickers"]
    assert [card["symbol"] for card in cards["value"]] == ["VALE3.SA"]

    # Reabrir a conversa traz o mesmo caminho, lido do banco.
    with user.stream("POST", "/api/agent/connect", json={"threadId": thread_id}) as response:
        replay = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    [snapshot] = of(replay, "MESSAGES_SNAPSHOT")
    assert [message["role"] for message in snapshot["messages"]] == ["user", "assistant", "tool", "assistant"]


def test_compra_pausa_no_cartao_e_grava_o_valor_corrigido(user, model, database):
    purchase = {"ticker_name": "PETR4.SA", "quantity": 100, "unit_price": 30.0, "traded_on": "2026-10-01"}
    model.script = [calls(("registrar_compra", purchase)), says("Registrei a compra de 100 PETR4.")]
    thread_id = str(uuid.uuid4())

    paused = run(user, thread_id, text="Comprei 100 PETR4 a 30 no dia 1º.")

    outcome = paused[-1]["outcome"]
    assert outcome["type"] == "interrupt"
    [interrupt] = outcome["interrupts"]
    assert interrupt["reason"] == "tool_call"
    assert interrupt["metadata"]["graham"]["locked"] == ["ticker_name"]
    assert _trades(database, user.email) == []

    resumed = run(user, thread_id, resume=[{
        "interruptId": interrupt["id"], "status": "resolved",
        "payload": {"approved": True, "editedArgs": {**purchase, "unit_price": 29.5}},
    }])

    assert types(resumed)[-1] == "RUN_FINISHED"
    [result] = of(resumed, "TOOL_CALL_RESULT")
    assert json.loads(result["content"])["user_edits"] == {"unit_price": {"proposed": 30.0, "approved": 29.5}}
    assert _trades(database, user.email) == [("PETR4.SA", "compra", 100, 29.5)]


def test_compra_cancelada_no_cartao_nao_grava_e_o_modelo_explica(user, model, database):
    purchase = {"ticker_name": "PETR4.SA", "quantity": 5, "unit_price": 30.0, "traded_on": "2026-10-01"}
    model.script = [calls(("registrar_compra", purchase)), says("Tudo bem, não registrei.")]
    thread_id = str(uuid.uuid4())
    [interrupt] = run(user, thread_id, text="Comprei 5 PETR4.")[-1]["outcome"]["interrupts"]

    # O botão Cancelar do cartão: a interrupção é resolvida, com a recusa.
    resumed = run(user, thread_id, resume=[{"interruptId": interrupt["id"], "status": "resolved", "payload": {"approved": False}}])

    assert _trades(database, user.email) == []
    [result] = of(resumed, "TOOL_CALL_RESULT")
    assert result["metadata"]["graham"]["status"] == "cancelled"
    assert "".join(event["delta"] for event in of(resumed, "TEXT_MESSAGE_CONTENT")) == "Tudo bem, não registrei."


def test_confirmacao_abandonada_encerra_sem_rodar_nada(user, model, database):
    purchase = {"ticker_name": "PETR4.SA", "quantity": 5, "unit_price": 30.0, "traded_on": "2026-10-01"}
    model.script = [calls(("registrar_compra", purchase))]
    thread_id = str(uuid.uuid4())
    [interrupt] = run(user, thread_id, text="Comprei 5 PETR4.")[-1]["outcome"]["interrupts"]

    # `cancelled` no AG-UI: o usuário deixou o cartão para lá, e o modelo não é chamado de novo.
    resumed = run(user, thread_id, resume=[{"interruptId": interrupt["id"], "status": "cancelled"}])

    assert types(resumed) == ["RUN_STARTED", "RUN_FINISHED"]
    assert _trades(database, user.email) == []


def test_pergunta_nova_com_confirmacao_pendente_e_recusada(user, model):
    purchase = {"ticker_name": "PETR4.SA", "quantity": 5, "unit_price": 30.0, "traded_on": "2026-10-01"}
    model.script = [calls(("registrar_compra", purchase))]
    thread_id = str(uuid.uuid4())
    run(user, thread_id, text="Comprei 5 PETR4.")

    events = run(user, thread_id, text="Esquece, outra pergunta.")

    assert events[-1]["type"] == "RUN_ERROR" and events[-1]["code"] == "pending_interrupts"


def test_turno_concluido_vira_memoria_conversa_com_embedding(user, model, database):
    model.script = [says("Os juros futuros subiram hoje.")]

    run(user, str(uuid.uuid4()), text="Como foram os juros futuros?")

    # A indexação roda depois da resposta, em segundo plano.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        row = database.execute(
            """
            select m.content, m.embedding is not null
            from agent.memories m join core.users u on u.id = m.user_id
            where u.email = %s and m.category = 'conversa'
            """,
            (user.email,),
        ).fetchone()
        if row and row[1]:
            break
        time.sleep(0.2)
    assert row is not None and row[1], row
    assert "juros futuros" in row[0]


def _trades(database, email):
    rows = database.execute(
        """
        select t.ticker, t.side::text, t.quantity, t.unit_price
        from core.portfolio_trades t join core.users u on u.id = t.user_id
        where u.email = %s order by t.created_at
        """,
        (email,),
    ).fetchall()
    return [(ticker, side, float(quantity), float(price)) for ticker, side, quantity, price in rows]
