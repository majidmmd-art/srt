"""تبدیل محتوای فایل SRT به فایل Word (docx) راست‌چین."""
import io
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt

FONT_NAME = "Vazirmatn"  # اگر روی سیستم نصب نباشد، ورد فونت جایگزین نشان می‌دهد
TIME_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)
TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")  # تگ‌های <i> و {\an8}


def decode_bytes(data: bytes) -> str:
    """فایل‌های SRT فارسی معمولاً UTF-8 یا Windows-1256 هستند."""
    for enc in ("utf-8-sig", "utf-16", "cp1256"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and "-->" not in text:
                continue
            return text
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def parse_srt(text: str):
    """خروجی: لیست (شروع، پایان، متن)"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("ي", "ی").replace("ك", "ک")  # ی و ک عربی ← فارسی
    entries = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            m = TIME_RE.search(line)
            if m:
                body = " ".join(TAG_RE.sub("", l) for l in lines[i + 1:]).strip()
                if body:
                    start = m.group(1).replace(".", ",").split(",")[0]
                    end = m.group(2).replace(".", ",").split(",")[0]
                    entries.append((start, end, body))
                break
    return entries


def _rtl(paragraph, size=12, bold=False, text=""):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    pPr.insert(0, bidi)
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = FONT_NAME
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    rFonts.set(qn("w:cs"), FONT_NAME)
    rPr.append(OxmlElement("w:rtl"))
    szCs = OxmlElement("w:szCs")
    szCs.set(qn("w:val"), str(size * 2))
    rPr.append(szCs)
    if bold:
        rPr.append(OxmlElement("w:bCs"))
    return run


def build_docx(entries, title: str, with_times: bool) -> bytes:
    doc = Document()
    _rtl(doc.add_paragraph(), size=16, bold=True, text=title)

    if with_times:
        for start, end, body in entries:
            p = doc.add_paragraph()
            _rtl(p, size=9, text=f"{start} ← {end}\n")
            _rtl(p, size=12, text=body)
    else:
        # چند زیرنویس پشت سر هم را به یک پاراگراف تبدیل می‌کنیم
        para, count = [], 0
        for _, _, body in entries:
            para.append(body)
            count += 1
            if count >= 6 and body.rstrip().endswith((".", "؟", "?", "!", "…")):
                _rtl(doc.add_paragraph(), text=" ".join(para))
                para, count = [], 0
        if para:
            _rtl(doc.add_paragraph(), text=" ".join(para))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def srt_bytes_to_docx(data: bytes, title: str, with_times: bool) -> tuple[bytes, int]:
    entries = parse_srt(decode_bytes(data))
    return build_docx(entries, title, with_times), len(entries)
