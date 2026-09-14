from pathlib import Path
from typing_extensions import Final
from langchain_core.messages import SystemMessage

SYSTEM_PROMPT: Final[SystemMessage] = SystemMessage(
    content=(Path(__file__).parent / "system_prompt.md").read_text(encoding="utf-8")
)
