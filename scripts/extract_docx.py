"""Extract text and embedded images from a .docx (Office Open XML) file.

Companion to ``extract_doc.py`` (which handles the legacy OLE ``.doc`` format).
Text keeps headings as Markdown-ish prefixes and tables as tab-separated rows so
the storyboard rules can still match section keywords.

Usage:
    python extract_docx.py <file.docx> <out_dir> [--json]

Outputs: <out_dir>/disclosure.txt and <out_dir>/media/*.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


def extract_text(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower()
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            lines.append("#" * int(level) + " " + text)
        else:
            lines.append(text)
    for table_index, table in enumerate(document.tables, start=1):
        lines.append(f"\n## 表 {table_index}")
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def extract_images(path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.startswith("word/media/"):
                continue
            data = archive.read(name)
            if len(data) < 3000:
                continue
            target = out_dir / Path(name).name
            target.write_bytes(data)
            written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="docx → 正文 + 插图")
    parser.add_argument("docx")
    parser.add_argument("out_dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    source, out_dir = Path(args.docx), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        text = extract_text(source)
    except ImportError:
        raise SystemExit("需要 python-docx：pip install python-docx")
    (out_dir / "disclosure.txt").write_text(text, encoding="utf-8")
    images = extract_images(source, out_dir / "media")
    # 保留原文件后缀的小写别名，便于下游按扩展名处理
    payload = {"docx": str(source), "characters": len(text),
               "images": len(images), "out_dir": str(out_dir)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"正文 {len(text)} 字、插图 {len(images)} 张 → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
