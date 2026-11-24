from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    from backend.core.contracts import TaskCommand
except ImportError:
    from core.contracts import TaskCommand


@dataclass
class SkillDefinition:
    name: str
    description: str
    version: str = "1.0.0"
    triggers: list[str] = field(default_factory=list)
    instructions: str = ""
    file_path: str = ""


class SkillLoader:
    """Discovers, parses, and provides runtime access to native Cortex skills.

    Adheres to the Agent Skills standard with YAML frontmatter and Markdown body.
    Injects skill instructions dynamically when relevant tasks are being executed.
    """

    EMAIL_COMMANDS = {
        TaskCommand.READ_MAIL,
        TaskCommand.SUMMARIZE_MAIL,
        TaskCommand.DRAFT_MAIL,
        TaskCommand.SEND_MAIL,
        TaskCommand.SEARCH_MAIL,
        TaskCommand.EMAIL_BRIEFING,
        TaskCommand.EXTRACT_ACTIONS,
        TaskCommand.REPLY_MAIL,
        TaskCommand.FORWARD_MAIL,
    }

    EMAIL_KEYWORD_PATTERNS = (
        r"\b(?:email|emails|mail|inbox|mailbox|draft|unread)\b",
        r"\b(?:reply|forward)\b.*\b(?:email|mail|message|invitation|it|this)\b",
        r"\b(?:summarize|summarise)\b.*\b(?:email|emails|mail|message|inbox)\b",
        r"\b(?:send|write|draft|compose)\b.*\b(?:email|mail)\b",
        r"\b(?:need\s+to\s+respond|need\s+my\s+attention|ask\s+me\s+to\s+do\s+anything|pending\s+follow-?ups)\b",
    )

    def __init__(self, skills_dir: Optional[str | Path] = None) -> None:
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            # Locate skills directory relative to this file or project root
            base_dir = Path(__file__).resolve().parents[2]
            self.skills_dir = base_dir / "skills"
        self._skills: dict[str, SkillDefinition] = {}
        self.load_all()

    def load_all(self) -> dict[str, SkillDefinition]:
        """Discovers and parses all SKILL.md files in the skills directory."""
        if not self.skills_dir.exists():
            return {}

        for skill_file in self.skills_dir.glob("*/SKILL.md"):
            try:
                skill = self._parse_skill_file(skill_file)
                if skill:
                    self._skills[skill.name] = skill
            except Exception:
                continue
        return self._skills

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        if name not in self._skills:
            self.load_all()
        return self._skills.get(name)

    def is_email_task(self, intent: str, command: Any = None) -> bool:
        """Determines whether a given user intent or command pertains to email operations."""
        if command:
            cmd_val = command.value if hasattr(command, "value") else str(command)
            if any(cmd_val == c.value for c in self.EMAIL_COMMANDS):
                return True
        intent_lower = str(intent).lower()
        return any(re.search(pat, intent_lower) for pat in self.EMAIL_KEYWORD_PATTERNS)

    def get_active_skills_for_task(self, intent: str, command: Any = None) -> list[SkillDefinition]:
        """Returns the list of active skills relevant to the current task."""
        active: list[SkillDefinition] = []
        if self.is_email_task(intent, command):
            skill = self.get_skill("email-agent")
            if skill:
                active.append(skill)
        return active

    def get_prompt_extension_for_task(self, intent: str, command: Any = None) -> str:
        """Generates the prompt instructions to append to the system prompt for relevant tasks.

        Returns an empty string for unrelated tasks (e.g. calculator, notes) to keep context clean.
        """
        active_skills = self.get_active_skills_for_task(intent, command)
        if not active_skills:
            return ""

        parts = ["\n\n--- ACTIVE SKILL DIRECTIVES ---"]
        for s in active_skills:
            parts.append(f"### Skill: {s.name} (v{s.version})\n{s.description}\n\n{s.instructions}")
        parts.append("--- END SKILL DIRECTIVES ---\n")
        return "\n".join(parts)

    def _parse_skill_file(self, path: Path) -> Optional[SkillDefinition]:
        content = path.read_text(encoding="utf-8")
        # Check for YAML frontmatter between --- and ---
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if not fm_match:
            return None

        frontmatter_raw = fm_match.group(1)
        body = fm_match.group(2).strip()

        # Parse basic YAML fields
        name = path.parent.name
        description = ""
        version = "1.0.0"
        triggers: list[str] = []

        in_triggers = False
        for line in frontmatter_raw.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            if line_str.startswith("name:"):
                name = line_str.split(":", 1)[1].strip().strip("\"'")
                in_triggers = False
            elif line_str.startswith("description:"):
                description = line_str.split(":", 1)[1].strip().strip("\"'")
                in_triggers = False
            elif line_str.startswith("version:"):
                version = line_str.split(":", 1)[1].strip().strip("\"'")
                in_triggers = False
            elif line_str.startswith("triggers:"):
                in_triggers = True
            elif in_triggers and line_str.startswith("-"):
                trig = line_str.lstrip("-").strip().strip("\"'")
                if trig:
                    triggers.append(trig)
            else:
                in_triggers = False

        return SkillDefinition(
            name=name,
            description=description,
            version=version,
            triggers=triggers,
            instructions=body,
            file_path=str(path.resolve()),
        )
