"""Um modelo de chat roteirizado, para testar o agente sem chamar um provedor.

O modelo de verdade não é determinístico; o grafo, a confirmação e a tradução
para o AG-UI são. Com as respostas do modelo fixadas, o que se testa é o que
o Graham faz com elas.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


def says(text: str) -> AIMessage:
    return AIMessage(content=text)


def calls(*tool_calls: tuple[str, dict[str, Any]]) -> AIMessage:
    """Uma resposta que só chama ferramentas, com ids previsíveis."""
    return AIMessage(
        content="",
        tool_calls=[
            {"id": f"call_{name}_{index}", "name": name, "args": args, "type": "tool_call"}
            for index, (name, args) in enumerate(tool_calls)
        ],
    )


class ScriptedModel(BaseChatModel):
    """Devolve as respostas do roteiro, em ordem, e guarda o que recebeu."""

    script: list[AIMessage] = Field(default_factory=list)
    received: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.received.append(list(messages))
        if not self.script:
            raise AssertionError("O roteiro do modelo acabou: o grafo chamou o modelo mais vezes que o previsto.")
        return self.script.pop(0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs) -> Iterator[ChatGenerationChunk]:
        # Em pedaços, como um provedor: o texto palavra a palavra, cada
        # chamada de ferramenta com o id e o nome no primeiro fragmento.
        message = self._next(messages)
        for piece in re.findall(r"\S+\s*", message.content):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk
        for index, call in enumerate(message.tool_calls):
            chunk = ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_call_chunks=[{
                    "index": index, "id": call["id"], "name": call["name"],
                    "args": json.dumps(call["args"], ensure_ascii=False),
                }],
            ))
            if run_manager:
                run_manager.on_llm_new_token("", chunk=chunk)
            yield chunk
