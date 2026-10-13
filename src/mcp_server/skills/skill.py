"""Carregamento de uma skill: o `SKILL.md`, os arquivos de apoio e o que o
Markdown não carrega (os argumentos do prompt, as variantes, as ferramentas).

Cada pasta de skill tem um `__init__.py` que chama `load(__file__, ...)`. O
nome e a descrição vêm só do frontmatter do `SKILL.md`: a SEP-2640 publica o
frontmatter como está, e o cliente rejeita a skill se a listagem e o arquivo
divergirem. Tudo é validado na subida: uma skill malformada nem chega ao ar.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.tools.catalog import BY_NAME

# O padrão Agent Skills: minúsculas, números e hífens, sem hífen nas pontas.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64

SKILLS_ROOT = Path(__file__).resolve().parent

# O código que registra a skill não é conteúdo dela.
_IGNORED = {"__init__.py", "__pycache__"}


class SkillError(Exception):
    """Uma skill malformada, encontrada na subida."""


@dataclass(frozen=True)
class Argument:
    """Um argumento do prompt da skill. Chega sempre como texto."""

    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class Variants:
    """Conteúdo escolhido por um argumento do prompt.

    `files` liga cada valor do argumento a um arquivo de apoio da skill. No
    prompt, o arquivo do valor pedido vem junto do `SKILL.md`; como skill, o
    próprio `SKILL.md` diz ao agente qual arquivo ler.
    """

    argument: str
    files: dict[str, str]


@dataclass(frozen=True)
class SkillFile:
    path: str  # relativo à pasta da skill, com "/"
    content: bytes
    mime_type: str

    @property
    def digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.content).hexdigest()}"


@dataclass(frozen=True)
class Skill:
    group: str
    frontmatter: dict
    body: str  # o SKILL.md sem o frontmatter
    files: tuple[SkillFile, ...]
    arguments: tuple[Argument, ...] = ()
    variants: Variants | None = None
    tools: tuple[str, ...] = field(default=())

    @property
    def name(self) -> str:
        return self.frontmatter["name"]

    @property
    def description(self) -> str:
        return self.frontmatter["description"]

    @property
    def path(self) -> str:
        """O caminho da skill no espaço de nomes: o grupo e o nome."""
        return f"{self.group}/{self.name}"

    @property
    def uri(self) -> str:
        return f"skill://{self.path}/SKILL.md"

    def file_uri(self, path: str) -> str:
        return f"skill://{self.path}/{path}"

    def text(self, path: str) -> str:
        return next(file for file in self.files if file.path == path).content.decode("utf-8")


def _mime(path: Path) -> str:
    return "text/markdown" if path.suffix == ".md" else "text/plain"


def _frontmatter(text: str, where: Path) -> tuple[dict, str]:
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.S)
    if not match:
        raise SkillError(f"{where}: o SKILL.md precisa começar com o frontmatter YAML entre '---'.")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description"):
        raise SkillError(f"{where}: o frontmatter precisa de 'name' e 'description'.")
    return meta, match.group(2).lstrip("\n")


def load(
    init_file: str,
    *,
    arguments: tuple[Argument, ...] = (),
    variants: Variants | None = None,
    tools: tuple[str, ...] = (),
) -> Skill:
    """A skill da pasta deste `__init__.py`, validada."""
    folder = Path(init_file).resolve().parent
    skill_md = folder / "SKILL.md"
    if not skill_md.is_file():
        raise SkillError(f"{folder}: falta o SKILL.md.")
    meta, body = _frontmatter(skill_md.read_text(encoding="utf-8"), skill_md)

    name = meta["name"]
    if not NAME_PATTERN.match(name) or len(name) > MAX_NAME:
        raise SkillError(f"{skill_md}: nome '{name}' inválido (minúsculas, números e hífens, até {MAX_NAME}).")
    # A pasta é um pacote Python, sem hífen; o nome é o da pasta com '_' em '-'.
    if folder.name.replace("_", "-") != name:
        raise SkillError(f"{skill_md}: o nome '{name}' não corresponde à pasta '{folder.name}'.")
    group = folder.parent.relative_to(SKILLS_ROOT).as_posix()

    files = tuple(
        SkillFile(path.relative_to(folder).as_posix(), path.read_bytes(), _mime(path))
        for path in sorted(folder.rglob("*"))
        if path.is_file() and not _IGNORED & set(path.relative_to(folder).parts)
    )
    paths = {file.path for file in files}

    for tool in tools:
        if tool not in BY_NAME:
            raise SkillError(f"{skill_md}: cita a ferramenta '{tool}', que não está no catálogo.")
    names = {argument.name for argument in arguments}
    if variants:
        if variants.argument not in names:
            raise SkillError(f"{skill_md}: as variantes dependem do argumento '{variants.argument}', que não foi declarado.")
        for value, path in variants.files.items():
            if path not in paths:
                raise SkillError(f"{skill_md}: a variante '{value}' aponta para '{path}', que não existe.")

    return Skill(group, meta, body, files, tuple(arguments), variants, tuple(tools))
