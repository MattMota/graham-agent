"""O contrato AG-UI do Graham: o que uma execução aceita e como a conversa
gravada vira mensagens e interrupções do protocolo.

O servidor é a fonte da verdade do histórico: das `messages` de uma execução,
só a pergunta nova é usada. Os extras do Graham (estado do turno, tempo de
pensamento, gráfico, cartões de confirmação) vão em `metadata.graham`, espaço
que o AG-UI deixa livre em todo evento e mensagem; um cliente que não os
conhece os ignora.
"""

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ag_ui.core import (
    AssistantMessage,
    FunctionCall,
    Interrupt,
    Message,
    RunAgentInput,
    RunFinishedInterruptOutcome,
    ToolCall,
    ToolMessage,
    UserMessage,
)

from src.agent.tools.registry import APPROVAL_REQUIRED
from src.storage.conversations import Row
from src.tools.catalog import BY_NAME

# Por quanto tempo os checkpoints de um turno ficam guardados. Uma confirmação
# só pode ser respondida enquanto o checkpoint da pausa existir.
CHECKPOINT_RETENTION = timedelta(days=1)

APPROVAL_TITLES = {
    "registrar_compra": "Registrar compra na carteira",
    "registrar_venda": "Registrar venda na carteira",
    "adicionar_watchlist": "Adicionar à watchlist",
    "remover_watchlist": "Remover da watchlist",
    "definir_alocacao": "Definir a alocação-alvo",
}

# Campos que o usuário não corrige no cartão. Um ativo errado não é um valor a
# ajustar: é outra operação, então ele cancela e pede ao agente.
LOCKED_FIELDS = ("ticker_name",)

# Tamanho máximo de uma pergunta, em caracteres.
MAX_QUESTION = 4000


def extras(**values: Any) -> dict[str, Any]:
    """O `metadata` com os extras do Graham, sem os valores vazios."""
    return {"graham": {key: value for key, value in values.items() if value is not None}}


# Confirmação ────────────────────────────────────────────────────────────────


def _response_schema(name: str) -> dict[str, Any]:
    """A resposta que a interrupção espera, no padrão do AG-UI para aprovar
    uma chamada: `approved` e, opcionalmente, `editedArgs`, que substitui os
    argumentos inteiros."""
    schema = BY_NAME[name].input_model.model_json_schema()
    # Aninhado, o schema da ferramenta perderia as referências a `$defs`, que
    # são relativas à raiz.
    definitions = schema.pop("$defs", None)
    response = {
        "type": "object",
        "properties": {"approved": {"type": "boolean"}, "editedArgs": schema},
        "required": ["approved"],
    }
    if definitions:
        response["$defs"] = definitions
    return response


def interrupts(requests: list[dict[str, Any]], paused_at: datetime) -> list[Interrupt]:
    """Uma interrupção por operação à espera de confirmação.

    O id é o da tool call: a especificação não pede outro, e assim a resposta
    aponta direto para a operação.
    """
    expires_at = (paused_at + CHECKPOINT_RETENTION).isoformat()
    result = []
    for request in requests:
        properties = BY_NAME[request["name"]].input_model.model_json_schema()["properties"]
        result.append(Interrupt(
            id=request["tool_call_id"],
            reason="tool_call",
            tool_call_id=request["tool_call_id"],
            message=APPROVAL_TITLES.get(request["name"], request["name"]),
            response_schema=_response_schema(request["name"]),
            expires_at=expires_at,
            metadata=extras(
                name=request["name"],
                args=request["args"],
                locked=[field for field in LOCKED_FIELDS if field in properties],
            ),
        ))
    return result


def pending(path: list[Row]) -> RunFinishedInterruptOutcome | None:
    """A confirmação em aberto no fim do caminho, se houver."""
    last = path[-1] if path else None
    if last is None or last["state"] != "awaiting_approval":
        return None
    return RunFinishedInterruptOutcome(
        interrupts=interrupts(last["payload"]["approval"]["requests"], last["created_at"])
    )


# Snapshot ───────────────────────────────────────────────────────────────────


def _tool_call(call: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=call["id"],
        function=FunctionCall(name=call["name"], arguments=json.dumps(call["args"], ensure_ascii=False)),
        # As operações aparecem no cartão de confirmação, não como consulta.
        metadata=extras(approval=True) if call["name"] in APPROVAL_REQUIRED else None,
    )


def _message(row: Row) -> Message:
    payload = row["payload"] or {}
    message_id = str(row["id"])

    if row["role"] == "user":
        return UserMessage(id=message_id, content=row["content"])

    if row["role"] == "assistant":
        approval = payload.get("approval")
        return AssistantMessage(
            id=message_id,
            content=row["content"] or None,
            tool_calls=[_tool_call(call) for call in payload.get("tool_calls") or []] or None,
            metadata=extras(
                state=row["state"],
                thinkingMs=payload.get("thinking_ms"),
                error=payload.get("error"),
                approval={
                    "interrupts": [
                        item.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for item in interrupts(approval["requests"], row["created_at"])
                    ],
                    "decisions": approval.get("decisions"),
                } if approval else None,
            ),
        )

    status = "cancelled" if payload.get("cancelled") else row["state"]
    return ToolMessage(
        id=message_id,
        content=row["content"],
        tool_call_id=payload["tool_call_id"],
        error=row["content"] if status == "failed" else None,
        metadata=extras(name=payload.get("name"), status=status, artifact=payload.get("artifact")),
    )


def snapshot(path: list[Row]) -> list[Message]:
    """O caminho ativo da conversa como mensagens do AG-UI."""
    return [_message(row) for row in path]


# Entrada ────────────────────────────────────────────────────────────────────


class InvalidInput(ValueError):
    """Uma entrada que o Graham não aceita, com o motivo para o cliente."""


def uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise InvalidInput(f"{field} precisa ser um UUID.") from None


def question(body: RunAgentInput) -> UserMessage | None:
    """A última mensagem, se for do usuário: a candidata a pergunta nova.

    Um cliente AG-UI costuma mandar o histórico inteiro; se o id dela já está
    no banco, é histórico reenviado, e quem decide isso é quem chama.
    """
    last = body.messages[-1] if body.messages else None
    if not isinstance(last, UserMessage):
        return None
    uuid(last.id, "O id da mensagem do usuário")
    return last


def text(message: UserMessage) -> str:
    """O texto da pergunta; o Graham ainda não recebe imagens nem arquivos."""
    if isinstance(message.content, str):
        content = message.content
    else:
        if any(part.type != "text" for part in message.content):
            raise InvalidInput("O Graham só recebe texto nas perguntas.")
        content = "".join(part.text for part in message.content)
    if not content.strip():
        raise InvalidInput("A pergunta está vazia.")
    if len(content) > MAX_QUESTION:
        raise InvalidInput(f"A pergunta passa de {MAX_QUESTION} caracteres.")
    return content


def regenerate_target(body: RunAgentInput) -> UUID | None:
    """`forwardedProps.graham.regenerate`: o turno cuja resposta é refeita."""
    props = body.forwarded_props if isinstance(body.forwarded_props, dict) else {}
    target = (props.get("graham") or {}).get("regenerate")
    return None if target is None else uuid(str(target), "forwardedProps.graham.regenerate")
