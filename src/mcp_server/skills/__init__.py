"""Todas as skills do servidor MCP, reunidas dos grupos.

Cada grupo é uma pasta com as suas skills; cada skill, uma pasta com o
`SKILL.md` e um `__init__.py` que a carrega. Veja o CLAUDE.md desta pasta.
"""

from src.mcp_server.skills import analise, carteira
from src.mcp_server.skills.skill import Skill, SkillError

SKILLS: list[Skill] = [*analise.SKILLS, *carteira.SKILLS]

# O nome é também o do prompt da skill, e dois prompts não podem ter o mesmo.
_names = [skill.name for skill in SKILLS]
if len(set(_names)) != len(_names):
    raise SkillError(f"Nomes de skill repetidos: {sorted({n for n in _names if _names.count(n) > 1})}")
