"""Grava no banco as mensagens de um turno conforme o grafo as produz."""

import json
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from psycopg_pool import AsyncConnectionPool

from src.agent.config.model import SETTINGS
from src.storage import conversations, memories

MODEL = SETTINGS["llm"]["model"]
MODEL_PARAMS = {"temperature": SETTINGS["llm"]["temperature"]}


class TurnRecorder:
    """Acompanha um turno do assistente, do primeiro token à resposta final.

    O turno nasce com uma mensagem do assistente em `streaming`. O id dela
    também nomeia a thread do LangGraph daquela execução, o que liga cada
    checkpoint ao turno que o produziu sem precisar de outra tabela.
    """

    def __init__(self, pool: AsyncConnectionPool, thread_id: UUID, first_id: UUID, parent_id: UUID):
        self.pool = pool
        self.thread_id = thread_id
        self.first_id = first_id
        # Mensagem do assistente sendo gerada agora, se houver.
        self.current: UUID | None = first_id
        # Última mensagem já concluída: é dela que a próxima descende.
        self.last = parent_id
        # O texto chega em pedaços e só é gravado quando a mensagem fecha; se o
        # turno for interrompido, é o que se salva da resposta parcial.
        self.partial = ""
        # Tool calls da última mensagem do modelo, e a linha que as guarda.
        self.calls: dict[str, dict] = {}
        self.calls_id: UUID | None = None

    @classmethod
    async def start(cls, pool: AsyncConnectionPool, thread_id: UUID, question_id: UUID) -> "TurnRecorder":
        first_id = await cls._new_assistant(pool, thread_id, question_id)
        return cls(pool, thread_id, first_id, question_id)

    @classmethod
    def resume(
        cls,
        pool: AsyncConnectionPool,
        thread_id: UUID,
        first_id: UUID,
        approval_id: UUID,
        calls_id: UUID,
    ) -> "TurnRecorder":
        """Continua um turno pausado: o que vier agora descende da mensagem da pausa."""
        recorder = cls(pool, thread_id, first_id, approval_id)
        recorder.current = None
        recorder.calls_id = calls_id
        return recorder

    @staticmethod
    async def _new_assistant(pool: AsyncConnectionPool, thread_id: UUID, parent_id: UUID) -> UUID:
        return await conversations.add_message(
            pool, thread_id, parent_id, "assistant", "streaming", model=MODEL, params=MODEL_PARAMS
        )

    @property
    def graph_thread_id(self) -> str:
        return str(self.first_id)

    async def model_started(self) -> None:
        # A primeira chamada ao modelo usa a mensagem criada em `start`; as
        # seguintes, depois de cada rodada de ferramentas, abrem uma nova.
        if self.current is None:
            self.current = await self._new_assistant(self.pool, self.thread_id, self.last)
        self.partial = ""

    def token(self, text: str) -> None:
        self.partial += text

    async def model_finished(self, message: AIMessage) -> None:
        await conversations.update_message(
            self.pool,
            self.current,
            content=message.text,
            state="completed",
            payload={"tool_calls": message.tool_calls} if message.tool_calls else None,
        )
        self.calls = {call["id"]: call for call in message.tool_calls}
        if message.tool_calls:
            self.calls_id = self.current
        self.last, self.current = self.current, None

    async def tools_finished(self, messages: list[ToolMessage], *, cancelled: bool = False) -> None:
        for message in messages:
            call = self.calls.get(message.tool_call_id, {})
            payload = {
                "tool_call_id": message.tool_call_id,
                "name": message.name,
                "input": call.get("args"),
            }
            # Guardado para a interface redesenhar o gráfico ao reabrir a conversa;
            # o histórico entregue ao modelo usa só o conteúdo.
            if getattr(message, "artifact", None) is not None:
                payload["artifact"] = message.artifact
            if cancelled:
                payload["cancelled"] = True
            self.last = await conversations.add_message(
                self.pool,
                self.thread_id,
                self.last,
                "tool",
                "failed" if message.status == "error" else "completed",
                content=message.text,
                payload=payload,
            )
            if message.status != "error" and not cancelled:
                await self._link_memory(message)

    async def _link_memory(self, message: ToolMessage) -> None:
        """Liga a memória à mensagem do agente que chamou a ferramenta.

        A ferramenta não conhece o id da nossa linha dessa mensagem; o gravador,
        sim. A origem diz de que conversa um fato saiu, e quem pediu para
        esquecê-lo, o que serve de sinal para melhorar a geração de memórias.
        """
        if message.name not in ("guardar_memoria", "esquecer_memoria") or self.calls_id is None:
            return
        try:
            memory_id = UUID(json.loads(message.text)["memory_id"])
        except (ValueError, KeyError, TypeError):
            return
        if message.name == "guardar_memoria":
            await memories.add_sources(self.pool, memory_id, [self.calls_id])
        else:
            await memories.set_forgotten_by(self.pool, memory_id, self.calls_id)

    async def pause(self, requests: list[dict]) -> UUID:
        """Marca a pausa à espera de confirmação e devolve a mensagem que a marca.

        A mensagem guarda os pedidos como o modelo os fez; as decisões do usuário
        entram nela depois. As duas versões, lado a lado, mostram o que o usuário
        corrigiu.
        """
        self.last = await conversations.add_message(
            self.pool,
            self.thread_id,
            self.last,
            "assistant",
            "awaiting_approval",
            payload={"approval": {"requests": requests}},
        )
        return self.last

    async def approval_finished(self, messages: list[BaseMessage]) -> None:
        """Grava o que saiu do nó de aprovação: os valores aprovados e os cancelamentos."""
        for message in messages:
            if isinstance(message, AIMessage):
                # O histórico do modelo passa a ter os valores que o usuário aprovou.
                await conversations.revise_message(
                    self.pool, self.calls_id, payload={"tool_calls": message.tool_calls}
                )
                self.calls = {call["id"]: call for call in message.tool_calls}
        cancelled = [message for message in messages if isinstance(message, ToolMessage)]
        await self.tools_finished(cancelled, cancelled=True)

    async def stop(self, state: conversations.State, error: str | None = None) -> UUID:
        """Encerra um turno que não chegou ao fim e devolve a mensagem que o fecha.

        Se o modelo estava falando, a mensagem dele guarda o texto parcial. Se o
        turno parou entre uma ferramenta e outra, uma mensagem vazia do
        assistente marca o ponto de parada, para que todo turno incompleto
        termine numa mensagem `interrupted` ou `failed`.
        """
        payload = {"error": error} if error else None
        if self.current is None:
            self.current = await conversations.add_message(
                self.pool, self.thread_id, self.last, "assistant", state, payload=payload
            )
        else:
            await conversations.update_message(
                self.pool, self.current, content=self.partial, state=state, payload=payload
            )
        self.last = self.current
        return self.current
