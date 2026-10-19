"""Executa o agente e traduz o que o grafo faz em eventos AG-UI.

Serve tanto ao começo de um turno quanto à retomada depois da confirmação: nos
dois casos a execução pode terminar, falhar ou pausar de novo. Os eventos vão
para o stream retomável (`streams.produce`), nunca direto para a conexão.
"""

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import anyio
from ag_ui.core import (
    PROTOCOL_VERSION,
    BaseEvent,
    CustomEvent,
    ReasoningEndEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from fastapi import FastAPI
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agent.memory import processing as memory_processing
from src.agent.runtime.context import AgentContext
from src.agent.tools import remote as mcp_tools
from src.agent.tools.registry import APPROVAL_REQUIRED
from src.server.agui import extras, interrupts
from src.server.recorder import TurnRecorder
from src.storage import memories
from src.tools import market

# Quantos cartões de ticker podem ser enviados ao final de uma resposta.
MAX_TICKER_CARDS = 8


def _now_ms() -> int:
    return round(time.time() * 1000)


# Cartões de ticker ──────────────────────────────────────────────────────────


def _tool_payload(content: str) -> Any:
    """O dado que a ferramenta devolveu, se o texto for JSON."""
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None


def _ticker_card(quote: dict[str, Any]) -> dict[str, Any]:
    """Reduz uma cotação completa aos campos que o cartão mostra."""
    return {
        "symbol": quote.get("ticker_name"),
        "name": quote.get("company_name"),
        "currency": quote.get("currency"),
        "price": quote.get("price"),
        "change": quote.get("change"),
        "change_percent": quote.get("change_percent"),
        "quoted_at": quote.get("quoted_at"),
    }


def _symbols_in(payload: Any) -> list[str]:
    """Colhe os tickers que aparecem no retorno de qualquer ferramenta."""
    if not isinstance(payload, dict):
        return []

    symbols = []
    if payload.get("ticker_name"):
        symbols.append(payload["ticker_name"])
    for key in ("matches", "companies", "positions", "entries", "events", "assets", "orders"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and item.get("ticker_name"):
                symbols.append(item["ticker_name"])
    return symbols


def _cited(code: str, text: str) -> bool:
    """O código aparece no texto como palavra inteira ('ITUB4' não vale dentro de 'ITUB4F')."""
    return re.search(rf"(?<![\w.]){re.escape(code)}(?![\w])", text) is not None


def _cited_symbols(candidates: list[str], quotes: dict[str, Any], answer: str) -> list[str]:
    """Os tickers que o agente citou, na ordem em que aparecem na resposta.

    O ticker por extenso ('BBAS3.SA') sempre conta. Citado só pela base
    ('BBAS3'), vale uma listagem dela: a busca por empresa devolve também as de
    outras bolsas (BBAS3.BA, em Buenos Aires, cotada em peso), e o cartão seria
    de um ativo de que o agente não falou. Fica a que o agente consultou, senão a
    da B3, senão a primeira da busca.
    """
    unique = list(dict.fromkeys(candidates))
    wanted = [symbol for symbol in unique if _cited(symbol, answer)]
    by_base: dict[str, list[str]] = {}
    for symbol in unique:
        by_base.setdefault(symbol.split(".")[0], []).append(symbol)
    for base, listings in by_base.items():
        if any(symbol in wanted for symbol in listings) or not _cited(base, answer):
            continue
        wanted.append(min(
            listings,
            key=lambda symbol: (symbol not in quotes, not symbol.endswith(".SA"), listings.index(symbol)),
        ))
    return sorted(wanted, key=lambda symbol: answer.find(symbol.split(".")[0]))


async def _ticker_cards(
    quotes: dict[str, dict[str, Any]], candidates: list[str], answer: str
) -> list[dict[str, Any]]:
    """Monta os cartões dos tickers citados, buscando só o que ainda falta."""
    wanted = _cited_symbols(candidates, quotes, answer)[:MAX_TICKER_CARDS]

    missing = [symbol for symbol in wanted if symbol not in quotes]
    if missing:
        # A ferramenta é síncrona; as consultas que faltam acontecem em
        # paralelo e fora do event loop.
        fetched = await asyncio.gather(
            *(asyncio.to_thread(market.get_current_stock_price, symbol) for symbol in missing),
            return_exceptions=True,
        )
        for symbol, result in zip(missing, fetched):
            if isinstance(result, dict):
                quotes[symbol] = result

    return [_ticker_card(quotes[symbol]) for symbol in wanted if symbol in quotes]


# Execução ───────────────────────────────────────────────────────────────────


class _Stream:
    """O que está aberto no stream da chamada ao modelo em curso.

    O AG-UI delimita cada mensagem e cada tool call com um início e um fim. O
    texto e as chamadas saem um de cada vez: começar um fecha o anterior, o
    que todo cliente aceita.
    """

    def __init__(self) -> None:
        self.text: str | None = None
        self.call: str | None = None
        # Do índice do fragmento à tool call, e os argumentos que chegaram antes
        # de o provedor dizer o id e o nome dela.
        self.calls: dict[Any, str] = {}
        self.early_args: dict[Any, str] = {}
        self.started: set[str] = set()

    def close_text(self) -> list[BaseEvent]:
        if self.text is None:
            return []
        event = TextMessageEndEvent(message_id=self.text)
        self.text = None
        return [event]

    def close_call(self) -> list[BaseEvent]:
        if self.call is None:
            return []
        event = ToolCallEndEvent(tool_call_id=self.call)
        self.call = None
        return [event]

    def say(self, message_id: str, delta: str) -> list[BaseEvent]:
        events: list[BaseEvent] = []
        if self.text is None:
            events += self.close_call()
            self.text = message_id
            events.append(TextMessageStartEvent(message_id=message_id, role="assistant"))
        events.append(TextMessageContentEvent(message_id=message_id, delta=delta))
        return events

    def call_chunk(self, chunk: dict[str, Any], parent_id: str) -> list[BaseEvent]:
        """Um fragmento de tool call: abre a chamada no primeiro e transmite os argumentos."""
        key = chunk.get("index") if chunk.get("index") is not None else chunk.get("id")
        args = chunk.get("args") or ""
        call_id = self.calls.get(key)
        events: list[BaseEvent] = []

        if call_id is None:
            if not chunk.get("id") or not chunk.get("name"):
                self.early_args[key] = self.early_args.get(key, "") + args
                return []
            call_id = self.calls[key] = chunk["id"]
            events += self.close_text() + self.close_call()
            self.call = call_id
            self.started.add(call_id)
            events.append(ToolCallStartEvent(
                tool_call_id=call_id,
                tool_call_name=chunk["name"],
                parent_message_id=parent_id,
                metadata=extras(approval=True) if chunk["name"] in APPROVAL_REQUIRED else None,
            ))
            args = self.early_args.pop(key, "") + args
        elif call_id != self.call:
            # Um provedor que intercala as chamadas: a anterior já foi fechada, e
            # os argumentos completos chegam no fim da mensagem (ver `finish`).
            return []

        if args:
            events.append(ToolCallArgsEvent(tool_call_id=call_id, delta=args))
        return events

    def finish(self, tool_calls: list[dict[str, Any]], parent_id: str) -> list[BaseEvent]:
        """Fecha o que ficou aberto e anuncia as chamadas que o stream não trouxe."""
        events = self.close_text() + self.close_call()
        for call in tool_calls:
            if call["id"] in self.started:
                continue
            events += [
                ToolCallStartEvent(
                    tool_call_id=call["id"],
                    tool_call_name=call["name"],
                    parent_message_id=parent_id,
                    metadata=extras(approval=True) if call["name"] in APPROVAL_REQUIRED else None,
                ),
                ToolCallArgsEvent(tool_call_id=call["id"], delta=json.dumps(call["args"], ensure_ascii=False)),
                ToolCallEndEvent(tool_call_id=call["id"]),
            ]
        return events


def _result(recorder: TurnRecorder, message: ToolMessage, *, cancelled: bool = False) -> ToolCallResultEvent:
    status = "cancelled" if cancelled else "failed" if message.status == "error" else "completed"
    return ToolCallResultEvent(
        message_id=str(recorder.result_id(message.tool_call_id)),
        tool_call_id=message.tool_call_id,
        content=message.text,
        role="tool",
        # O artefato (a série do gráfico do desempenho) vai só para a
        # interface; o modelo recebeu apenas o conteúdo.
        metadata=extras(status=status, artifact=getattr(message, "artifact", None)),
    )


async def run(
    app: FastAPI,
    thread: dict[str, Any],
    recorder: TurnRecorder,
    graph_input: Any,
    run_id: str,
) -> AsyncIterator[BaseEvent]:
    """Executa o grafo, gravando as mensagens e traduzindo os eventos em AG-UI."""
    pool = app.state.pool
    graph = app.state.graph
    thread_id = str(thread["id"])
    # Cada turno roda numa thread própria do LangGraph: os checkpoints servem
    # para inspecionar a execução e para esperar a confirmação; o histórico vem
    # das nossas tabelas. O `thread_id` dos metadados é o da conversa: o
    # LangGraph só copia o do turno para lá quando ele falta, e é por ele que a
    # LangSmith agrupa os turnos de uma conversa.
    config = {
        "configurable": {"thread_id": recorder.graph_thread_id},
        "metadata": {"graham_thread_id": thread_id, "thread_id": thread_id},
    }
    profile = await memories.profile(pool, thread["user_id"], memory_processing.profile_limit())
    context = AgentContext(
        user_id=thread["user_id"],
        pool=pool,
        profile=tuple(row["content"] for row in profile),
    )

    yield RunStartedEvent(thread_id=thread_id, run_id=run_id, protocol_version=PROTOCOL_VERSION)

    stream = _Stream()
    # Mesmo cuidado do CLI: o modelo emite espaços em branco antes de anunciar
    # uma ferramenta, e eles não devem aparecer na tela.
    began = False

    # A chamada ao modelo que ainda não produziu nada visível. Esse silêncio é
    # o raciocínio do modelo: o gateway o envia num campo que o ChatOpenAI
    # descarta, então ele não é lido, só medido.
    thinking: tuple[str, float] | None = None

    def stop_thinking() -> BaseEvent:
        nonlocal thinking
        reasoning_id, since = thinking
        milliseconds = round((time.monotonic() - since) * 1000)
        thinking = None
        recorder.thought(milliseconds)
        return ReasoningEndEvent(message_id=reasoning_id, metadata=extras(ms=milliseconds))

    # Cotações já obtidas pelas ferramentas, e todo ticker que passou por elas.
    quotes: dict[str, dict[str, Any]] = {}
    candidates: list[str] = []
    answer = ""
    # Resultados já anunciados quando cada ferramenta terminou.
    announced: set[str] = set()

    # Só vira verdadeiro quando a execução termina, falha ou pausa. Se o
    # gerador for encerrado antes disso, o servidor está parando.
    settled = False

    # A conexão MCP do turno, aberta dentro do `try` para uma falha ao abri-la
    # ser tratada como qualquer erro do turno.
    connections = AsyncExitStack()

    try:
        connection = await connections.enter_async_context(
            mcp_tools.turn_connection(pool, thread["user_id"])
        )
        context = replace(context, mcp=connection)
        async for event in graph.astream_events(
            graph_input, config=config, context=context, version="v2"
        ):
            kind = event["event"]

            if kind == "on_chat_model_start":
                await recorder.model_started()
                stream = _Stream()
                began = False
                # A hora de início vai no evento: quem reconecta no meio
                # continua a contagem de onde ela está.
                thinking = (str(uuid4()), time.monotonic())
                yield ReasoningStartEvent(message_id=thinking[0], timestamp=_now_ms())

            elif kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if thinking is not None and (chunk.content.strip() or chunk.tool_call_chunks):
                    yield stop_thinking()
                if chunk.content:
                    recorder.token(chunk.content)
                    if began or chunk.content.strip():
                        began = True
                        answer += chunk.content
                        for item in stream.say(str(recorder.current), chunk.content):
                            yield item
                for piece in chunk.tool_call_chunks:
                    for item in stream.call_chunk(piece, str(recorder.current)):
                        yield item

            elif kind == "on_tool_end" and event["name"] not in APPROVAL_REQUIRED:
                output = event["data"].get("output")
                if not isinstance(output, ToolMessage):
                    continue
                payload = _tool_payload(output.text)
                # A cotação completa já vem pronta aqui: nenhum cartão que o
                # agente consultou precisa de uma segunda ida ao Yahoo.
                if event["name"] == "cotacao_atual_acao" and isinstance(payload, dict) and payload.get("ticker_name"):
                    quotes[payload["ticker_name"]] = payload
                candidates.extend(_symbols_in(payload))
                announced.add(output.tool_call_id)
                yield _result(recorder, output)

            # O fim de cada nó traz as mensagens que ele acrescentou ao estado.
            elif kind == "on_chain_end" and event["name"] == "agent":
                if thinking is not None:
                    yield stop_thinking()
                message = event["data"]["output"]["messages"][-1]
                for item in stream.finish(message.tool_calls, str(recorder.current)):
                    yield item
                await recorder.model_finished(message)

            elif kind == "on_chain_end" and event["name"] == "approval":
                output = event["data"]["output"]
                if isinstance(output, Command) and output.update:
                    cancelled = await recorder.approval_finished(output.update.get("messages", []))
                    for message in cancelled:
                        yield _result(recorder, message, cancelled=True)

            elif kind == "on_chain_end" and event["name"] == "tools":
                messages = event["data"]["output"]["messages"]
                await recorder.tools_finished(messages)
                # Daqui, e não do `on_tool_end`: as operações confirmadas e os
                # erros que escapam da ferramenta (tratados pelo ToolNode) só
                # aparecem nesta saída.
                for message in messages:
                    if message.tool_call_id not in announced:
                        announced.add(message.tool_call_id)
                        yield _result(recorder, message)

        cards = await _ticker_cards(quotes, candidates, answer)
        if cards:
            yield CustomEvent(name="graham.tickers", value=cards)

        # O grafo parou no nó de aprovação: o turno espera o usuário decidir.
        snapshot = await graph.aget_state(config)
        if snapshot.interrupts:
            requests = snapshot.interrupts[0].value
            approval_id = await recorder.pause(requests)
            settled = True
            yield RunFinishedEvent(
                thread_id=thread_id,
                run_id=run_id,
                outcome=RunFinishedInterruptOutcome(
                    interrupts=interrupts(requests, datetime.now(UTC))
                ),
                metadata=extras(messageId=str(approval_id)),
            )
            return

        settled = True
        # O turno concluído vira memória `conversa`, para ser reencontrado depois.
        memory_processing.spawn(
            memory_processing.index_turn(pool, thread["user_id"], thread["title"], recorder.last)
        )
        yield RunFinishedEvent(
            thread_id=thread_id, run_id=run_id, metadata=extras(messageId=str(recorder.last))
        )

    except Exception as error:  # noqa: BLE001 - o erro precisa chegar ao cliente
        settled = True
        detail = f"{type(error).__name__}: {error}"
        message_id = await recorder.stop("failed", error=detail)
        yield RunErrorEvent(message=detail, metadata=extras(messageId=str(message_id)))

    finally:
        if not settled:
            # O cancelamento atinge também estas escritas; o escudo garante que
            # o texto parcial seja salvo antes de o gerador fechar.
            with anyio.CancelScope(shield=True):
                await recorder.stop("interrupted")
        with anyio.CancelScope(shield=True):
            await connections.aclose()
