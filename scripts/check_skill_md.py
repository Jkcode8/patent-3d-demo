"""Validate this skill's SKILL.md frontmatter against the skill-creator schema.

Only top-level frontmatter keys are checked, so nested ``metadata`` entries
(version, short-description, …) are allowed.

Usage:
    python check_skill_md.py [skill_dir]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED = {"name", "description", "license", "allowed-tools", "metadata"}


def top_level_keys(frontmatter: str) -> set[str]:
    keys = set()
    for line in frontmatter.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue                      # 嵌套键与注释不算顶层
        head, sep, _ = line.partition(":")
        if sep:
            keys.add(head.strip())
    return keys


def main() -> int:
    root = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1
            else Path(__file__).resolve().parent.parent)
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SystemExit("SKILL.md 缺少 frontmatter")
    frontmatter = text.split("---", 2)[1]
    keys = top_level_keys(frontmatter)
    extra = keys - ALLOWED
    if extra:
        raise SystemExit(f"frontmatter 含不允许的顶层键: {sorted(extra)}")
    missing = {"name", "description"} - keys
    if missing:
        raise SystemExit(f"frontmatter 缺少必需键: {sorted(missing)}")
    name = re.search(r"^name:\s*(\S+)", frontmatter, re.MULTILINE)
    if not name or not re.fullmatch(r"[a-z0-9-]{1,63}", name.group(1)):
        raise SystemExit("name 必须是小写字母/数字/连字符，且不超过 63 字符")
    if name.group(1) != root.name:
        raise SystemExit(f"name ({name.group(1)}) 与目录名 ({root.name}) 不一致")
    print(f"SKILL.md OK: name={name.group(1)} keys={sorted(keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
