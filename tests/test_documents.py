import io
import zipfile
from datetime import datetime

import pytest

from secondbrain.documents import (CHUNK_CHARS, MAX_UPLOAD_BYTES, SEGMENT_POINTS, DocumentError, Message, build_segments,
                                   parse_whatsapp, read_upload)

ANDROID = """12/03/2024, 10:15 - Messages and calls are end-to-end encrypted. No one outside of this chat can read them.
12/03/2024, 10:16 - Rahul Sharma: Hey Daksh, saw your message about DevOps
12/03/2024, 10:17 - Daksh: Hi! I want to build an infra tool
and sell it to startups
12/03/2024, 10:18 - Rahul Sharma: <Media omitted>
13/03/2024, 09:00 - Rahul Sharma: First find who has the pain.
"""

IOS = """‎[12/03/24, 10:16:05] Rahul Sharma: first line
[12/03/24, 10:17:10 PM] Daksh: second line
"""


# --- WhatsApp parsing --------------------------------------------------------------------------------------------

def test_android_export_skips_system_and_media_lines_and_joins_multiline_messages():
    messages = parse_whatsapp(ANDROID)
    assert [(m.author, m.text) for m in messages] == [
        ("Rahul Sharma", "Hey Daksh, saw your message about DevOps"),
        ("Daksh", "Hi! I want to build an infra tool\nand sell it to startups"),
        ("Rahul Sharma", "First find who has the pain."),
    ]
    assert messages[0].when == datetime(2024, 3, 12, 10, 16) and messages[2].when == datetime(2024, 3, 13, 9, 0)


def test_ios_export_with_brackets_seconds_and_invisible_marks():
    messages = parse_whatsapp(IOS)
    assert [m.author for m in messages] == ["Rahul Sharma", "Daksh"] and messages[1].when.hour == 22


def test_month_first_dates_are_detected_when_a_first_field_cannot_be_a_day():
    text = "03/13/2024, 10:00 - Amy: hello there\n03/14/2024, 11:00 - Bo: hi again\n"
    assert [m.when.day for m in parse_whatsapp(text)] == [13, 14]


def test_plain_text_is_not_whatsapp():
    assert parse_whatsapp("Just some notes.\nNothing like a chat export here.\n") == []


# --- uploads: txt, md, zip ------------------------------------------------------------------------------------------

def test_txt_and_markdown_uploads_are_read_as_text_with_encoding_fallbacks():
    up = read_upload("notes.md", "# Title\n\nSome founder advice about pricing.".encode("utf-8-sig"))
    assert up.kind == "markdown" and up.text.startswith("# Title") and up.messages == []
    assert read_upload("a.txt", "café plan".encode("cp1252")).text == "café plan"
    assert read_upload("b.txt", "wide text".encode("utf-16")).text == "wide text"


def test_a_txt_file_that_is_a_whatsapp_export_is_recognised():
    up = read_upload("WhatsApp Chat with Rahul.txt", ANDROID.encode("utf-8"))
    assert up.kind == "whatsapp" and len(up.messages) == 3 and up.name == "WhatsApp Chat with Rahul.txt"


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_whatsapp_zip_uses_the_chat_text_and_ignores_media_and_junk():
    data = zip_bytes({"__MACOSX/._chat.txt": b"junk", "IMG-001.jpg": b"\xff\xd8\xff", "WhatsApp Chat with Rahul.txt": ANDROID.encode()})
    up = read_upload("export.zip", data)
    assert up.kind == "whatsapp" and len(up.messages) == 3


def test_zip_problems_are_refused_with_clear_errors():
    with pytest.raises(DocumentError, match="no text"):
        read_upload("x.zip", zip_bytes({"IMG.jpg": b"\xff\xd8"}))
    with pytest.raises(DocumentError, match="too large"):
        read_upload("bomb.zip", zip_bytes({"chat.txt": b"a" * (45 * 1024 * 1024)}))
    with pytest.raises(DocumentError, match="not a valid"):
        read_upload("broken.zip", b"this is not a zip")
    with pytest.raises(DocumentError, match="nested"):
        read_upload("n.zip", zip_bytes({"inner.zip": zip_bytes({"chat.txt": b"x"})}))


