"""Serve as skills pela extensão de skills do MCP (SEP-2640) e como prompts.

Pela extensão (`io.modelcontextprotocol/skills`), o agente decide quando
carregar uma skill: `skills/list` e `skills/get` dão nome, descrição e o
digest de cada arquivo, e os arquivos são resources em `skill://`. O SDK
documenta um suporte de servidor a skills que ainda não saiu na versão
publicada (2.3.0); até lá, esta extensão implementa os dois métodos sobre o
mecanismo genérico de extensões do SDK.

Como prompt, quem aciona é o usuário, com os argumentos preenchidos: o texto
devolvido é o `SKILL.md`, a variante escolhida pelo argumento (se houver) e os
valores pedidos. Serve aos clientes que ainda não falam a extensão.
"""

from typing import Any

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.prompts.base import Prompt, PromptArgument
from mcp.server.mcpserver.resources import TextResource
from mcp_types import PaginatedRequestParams, RequestParams

from src.mcp_server.skills import Skill

IDENTIFIER = "io.modelcontextprotocol/skills"

# `resources/read` responde a um recurso desconhecido com o mesmo código.
INVALID_PARAMS = -32602

# Por quanto tempo o cliente pode reaproveitar a listagem.
LIST_TTL_MS = 60 * 60 * 1000


class ListSkillsParams(PaginatedRequestParams):
    pass


class GetSkillParams(RequestParams):
    uri: str


def entry(skill: Skill) -> dict[str, Any]:
    """A entrada da skill em `skills/list` e `skills/get`."""
    return {
        "uri": skill.uri,
        "frontmatter": skill.frontmatter,
        "resources": [
            {"uri": skill.file_uri(file.path), "digest": file.digest, "size": len(file.content)}
            for file in skill.files
        ],
    }


class SkillsExtension(Extension):
    identifier = IDENTIFIER

    def __init__(self, skills: list[Skill]) -> None:
        self.skills = skills
        self.by_uri = {skill.uri: skill for skill in skills}

    def resources(self) -> list[ResourceBinding]:
        bindings = []
        for skill in self.skills:
            for file in skill.files:
                is_main = file.path == "SKILL.md"
                bindings.append(ResourceBinding(TextResource(
                    uri=skill.file_uri(file.path),
                    name=skill.name if is_main else file.path,
                    description=skill.description if is_main else None,
                    mime_type=file.mime_type,
                    text=file.content.decode("utf-8"),
                )))
        return bindings

    def methods(self) -> list[MethodBinding]:
        async def list_skills(ctx: Any, params: ListSkillsParams) -> dict[str, Any]:
            # O catálogo é pequeno: cabe numa página só, sem cursor. Os atributos
            # de cache (SEP-2549) são exigidos nas listagens da versão
            # 2026-07-28, a única em que a extensão é anunciada: as skills são as
            # mesmas para todo usuário e só mudam com uma nova versão do servidor.
            return {
                "skills": [entry(skill) for skill in self.skills],
                "ttlMs": LIST_TTL_MS,
                "cacheScope": "public",
            }

        async def get_skill(ctx: Any, params: GetSkillParams) -> dict[str, Any]:
            skill = self.by_uri.get(params.uri)
            if skill is None:
                raise MCPError(INVALID_PARAMS, f"Nenhuma skill em {params.uri}.")
            # A SEP deixa em aberto se a resposta leva os atributos de cache; os
            # clientes que validam o resultado (o Inspector) os exigem.
            return {"skill": entry(skill), "ttlMs": LIST_TTL_MS, "cacheScope": "public"}

        return [
            MethodBinding("skills/list", ListSkillsParams, list_skills),
            MethodBinding("skills/get", GetSkillParams, get_skill),
        ]


def render_prompt(skill: Skill, arguments: dict[str, str]) -> str:
    """O texto do prompt: a skill, a variante pedida e os valores informados."""
    parts = [skill.body.strip()]
    if skill.variants:
        chosen = skill.variants.files.get((arguments.get(skill.variants.argument) or "").strip().lower())
        if chosen:
            parts.append(skill.text(chosen).strip())
    given = [f"- {argument.name}: {arguments[argument.name]}" for argument in skill.arguments if arguments.get(argument.name)]
    if given:
        parts.append("Pedido do usuário:\n" + "\n".join(given))
    return "\n\n".join(parts)


def register_prompts(server: MCPServer, skills: list[Skill]) -> None:
    for skill in skills:
        def render(_skill: Skill = skill, **arguments: str) -> str:
            return render_prompt(_skill, arguments)

        server.add_prompt(Prompt(
            name=skill.name,
            description=skill.description,
            arguments=[
                PromptArgument(name=argument.name, description=argument.description, required=argument.required)
                for argument in skill.arguments
            ],
            fn=render,
        ))
