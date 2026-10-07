"""Schemas de entrada das ferramentas de memória."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RememberInput(BaseModel):
    """Um fato a guardar na memória de longo prazo."""

    fact: str = Field(
        title="Fato",
        description=(
            "Um único fato, em uma frase autocontida, compreensível sem o resto da conversa, "
            "como 'O usuário tem perfil conservador.' Fatos independentes (perfil e horizonte, "
            "por exemplo) vão em memórias separadas, para que um possa mudar sem levar o outro."
        ),
        min_length=3,
        max_length=500,
    )
    # `conversa` fica de fora: só o sistema indexa os turnos.
    category: Literal["perfil", "preferencia", "interesse", "episodio"] = Field(
        title="Categoria",
        description=(
            "'perfil': tolerância a risco, horizonte, objetivos. 'preferencia': como o "
            "usuário quer as respostas (formato, moeda, nível de detalhe). 'interesse': "
            "setores e temas que acompanha ou evita, sem preço alvo (alvos ficam na "
            "watchlist). 'episodio': um acontecimento que vale lembrar, com a data."
        ),
    )


class RecallInput(BaseModel):
    """O que procurar na memória."""

    search_fact: str = Field(
        title="Busca",
        description="O que procurar, descrito como um fato ou uma pergunta, como 'bancos que o usuário acompanha'.",
        min_length=2,
        max_length=300,
    )


class MemoryIdInput(BaseModel):
    """Uma memória, pelo id devolvido por buscar_memorias."""

    memory_id: UUID = Field(title="Memória", description="O id da memória, como devolvido por buscar_memorias.")
