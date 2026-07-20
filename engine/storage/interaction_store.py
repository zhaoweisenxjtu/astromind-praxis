"""File-system interaction store.

教学互动全文以 Markdown 文件存储（YAML front matter + body），
按 ~/.meta-learning/interactions/{user_id}/{track_id}/{node_id}/{date}/ 组织。
"""

import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from ..db.database import DB_DIR  # ~/.meta-learning/

INTERACTIONS_DIR = DB_DIR / "interactions"

# YAML front matter pattern
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# Fields stored in front matter
_FRONT_FIELDS = {
    "interaction_id", "session_id", "type", "method",
    "level_before", "level_after", "duration",
}


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _interaction_filepath(
    user_id: int,
    track_id: int,
    node_id: int,
    interaction_id: int,
    interaction_type: str,
    when: Optional[date] = None,
) -> Path:
    """Build the file path for an interaction record."""
    d = when or date.today()
    return (
        INTERACTIONS_DIR
        / str(user_id)
        / str(track_id)
        / str(node_id)
        / d.isoformat()
        / f"{interaction_id}-{interaction_type}.md"
    )


def save_interaction(
    interaction_id: int,
    user_id: int,
    track_id: int,
    node_id: int,
    interaction_type: str,
    session_id: str,
    method_used: str = "",
    level_before: int = 1,
    level_after: int = 1,
    duration_seconds: int = 0,
    teacher_content: str = "",
    student_response: str = "",
    feedback: str = "",
    misconceptions: Optional[list[str]] = None,
) -> str:
    """Save full interaction text to file system. Returns the file path."""
    filepath = _interaction_filepath(
        user_id, track_id, node_id, interaction_id, interaction_type,
    )
    _ensure_dir(filepath.parent)

    # Build YAML front matter
    front = (
        f"---\n"
        f"interaction_id: {interaction_id}\n"
        f"session_id: {session_id}\n"
        f"type: {interaction_type}\n"
        f"method: {method_used or ''}\n"
        f"level_before: {level_before}\n"
        f"level_after: {level_after}\n"
        f"duration: {duration_seconds}\n"
        f"---\n\n"
    )

    # Build body
    parts = [front]

    if teacher_content:
        parts.append(f"## Teacher\n\n{teacher_content}\n\n")
    if student_response:
        parts.append(f"## Student\n\n{student_response}\n\n")
    if feedback:
        parts.append(f"## Feedback\n\n{feedback}\n\n")
    if misconceptions:
        parts.append("## Misconceptions\n\n")
        for m in misconceptions:
            parts.append(f"- {m}\n")

    content = "".join(parts)
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def load_interaction(file_path: str) -> dict:
    """Load interaction text from file. Returns dict with front matter + body sections."""
    path = Path(file_path)
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")

    # Parse front matter
    fm = {}
    body = text
    m = _FRONT_MATTER_RE.match(text)
    if m:
        raw = m.group(1)
        body = text[m.end():]
        for line in raw.strip().split("\n"):
            if ":" in line:
                key, _, val = line.partition(":")
                fm[key.strip()] = val.strip()

    # Parse body sections
    sections = {"teacher": "", "student": "", "feedback": "", "misconceptions": []}
    current_section = None
    for line in body.split("\n"):
        if line.startswith("## Teacher"):
            current_section = "teacher"
            continue
        elif line.startswith("## Student"):
            current_section = "student"
            continue
        elif line.startswith("## Feedback"):
            current_section = "feedback"
            continue
        elif line.startswith("## Misconceptions"):
            current_section = "misconceptions"
            continue
        elif line.startswith("## "):
            current_section = None
            continue

        if current_section == "misconceptions":
            stripped = line.strip()
            if stripped.startswith("- "):
                sections["misconceptions"].append(stripped[2:])
        elif current_section and line.strip():
            if sections[current_section]:
                sections[current_section] += "\n" + line
            else:
                sections[current_section] = line

    return {
        "front_matter": fm,
        "teacher_content": sections["teacher"],
        "student_response": sections["student"],
        "feedback": sections["feedback"],
        "misconceptions": sections["misconceptions"],
    }


def search_interactions(keyword: str, user_id: Optional[int] = None) -> list[dict]:
    """Search interaction files by keyword. Returns list of (filepath, snippet) dicts.

    遍历 interactions/ 目录，在文件内容中搜索关键词。
    如果 user_id 指定，只在对应子目录中搜索。
    """
    base = INTERACTIONS_DIR
    if user_id:
        base = base / str(user_id)
    if not base.exists():
        return []

    results = []
    for filepath in sorted(base.rglob("*.md")):
        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception:
            continue
        if keyword.lower() in text.lower():
            # Find first matching line as snippet
            snippet = ""
            for line in text.split("\n"):
                if keyword.lower() in line.lower():
                    snippet = line.strip()[:120]
                    break
            results.append({
                "file_path": str(filepath),
                "snippet": snippet,
            })

    return results
