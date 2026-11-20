"""Read documents he shares (text, markdown, WhatsApp exports, zips) into attributed text chunks.

Pure functions, no I/O beyond the bytes given. Everything is bounded (upload size, unzipped size, characters), zips are read in
memory and never extracted to disk, and secrets are redacted before any text is returned.
"""

from __future__ import annotations

import codecs
import io
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from .chunks import CHUNK_MAX_CHARS, _split_unit
from .sessions import redact_secrets

CHUNK_CHARS = CHUNK_MAX_CHARS
SEGMENT_POINTS = 20  # chunks stored per card
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # Telegram's own download limit for bots
MAX_UNZIPPED_BYTES = 40 * 1024 * 1024
MAX_ZIP_MEMBERS = 500
MAX_DOC_CHARS = 1_000_000
MAX_PDF_PAGES = 300


class DocumentError(Exception):
    """A shared file cannot be used; the message is safe to show him."""


@dataclass(frozen=True)
class Message:
    when: datetime | None
    author: str
    text: str


@dataclass
class Upload:
    kind: str  # "whatsapp" | "markdown" | "text" | "pdf"
    name: str
    text: str
    messages: list[Message] = field(default_factory=list)
    pages: int = 0


# --- WhatsApp ---------------------------------------------------------------------------------------------------------

_DATE = r"(\d{1,2})/(\d{1,2})/(\d{2,4})"
_TIME = r"(\d{1,2}):(\d{2})(?::\d{2})?\s?([AaPp]\.?[Mm]\.?)?"
_ANDROID = re.compile(rf"^{_DATE},?\s+{_TIME}\s+-\s+([^:]{{1,80}}?):\s(.*)$")
_IOS = re.compile(rf"^\[{_DATE},?\s+{_TIME}\]\s+([^:]{{1,80}}?):\s(.*)$")
_SYSTEM = re.compile(rf"^(?:\[)?{_DATE},?\s+{_TIME}(?:\]|\s+-)\s+.*$")
_MARKS = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮﻿"))
_SKIP = re.compile(r"^<?\s*(media|image|video|audio|sticker|gif|document|contact card)( omitted)?\s*>?$|"
                   r"^\(file attached\)$|^this message was deleted\.?$|^you deleted this message\.?$", re.IGNORECASE)


def _when(raw: tuple, day_first: bool) -> datetime | None:
    a, b, y, hour, minute, ampm = raw
    day, month = (int(a), int(b)) if day_first else (int(b), int(a))
    year = int(y) + (2000 if int(y) < 100 else 0)
    h = int(hour)
    if ampm:
        h = h % 12 + (12 if ampm.lower().startswith("p") else 0)
    try:
        return datetime(year, month, day, h, int(minute))
    except ValueError:
        return None


def parse_whatsapp(text: str) -> list[Message]:
    """Messages of a WhatsApp export (Android or iOS), or [] when the text is not one. System lines and omitted media are
    dropped; continuation lines are joined to the message they belong to."""
    raw: list[tuple[tuple, str, str]] = []  # (date/time groups, author, text)
    for line in (l.translate(_MARKS).rstrip("\r") for l in text.split("\n")):
        match = _ANDROID.match(line) or _IOS.match(line)
        if match:
            g = match.groups()
            raw.append((g[:6], g[6].strip(), g[7]))
        elif _SYSTEM.match(line):
            raw.append((None, "", ""))  # a system message: skipped, and it ends the previous message
        elif raw and raw[-1][1]:
            when, author, body = raw[-1]
            raw[-1] = (when, author, body + "\n" + line)
    authored = [r for r in raw if r[1]]
    if len(authored) < 2:
        return []
    firsts = [int(r[0][0]) for r in authored]
    seconds = [int(r[0][1]) for r in authored]
    day_first = not (max(firsts) <= 12 and max(seconds) > 12)  # month-first only when a second field cannot be a month
    out = []
    for groups, author, body in authored:
        body = body.strip()
        if body and not _SKIP.match(body):
            out.append(Message(_when(groups, day_first), author, body))
    return out


# --- reading an upload ----------------------------------------------------------------------------------------------------

def _decode(data: bytes) -> str:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _zip_text(data: bytes) -> tuple[str, str]:
    try:
        return _zip_text_unsafe(data)
    except DocumentError:
        raise
    except zipfile.BadZipFile as e:
        raise DocumentError("that is not a valid zip file") from e
    except (RuntimeError, NotImplementedError, zlib.error, EOFError, OSError, ValueError) as e:
        raise DocumentError("that zip file could not be read (it may be encrypted or damaged)") from e


