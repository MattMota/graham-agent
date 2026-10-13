"""As skills do servidor MCP, usadas pelo próprio Graham.

O prompt lista nome e descrição de cada skill (o catálogo, lido do MCP na
subida); `ler_skill` carrega o texto dela quando a tarefa pede. É a revelação
progressiva do padrão de skills: o roteiro só entra no contexto quando usado.
"""

from typing import Any

from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.runtime import get_runtime
from mcp import Client
from pydantic import BaseModel, Field

from src.agent.runtime.context import AgentContext
from src.mcp_server import server as mcp_server


class SkillEntry(BaseModel):
    name: str
    description: str
    # O endereço da pasta da skill: `skill://<grupo>/<nome>`.
    base: str


async def load_catalog() -> list[SkillEntry]:
    """As skills que o MCP publica, pelos resources `SKILL.md`."""
    async with Client(mcp_server.server) as local:
        listed = (await local.list_resources()).resources
    return [
        SkillEntry(name=resource.name, description=resource.description or "", base=str(resource.uri)[: -len("/SKILL.md")])
        for resource in listed
        if str(resource.uri).startswith("skill://") and str(resource.uri).endswith("/SKILL.md")
    ]


def catalog_prompt(catalog: list[SkillEntry]) -> str:
    """A seção do prompt que aponta para as skills."""
    if not catalog:
        return ""
    lines = "\n".join(f"- `{entry.name}`: {entry.description}" for entry in catalog)
    return (
        "Roteiros prontos para tarefas recorrentes. Quando a tarefa for uma destas, carregue a "
        f"skill com `ler_skill` antes de começar e siga-a:\n\n{lines}"
    )


class ReadSkillInput(BaseModel):
    name: str = Field(title="Skill", description="O nome da skill, como aparece na lista das instruções.")
    file: str = Field(
        default="SKILL.md",
        title="Arquivo",
        description="Um arquivo de apoio citado pela skill, relativo à pasta dela; por padrão, o SKILL.md.",
    )


def build_tool(catalog: list[SkillEntry]) -> BaseTool:
    by_name = {entry.name: entry for entry in catalog}

    @tool("ler_skill", args_schema=ReadSkillInput)
    async def read_skill(name: str, file: str = "SKILL.md") -> str:
        """Carrega o texto de uma skill (um roteiro para uma tarefa recorrente) ou de um arquivo de apoio dela."""
        entry = by_name.get(name)
        if entry is None:
            raise ToolException(f"Não há skill '{name}'. As disponíveis: {', '.join(sorted(by_name))}.")
        uri = f"{entry.base}/{file.strip().lstrip('/')}"
        context = get_runtime(AgentContext).context
        connection: Any = context.mcp if isinstance(context, AgentContext) else None
        try:
            if connection is not None:
                result = await connection.read_resource(uri)
            else:
                async with Client(mcp_server.server) as local:
                    result = await local.read_resource(uri)
        except Exception as error:  # noqa: BLE001 - um arquivo que não existe vira resposta legível
            raise ToolException(f"Não foi possível ler {file} da skill '{name}': {error}") from None
        return "\n".join(content.text for content in result.contents if getattr(content, "text", None))

    read_skill.handle_tool_error = True
    return read_skill
