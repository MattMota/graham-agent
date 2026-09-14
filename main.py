# main.py
import asyncio
from langchain_core.messages import HumanMessage
from src.agent.runtime.state_graph import RE_ACT_GRAPH, AgentState

CONFIG = {"configurable": {"thread_id": "cli"}}


async def responder(pergunta: str) -> None:
    entrada: AgentState = {"messages": [HumanMessage(pergunta)]}
    # O modelo costuma emitir espaços em branco antes de anunciar um tool call;
    # só começamos a imprimir quando chega conteúdo de verdade.
    comecou = False

    async for event in RE_ACT_GRAPH.astream_events(entrada, config=CONFIG, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if chunk.content:
                if not comecou and not chunk.content.strip():
                    continue
                comecou = True
                print(chunk.content, end="", flush=True)

        elif kind == "on_tool_start":
            print(f"\n  → {event['name']}({event['data']['input']})", flush=True)

        elif kind == "on_tool_end":
            print(f"\n  ← {event['name']} respondeu\n", flush=True)
            # A resposta final vem depois da ferramenta e traz o mesmo espaçamento.
            comecou = False


async def main() -> None:
    print("Graham Agent — digite 'sair' para encerrar.")

    while True:
        pergunta = input("\nvocê: ").strip()
        if pergunta.lower() in {"sair", "exit", "quit"}:
            break
        if not pergunta:
            continue

        print("\nagente: ", end="", flush=True)
        await responder(pergunta)
        print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAté logo.")