def _zip_text_unsafe(data: bytes) -> tuple[str, str]:
    zf = zipfile.ZipFile(io.BytesIO(data))
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and "__MACOSX" not in i.filename]
        if len(infos) > MAX_ZIP_MEMBERS or sum(i.file_size for i in infos) > MAX_UNZIPPED_BYTES:
            raise DocumentError("that zip is too large when unpacked")
        if any(i.filename.lower().endswith(".zip") for i in infos):
            raise DocumentError("nested zip files are not supported")
        texts = [i for i in infos if i.filename.lower().endswith(".txt") and not PurePosixPath(i.filename).name.startswith(".")]
        if not texts:
            raise DocumentError("no text file found inside that zip (export the chat without media)")
        texts.sort(key=lambda i: (not any(w in i.filename.lower() for w in ("whatsapp", "chat")), -i.file_size))
        with zf.open(texts[0]) as fh:
            body = fh.read(MAX_UNZIPPED_BYTES + 1)  # the header size can lie: bound the real read too
        if len(body) > MAX_UNZIPPED_BYTES:
            raise DocumentError("that zip is too large when unpacked")
        return PurePosixPath(texts[0].filename).name, _decode(body)


def _pdf_text(data: bytes) -> tuple[str, int]:
    """Text of a PDF, page by page. Scanned (image-only) PDFs have no text layer and are refused with a clear reason."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentError("that PDF is password-protected")
        count = len(reader.pages)
        if count > MAX_PDF_PAGES:
            raise DocumentError(f"that PDF has too many pages ({count}; the limit is {MAX_PDF_PAGES})")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except DocumentError:
        raise
    except Exception as e:  # pypdf can fail in many ways on hostile files (ZeroDivisionError, MemoryError, zlib.error...)
        raise DocumentError("that is not a valid PDF") from e
    text = "\n\n".join(p for p in pages if p)
    if not text.strip():
        raise DocumentError("that PDF has no readable text (it may be scanned; images are not supported yet)")
    return text, count


def read_upload(filename: str, data: bytes) -> Upload:
    """Turn a shared file into text (and parsed messages for a WhatsApp chat). Raises DocumentError with a clear reason."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError("that file is too large (the limit is 20 MB)")
    name = PurePosixPath(filename.replace("\\", "/")).name or "shared file"
    ext = PurePosixPath(name).suffix.lower()
    if ext == ".zip":
        name, text = _zip_text(data)
        ext = ".txt"
    elif ext == ".pdf":
        text, pages = _pdf_text(data)
        return Upload("pdf", name, redact_secrets(text.strip()[:MAX_DOC_CHARS]), pages=pages)
    elif ext in (".txt", ".md", ".markdown"):
        text = _decode(data)
    else:
        raise DocumentError(f"unsupported file type ({ext or 'no extension'}); send .txt, .md, a WhatsApp .zip or a PDF")
    text = redact_secrets(text.strip()[:MAX_DOC_CHARS])  # bound the size BEFORE scrubbing
    if not text.strip():
        raise DocumentError("that file is empty")
    messages = parse_whatsapp(text)
    if messages:
        return Upload("whatsapp", name, text, messages)
    return Upload("markdown" if ext in (".md", ".markdown") else "text", name, text)


# --- chunking -------------------------------------------------------------------------------------------------------------

def _header(when: datetime) -> str:
    return f"[{when.day} {when:%b %Y}]"


def _whatsapp_chunks(messages: list[Message], labels: dict[str, str]) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    last_day = None

    def flush() -> None:
        nonlocal current, size
        if current:
            chunks.append("\n".join(current))
        current, size = [], 0

    for m in messages:
        label = labels.get(m.author, m.author)
        lines: list[str] = []
        if m.when is not None and m.when.date() != last_day:
            lines.append(_header(m.when))
            last_day = m.when.date()
        room = max(CHUNK_CHARS - len(label) - 2, 200)
        lines += [f"{label}: {part}" for part in _split_unit(m.text, room)]
        for line in lines:
            if current and size + len(line) + 1 > CHUNK_CHARS:
                flush()
            current.append(line)
            size += len(line) + 1
    flush()
    return chunks


def _text_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for paragraph in (" ".join(p.split()) for p in re.split(r"\n\s*\n", text)):
        if not paragraph:
            continue
        for piece in _split_unit(paragraph, CHUNK_CHARS):
            if current and len(current) + 1 + len(piece) > CHUNK_CHARS:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def build_segments(upload: Upload, labels: dict[str, str]) -> list[list[str]]:
    """The text as chunks of at most CHUNK_CHARS, grouped into segments of at most SEGMENT_POINTS (one card each). In a
    WhatsApp chat every line says who spoke (`labels` maps an author's name to how he is shown, e.g. "Rahul (founder)")."""
    chunks = (_whatsapp_chunks(upload.messages, labels) if upload.kind == "whatsapp" else _text_chunks(upload.text))
    return [chunks[i:i + SEGMENT_POINTS] for i in range(0, len(chunks), SEGMENT_POINTS)]


_LINKEDIN = re.compile(r"sent the following message at \d{1,2}:\d{2}\s?[AP]M", re.IGNORECASE)


def looks_like_pasted_chat(text: str) -> bool:
    """True for a long message that is clearly a copied conversation (LinkedIn "sent the following message at ...", or
    several WhatsApp-style lines): other people's words, not his own writing."""
    if len(text) < 400:
        return False
    if len(_LINKEDIN.findall(text)) >= 2:
        return True
    lines = (line.translate(_MARKS) for line in text.split("\n"))
    return sum(1 for line in lines if _ANDROID.match(line) or _IOS.match(line)) >= 4
