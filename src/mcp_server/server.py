"""O servidor MCP do Graham: as ferramentas do catálogo, protegidas por token.

Serve tanto o Graham, que chama em nome do usuário com um token interno por
turno, quanto agentes de terceiros, com uma chave de acesso criada pelo
usuário. Montado na mesma app do servidor web, em `/mcp`.
"""

import inspect
import json
import os
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from src.mcp_server import resources
from src.mcp_server.skills import SKILLS
from src.mcp_server.skills_extension import SkillsExtension, register_prompts
from src.storage import tokens
from src.tools.catalog import CATALOG, READ, WRITE, ToolSpec
from src.tools.context import ToolContext, ToolFailure

PATH = "/mcp"


def public_url() -> str:
    """Endereço pelo qual o servidor é alcançado de fora, sem barra no fim."""
    return os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")


# O pool vem do servidor web, que o abre na subida; o MCP só o empresta.
_pool: AsyncConnectionPool | None = None


def attach(pool: AsyncConnectionPool | None) -> None:
    global _pool
    _pool = pool


class TokenVerifier:
    """Chaves de acesso e tokens internos, os dois em `core.access_tokens`."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if _pool is None or not token.startswith(tokens.PREFIX):
            return None
        row = await tokens.verify(_pool, token)
        if row is None:
            return None
        return AccessToken(
            token=token,
            client_id=f"graham-{row['kind']}-{row['id']}",
            scopes=list(row["scopes"]),
            expires_at=int(row["expires_at"].timestamp()) if row["expires_at"] else None,
            subject=str(row["user_id"]),
        )


server = MCPServer(
    "graham",
    instructions=(
        "Dados de mercado (B3 e bolsas dos EUA), notícias, proventos, desempenho e a carteira "
        "e a watchlist do usuário dono da chave. Ações brasileiras usam o sufixo '.SA'. "
        "As ferramentas que gravam exigem uma chave com permissão de escrita. Antes de usá-las, "
        "leia o resource graham://convencoes; graham://glossario explica os termos dos resultados. "
        "Roteiros prontos (analisar um ativo, explicar um movimento, revisar a carteira, registrar "
        "uma operação) estão nas skills (skills/list) e nos prompts de mesmo nome."
    ),
    extensions=[SkillsExtension(SKILLS)],
    token_verifier=TokenVerifier(),
    auth=AuthSettings(
        issuer_url=public_url(),
        resource_server_url=f"{public_url()}{PATH}",
        required_scopes=[READ],
        validate_token_resource=False,
    ),
)


def _failure(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, item['loc'])) or 'argumentos'}: {item['msg']}" for item in error.errors())


def _context(spec: ToolSpec) -> ToolContext:
    token = get_access_token()
    if token is None:
        # Chamada em processo (o REPL, a listagem na subida): sem usuário.
        return ToolContext()
    if spec.writes and WRITE not in token.scopes:
        raise ToolError(
            "Esta chave só tem permissão de leitura. Para gravar na carteira ou na watchlist, "
            "crie uma chave com a permissão de escrita."
        )
    return ToolContext(pool=_pool, user_id=UUID(token.subject))


def _register(spec: ToolSpec) -> None:
    async def handler(**arguments: Any) -> CallToolResult:
        # Os validadores do modelo (o ticker em maiúsculas, o setor pelo nome
        # aproximado) rodam aqui; a assinatura gerada abaixo só descreve os campos.
        try:
            args = spec.input_model.model_validate(arguments)
        except ValidationError as error:
            raise ToolError(_failure(error)) from None
        try:
            result = await spec.run(_context(spec), **args.model_dump())
        except (ToolFailure, ValueError) as error:
            raise ToolError(str(error)) from None

        content, chart = result if spec.chart else (result, None)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(content, ensure_ascii=False, default=str))],
            # O gráfico vai à parte: quem desenha a interface o usa, o agente não o lê.
            structured_content={"chart": chart} if chart else None,
        )

    # O MCPServer descreve a entrada a partir da assinatura da função: ela é
    # gerada dos campos do modelo, com descrições, limites e valores padrão.
    parameters = [
        inspect.Parameter(
            field,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=Annotated[info.annotation, info],
            default=inspect.Parameter.empty if info.is_required() else info.default,
        )
        for field, info in spec.input_model.model_fields.items()
    ]
    handler.__signature__ = inspect.Signature(parameters, return_annotation=CallToolResult)
    handler.__annotations__ = {parameter.name: parameter.annotation for parameter in parameters}
    handler.__annotations__["return"] = CallToolResult

    server.add_tool(
        handler,
        name=spec.name,
        description=spec.description,
        annotations=ToolAnnotations(
            read_only_hint=not spec.writes,
            # As que gravam mexem em dinheiro do usuário: o cliente deve pedir
            # a confirmação dele antes.
            destructive_hint=spec.writes,
            open_world_hint=not spec.writes,
        ),
    )


for _spec in CATALOG:
    _register(_spec)

resources.register(server)
register_prompts(server, SKILLS)


def _allowed_hosts() -> list[str]:
    host = urlsplit(public_url()).netloc
    return sorted({host, "127.0.0.1:*", "localhost:*"})


app = server.streamable_http_app(
    streamable_http_path=PATH,
    transport_security=TransportSecuritySettings(
        allowed_hosts=_allowed_hosts(),
        allowed_origins=[public_url(), "http://127.0.0.1:*", "http://localhost:*"],
    ),
)
