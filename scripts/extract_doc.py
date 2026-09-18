"""Extract text and embedded images from a legacy Word .doc (OLE2) file.

Word COM automation can hang on documents with embedded objects, so the text is
read straight out of the OLE compound file using the Word 97+ piece table, and
embedded pictures are recovered by scanning the streams for image signatures.

Usage:
    python extract_doc.py <file.doc> <out_dir> [--json]

Outputs: <out_dir>/disclosure.txt (UTF-8) and <out_dir>/media/*.png|jpg|gif|bmp.
Newer .docx files are handled by python-docx instead (see SKILL.md stage 1).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import olefile

FIB_FC_CLX = 0x01A2
FIB_LCB_CLX = 0x01A6

IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)


def _table_stream_name(doc_stream: bytes) -> str:
    flags = struct.unpack_from("<H", doc_stream, 0x000A)[0]
    return "1Table" if (flags >> 9) & 1 else "0Table"


def _piece_table(doc_stream: bytes, table_stream: bytes) -> bytes:
    fc_clx, lcb_clx = struct.unpack_from("<II", doc_stream, FIB_FC_CLX)
    clx = table_stream[fc_clx:fc_clx + lcb_clx]
    index = 0
    while index < len(clx):
        kind = clx[index]
        if kind == 0x01:  # Prc
            size = struct.unpack_from("<h", clx, index + 1)[0]
            index += 3 + size
        elif kind == 0x02:  # Pcdt
            size = struct.unpack_from("<I", clx, index + 1)[0]
            return clx[index + 5:index + 5 + size]
        else:
            break
    raise RuntimeError("piece table (Clx) not found")


def extract_text(path: Path) -> str:
    with olefile.OleFileIO(str(path)) as ole:
        doc_stream = ole.openstream("WordDocument").read()
        table_stream = ole.openstream(_table_stream_name(doc_stream)).read()
        pcdt = _piece_table(doc_stream, table_stream)

        piece_count = (len(pcdt) - 4) // 12
        cps = struct.unpack_from(f"<{piece_count + 1}I", pcdt, 0)

        parts: list[str] = []
        for i in range(piece_count):
            offset = 4 * (piece_count + 1) + 8 * i
            fc = struct.unpack_from("<I", pcdt, offset + 2)[0]
            compressed = bool(fc & 0x40000000)
            position = fc & 0x3FFFFFFF
            length = cps[i + 1] - cps[i]
            if compressed:
                raw = doc_stream[position // 2: position // 2 + length]
                parts.append(raw.decode("cp936", errors="replace"))
            else:
                raw = doc_stream[position: position + length * 2]
                parts.append(raw.decode("utf-16-le", errors="replace"))

    text = "".join(parts)
    text = text.replace("\r", "\n").replace("\x07", "\t").replace("\x0b", "\n")
    text = text.replace("\x13", "").replace("\x14", "").replace("\x15", "")
    return text


def extract_images(path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with olefile.OleFileIO(str(path)) as ole:
        streams = ["/".join(entry) for entry in ole.listdir()]
        for stream_name in streams:
            try:
                data = ole.openstream(stream_name).read()
            except Exception:
                continue
            if len(data) < 128:
                continue
            for signature, extension in IMAGE_SIGNATURES:
                start = 0
                while True:
                    index = data.find(signature, start)
                    if index < 0:
                        break
                    start = index + 1
                    if extension == ".jpg":
                        end = data.find(b"\xff\xd9", index)
                        if end < 0:
                            continue
                        end += 2
                    elif extension == ".png":
                        end = data.find(b"IEND\xaeB`\x82", index)
                        if end < 0:
                            continue
                        end += 8
                    else:
                        continue
                    blob = data[index:end]
                    if len(blob) < 3000:  # skip thumbnails/icons
                        continue
                    target = out_dir / f"{stream_name.replace('/', '_')}_{index}{extension}"
                    target.write_bytes(blob)
                    written.append(target)

    # EMF/WMF blobs live outside the picture signature scan
    with olefile.OleFileIO(str(path)) as ole:
        for stream_name in ["/".join(entry) for entry in ole.listdir()]:
            try:
                data = ole.openstream(stream_name).read()
            except Exception:
                continue
            start = 0
            while True:
                index = data.find(b"\x01\x00\x00\x00\x00\x00\x00\x00", start)
                if index < 0:
                    break
                start = index + 1
                if data[index + 40:index + 44] == b" EMF":
                    size = struct.unpack_from("<I", data, index + 8)[0]
                    if 1000 < size < len(data) - index:
                        target = out_dir / f"{stream_name.replace('/', '_')}_{index}.emf"
                        target.write_bytes(data[index:index + size])
                        written.append(target)

    return written


def main() -> int:
    doc_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    text = extract_text(doc_path)
    (out_dir / "disclosure.txt").write_text(text, encoding="utf-8")
    print(f"text characters: {len(text)}")

    images = extract_images(doc_path, out_dir / "media")
    print(f"images extracted: {len(images)}")
    for image in images[:40]:
        print(f"  {image.name}  {image.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
