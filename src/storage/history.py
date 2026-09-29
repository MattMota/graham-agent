"""Converte o caminho de uma thread no histórico que o modelo recebe."""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from src.storage.conversations import Row


def to_langchain(rows: list[Row]) -> list[BaseMessage]:
    """Monta as mensagens do modelo a partir das linhas de `agent.messages`.

    Fica de fora o que não terminou: respostas interrompidas ou com erro e
    pedidos de ferramenta cuja resposta nunca chegou. Os provedores recusam um
    histórico com tool call sem a mensagem da ferramenta correspondente.
    """
    answered = {
        row["payload"]["tool_call_id"] for row in rows if row["role"] == "tool" and row["payload"]
    }
    # Só entram as respostas de ferramenta cujo pedido também entrou.
    kept_calls: set[str] = set()
    messages: list[BaseMessage] = []

    for row in rows:
        payload = row["payload"] or {}
        message_id = str(row["id"])

        if row["role"] == "user":
            messages.append(HumanMessage(row["content"], id=message_id))

        elif row["role"] == "assistant":
            calls = payload.get("tool_calls") or []
            if row["state"] != "completed" or any(call["id"] not in answered for call in calls):
                continue
            if not row["content"] and not calls:
                continue
            kept_calls.update(call["id"] for call in calls)
            messages.append(AIMessage(row["content"], tool_calls=calls, id=message_id))

        elif payload.get("tool_call_id") in kept_calls:
            messages.append(
                ToolMessage(
                    row["content"],
                    tool_call_id=payload["tool_call_id"],
                    name=payload.get("name"),
                    status="error" if row["state"] == "failed" else "success",
                    id=message_id,
                )
            )

    return messages


def split_turns(rows: list[Row]) -> list[list[Row]]:
    """Agrupa o caminho em turnos: cada pergunta sozinha e, depois dela, as
    mensagens do assistente e das ferramentas até a pergunta seguinte."""
    turns: list[list[Row]] = []
    for row in rows:
        if row["role"] == "user" or not turns or turns[-1][0]["role"] == "user":
            turns.append([row])
        else:
            turns[-1].append(row)
    return turns
