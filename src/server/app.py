"""Servidor HTTP do Graham: serve a interface e transmite as respostas do agente."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.agent.runtime.state_graph import RE_ACT_GRAPH, AgentState
from src.agent.tools.definition import get_current_stock_price

STATIC_DIR = Path(__file__).parent / "static"

# Quantos cartões de ticker podem ser enviados ao final de uma resposta.
MAX_TICKER_CARDS = 8

# Teto para o retorno da ferramenta exibido na interface, em caracteres.
MAX_TOOL_PREVIEW = 20_000

app = FastAPI(title="Graham Agent", description="Seu corretor de confiança")


class ChatRequest(BaseModel):
    """Uma pergunta do usuário dentro de uma conversa."""

    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(
        min_length=1,
        max_length=100,
        description="Identifica a conversa; o checkpointer guarda o histórico por thread.",
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    """Formata um evento no protocolo Server-Sent Events."""
    # `json.dumps` escapa quebras de linha, então o payload nunca quebra o frame.
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _tool_payload(output: Any) -> Any:
    """Extrai o dado que a ferramenta devolveu de dentro do ToolMessage."""
    content = getattr(output, "content", output)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return content


def _tool_preview(payload: Any) -> Any:
    """Prepara o retorno da ferramenta para exibição, limitando o tamanho."""
    if payload is None:
        return None
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) > MAX_TOOL_PREVIEW:
        return {
            "aviso": "Resultado longo demais para exibir por inteiro.",
            "caracteres": len(serialized),
        }
    return payload


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
    for key in ("matches", "companies"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and item.get("ticker_name"):
                symbols.append(item["ticker_name"])
    return symbols


def _mentioned(symbol: str, text: str) -> bool:
    """O agente citou este ticker na resposta? 'BBAS3' conta por 'BBAS3.SA'."""
    return symbol in text or symbol.split(".")[0] in text


async def _ticker_cards(
    quotes: dict[str, dict[str, Any]], candidates: list[str], answer: str
) -> list[dict[str, Any]]:
    """Monta os cartões dos tickers citados, buscando só o que ainda falta."""
    wanted = []
    for symbol in candidates:
        if symbol not in wanted and _mentioned(symbol, answer):
            wanted.append(symbol)
    wanted.sort(key=lambda symbol: answer.find(symbol.split(".")[0]))
    wanted = wanted[:MAX_TICKER_CARDS]

    missing = [symbol for symbol in wanted if symbol not in quotes]
    if missing:
        # A ferramenta é síncrona; o LangChain a roda numa thread, então as
        # consultas que faltam acontecem em paralelo e fora do event loop.
        fetched = await asyncio.gather(
            *(get_current_stock_price.ainvoke({"ticker_name": symbol}) for symbol in missing),
            return_exceptions=True,
        )
        for symbol, result in zip(missing, fetched):
            if isinstance(result, dict):
                quotes[symbol] = result

    return [_ticker_card(quotes[symbol]) for symbol in wanted if symbol in quotes]


async def _stream_answer(message: str, thread_id: str) -> AsyncIterator[str]:
    """Traduz os eventos do grafo em eventos SSE para o navegador."""
    config = {"configurable": {"thread_id": thread_id}}
    entrada: AgentState = {"messages": [HumanMessage(message)]}
    # Mesmo cuidado do CLI: o modelo emite espaços em branco antes de anunciar
    # uma ferramenta, e eles não devem aparecer na tela.
    comecou = False

    # Cotações já obtidas pelas ferramentas, e todo ticker que passou por elas.
    quotes: dict[str, dict[str, Any]] = {}
    candidates: list[str] = []
    answer = ""

    try:
        async for event in RE_ACT_GRAPH.astream_events(entrada, config=config, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    if not comecou and not chunk.content.strip():
                        continue
                    comecou = True
                    answer += chunk.content
                    yield _sse("token", {"text": chunk.content})

            elif kind == "on_tool_start":
                yield _sse(
                    "tool_start",
                    {"name": event["name"], "input": event["data"].get("input")},
                )

            elif kind == "on_tool_end":
                comecou = False

                payload = _tool_payload(event["data"].get("output"))
                # A cotação completa já vem pronta aqui: nenhum cartão que o
                # agente consultou precisa de uma segunda ida ao Yahoo.
                if event["name"] == "cotacao_atual_acao" and isinstance(payload, dict):
                    if payload.get("ticker_name"):
                        quotes[payload["ticker_name"]] = payload
                candidates.extend(_symbols_in(payload))

                yield _sse(
                    "tool_end",
                    {"name": event["name"], "output": _tool_preview(payload)},
                )

        for card in await _ticker_cards(quotes, candidates, answer):
            yield _sse("ticker", card)

    except Exception as error:  # noqa: BLE001 - o erro precisa chegar à interface
        yield _sse("error", {"message": f"{type(error).__name__}: {error}"})

    yield _sse("done", {})


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Responde a uma pergunta transmitindo os tokens conforme são gerados."""
    return StreamingResponse(
        _stream_answer(request.message, request.thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Impede que proxies (nginx e afins) segurem o corpo em buffer.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Confirma que o grafo foi compilado e quantas ferramentas estão ligadas."""
    return {"status": "ok", "nodes": list(RE_ACT_GRAPH.get_graph().nodes)}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
