"""Quais tickers viram cartões ao fim da resposta."""

import math

from src.server.runs import _cited, _cited_symbols, _symbols_in
from src.tools.market import _percent_change, _safe


def test_codigo_conta_so_como_palavra_inteira():
    assert _cited("ITUB4", "Comprei ITUB4 ontem.")
    assert not _cited("ITUB4", "O ITUB4F é o fracionário.")
    # A base dentro do código completo conta: é como "PETR4" acha "PETR4.SA".
    assert _cited("PETR4", "Veja PETR4.SA")


def test_citado_pela_base_fica_a_listagem_da_b3_e_nao_a_de_buenos_aires():
    candidates = ["BBAS3.BA", "BBAS3.SA"]

    assert _cited_symbols(candidates, {}, "O BBAS3 subiu hoje.") == ["BBAS3.SA"]


def test_citado_pela_base_prefere_a_listagem_que_o_agente_consultou():
    candidates = ["BBAS3.SA", "BBAS3.BA"]

    assert _cited_symbols(candidates, {"BBAS3.BA": {}}, "O BBAS3 subiu.") == ["BBAS3.BA"]


def test_cartoes_seguem_a_ordem_da_resposta_e_ignoram_os_nao_citados():
    candidates = ["VALE3.SA", "PETR4.SA", "ITUB4.SA"]
    answer = "A PETR4.SA caiu e a VALE3 subiu."

    assert _cited_symbols(candidates, {}, answer) == ["PETR4.SA", "VALE3.SA"]


def test_tickers_saem_dos_retornos_das_ferramentas():
    payload = {
        "ticker_name": "PETR4.SA",
        "positions": [{"ticker_name": "VALE3.SA"}],
        "entries": [{"ticker_name": "AAPL"}],
        "events": [{"ticker_name": "MSFT", "type": "data_ex"}],
    }

    assert _symbols_in(payload) == ["PETR4.SA", "VALE3.SA", "AAPL", "MSFT"]
    assert _symbols_in("texto que não é JSON") == []


def test_nan_da_yahoo_vira_ausencia_de_dado():
    assert _safe(lambda: math.nan) is None
    assert _safe(lambda: 1 / 0) is None
    assert _safe(lambda: 12.5) == 12.5


def test_variacao_sem_fechamento_anterior_fica_vazia():
    assert _percent_change(11.0, 10.0) == (1.0, 10.0)
    assert _percent_change(11.0, None) == (None, None)