def test_unsupported_and_oversized_uploads_are_refused():
    with pytest.raises(DocumentError, match="unsupported"):
        read_upload("photo.jpg", b"\xff\xd8\xff")
    with pytest.raises(DocumentError, match="too large"):
        read_upload("big.txt", b"a" * (MAX_UPLOAD_BYTES + 1))
    with pytest.raises(DocumentError, match="empty"):
        read_upload("empty.txt", b"   \n")


# --- segments: what gets stored ----------------------------------------------------------------------------------------

def test_whatsapp_chunks_keep_attribution_with_roles_and_a_date_header():
    messages = parse_whatsapp(ANDROID)
    segments = build_segments(read_upload("c.txt", ANDROID.encode()), labels={"Daksh": "Daksh", "Rahul Sharma": "Rahul (founder)"})
    text = "\n".join(p for seg in segments for p in seg)
    assert "[12 Mar 2024]" in text and "Rahul (founder): Hey Daksh, saw your message about DevOps" in text
    assert "Daksh: Hi! I want to build an infra tool" in text and "[13 Mar 2024]" in text
    assert all(len(p) <= CHUNK_CHARS + 120 for seg in segments for p in seg)          # header and labels add a little


def test_a_very_long_message_is_split_without_losing_who_said_it():
    long = "A" * 400 + ". " + "B" * 400 + ". " + "C" * 400 + ". " + "D" * 400 + "."
    chat = f"12/03/2024, 10:16 - Rahul Sharma: {long}\n12/03/2024, 10:17 - Daksh: ok\n"
    segments = build_segments(read_upload("c.txt", chat.encode()), labels={"Rahul Sharma": "Rahul (founder)"})
    points = [p for seg in segments for p in seg]
    assert sum(p.count("Rahul (founder):") for p in points) >= 2          # split into several parts, each still attributed
    assert all(len(p) <= CHUNK_CHARS + 40 for p in points)


def test_segments_hold_a_bounded_number_of_points_and_text_docs_split_by_paragraph():
    paragraphs = "\n\n".join(f"Paragraph {i} about pricing and customers. " * 12 for i in range(60))
    segments = build_segments(read_upload("big.md", paragraphs.encode()), labels={})
    assert len(segments) >= 2 and all(0 < len(seg) <= SEGMENT_POINTS for seg in segments)
    assert all(len(p) <= CHUNK_CHARS + 20 for seg in segments for p in seg)


def test_secrets_are_redacted_before_anything_is_stored():
    up = read_upload("n.txt", b"my key is sk-ant-api03-abcdefghijklmnopqrstuvwx and more words here for the note")
    assert "sk-ant" not in up.text


# --- PDF ----------------------------------------------------------------------------------------------------------------

def make_pdf(pages: list[str]) -> bytes:
    """A minimal real PDF with one line of text per page (Helvetica), built by hand so no PDF library is needed to test."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    font_ref = 3 + 2 * n
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font_ref} 0 R >> >> >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_pdf_text_is_extracted_page_by_page():
    up = read_upload("advice.pdf", make_pdf(["Find the pain before you build", "Charge early for the result"]))
    assert up.kind == "pdf" and up.pages == 2
    assert "Find the pain before you build" in up.text and "Charge early for the result" in up.text
    assert up.text.index("Find the pain") < up.text.index("Charge early")


def test_pdf_problems_get_clear_errors():
    with pytest.raises(DocumentError, match="not a valid PDF"):
        read_upload("x.pdf", b"%PDF-1.4 this is garbage")
    with pytest.raises(DocumentError, match="no readable text"):
        read_upload("scan.pdf", make_pdf([""]))                      # a page without text, like a scanned image
    with pytest.raises(DocumentError, match="too many pages"):
        read_upload("long.pdf", make_pdf(["page"] * 301))


def test_pdf_secrets_are_redacted_and_the_pdf_is_chunked_like_text():
    up = read_upload("n.pdf", make_pdf(["key sk-ant-api03-abcdefghijklmnopqrstuvwx and a note about pricing for founders"]))
    assert "sk-ant" not in up.text
    segments = build_segments(up, labels={})
    assert segments and all(len(p) <= CHUNK_CHARS + 20 for seg in segments for p in seg)
