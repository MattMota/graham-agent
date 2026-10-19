"""Métricas por execução: gravadas no fim de cada uma e resumidas em /api/metrics."""

import time
import uuid

import httpx
import pytest

from tests.fakes import calls, says, with_usage
from tests.integration.test_agent_turn import run

pytestmark = pytest.mark.integration


def rows(database, email):
    # A gravação acontece no fim da execução, logo depois do último evento.
    for _ in range(50):
        found = database.execute(
            """
            select m.outcome, m.model_calls, m.input_tokens, m.output_tokens, m.tool_calls, m.tool_errors,
                   m.duration_ms, m.first_output_ms
            from agent.run_metrics m join core.users u on u.id = m.user_id
            where u.email = %s order by m.started_at
            """,
            (email,),
        ).fetchall()
        if found:
            return found
        time.sleep(0.1)
    return []


def test_execucao_grava_tokens_ferramentas_e_tempos(user, model, database):
    model.script = [
        with_usage(calls(("agenda_eventos", {"tickers": ["VALE3.SA"]})), 1200, 40),
        with_usage(says("A Vale divulga o resultado em dez dias."), 1500, 25),
    ]

    run(user, str(uuid.uuid4()), text="Quando sai o resultado da Vale?")

    [(outcome, model_calls, input_tokens, output_tokens, tool_calls, tool_errors, duration, first)] = rows(database, user.email)
    assert (outcome, model_calls, input_tokens, output_tokens) == ("completed", 2, 2700, 65)
    assert (tool_calls, tool_errors) == (1, 0)
    assert duration > 0 and first is not None and first <= duration


def test_erro_de_ferramenta_e_contado(user, model, database):
    model.script = [calls(("agenda_eventos", {"tickers": ["XXXX9.SA"]})), says("Não encontrei esse ativo.")]

    run(user, str(uuid.uuid4()), text="Agenda do XXXX9?")

    [row] = rows(database, user.email)
    assert row[4:6] == (1, 1)


def test_pausa_e_retomada_sao_execucoes_separadas(user, model, database):
    purchase = {"ticker_name": "PETR4.SA", "quantity": 1, "unit_price": 30.0, "traded_on": "2026-10-01"}
    model.script = [calls(("registrar_compra", purchase)), says("Registrado.")]
    thread_id = str(uuid.uuid4())
    [interrupt] = run(user, thread_id, text="Comprei 1 PETR4.")[-1]["outcome"]["interrupts"]
    run(user, thread_id, resume=[{"interruptId": interrupt["id"], "status": "resolved", "payload": {"approved": True}}])

    for _ in range(50):
        outcomes = [row[0] for row in rows(database, user.email)]
        if len(outcomes) == 2:
            break
        time.sleep(0.1)
    assert outcomes == ["awaiting_approval", "completed"]


def test_resumo_agrega_so_as_execucoes_do_usuario(server, user, model):
    model.script = [with_usage(says("Olá."), 100, 10), with_usage(says("Oi de novo."), 300, 30)]
    run(user, str(uuid.uuid4()), text="Oi")
    run(user, str(uuid.uuid4()), text="Oi de novo")
    time.sleep(0.5)

    summary = user.get("/api/metrics", params={"days": 7}).json()

    assert summary["runs"] == 2 and summary["outcomes"]["completed"] == 2
    assert (summary["model"]["input_tokens"], summary["model"]["output_tokens"]) == (400, 40)
    assert summary["model"]["tokens_per_run"] == 220
    assert summary["latency_ms"]["duration_p50"] is not None
    assert summary["tools"]["error_rate"] is None  # nenhuma ferramenta chamada

    with httpx.Client(base_url=server, timeout=60) as other:
        other.post("/api/auth/signup", json={"email": f"outra-{user.email}", "password": "senha-segura-1"})
        assert other.get("/api/metrics").json()["runs"] == 0
    assert httpx.get(f"{server}/api/metrics").status_code == 401
