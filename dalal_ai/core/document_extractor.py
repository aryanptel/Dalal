"""
Document text extraction for attachments.

Browser-free and UI-free by design: this module is pure CPU work, so it runs on
the Streamlit thread at upload time rather than on the single Playwright worker
thread, and its result is cached so that sending the same file to five swarm
tabs parses it once.

It exists because the previous fallback read every attachment as
``open(path, "r", encoding="utf-8", errors="replace")``.  That is right for a
.txt and wrong for everything else: a PDF is a binary container and a .docx is a
ZIP, so both produced mojibake that was then fenced in a code block and pasted
into the model as though it were the document.

Supported: PDF (via pypdf), DOCX (stdlib only), and the plain-text family.
Anything else is refused with a usable message rather than mangled.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from xml.etree import ElementTree

from utils.logger import logger

# Bumped when extraction output changes, so stale sidecars are ignored.
EXTRACTOR_VERSION = 1

# How an attachment should reach the model.
KIND_NATIVE_ONLY = "native_only"          # images: upload or nothing
KIND_NATIVE_PREFERRED = "native_preferred"  # PDF/DOCX: upload, text as fallback
KIND_INLINE_PREFERRED = "inline_preferred"  # text/code: paste it, uploads add nothing

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".tex", ".bib", ".log", ".ini", ".cfg", ".toml",
    ".py", ".c", ".h", ".cpp", ".hpp", ".cc", ".m", ".jl", ".f", ".f90", ".for",
    ".java", ".js", ".ts", ".kt", ".rs", ".go", ".sh", ".bat", ".ps1", ".sql",
    ".ino", ".mat", ".r", ".swift", ".pl", ".lua", ".vim", ".dockerfile",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}

# Tried in order.  cp1252 before latin-1 because Windows editors emit smart
# quotes and degree signs that latin-1 silently maps to the wrong glyphs.
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

# A page yielding fewer than this many characters is treated as having no text
# layer, which is how a scanned PDF presents itself.
SCANNED_PAGE_CHAR_THRESHOLD = 10
SCANNED_PAGE_FRACTION = 0.8

PAGE_MARKER = "<!-- page {number} -->"
_PAGE_MARKER_RE = re.compile(r"^<!-- page (\d+) -->$", re.MULTILINE)


@dataclass
class ExtractedDocument:
    """The result of reading one attachment."""

    path: str
    name: str
    format: str                       # "pdf" | "docx" | "text" | "image" | "binary"
    kind: str                         # one of the KIND_* constants
    text: str = ""
    page_count: int = 0               # 0 when the format has no pages
    pages_included: list[int] = field(default_factory=list)
    char_count: int = 0
    truncated: bool = False
    extractable: bool = True          # False => there is no text to inline
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    def page_span(self) -> str:
        """Human phrasing of which pages made it in, e.g. 'pages 1-15 of 82'."""
        if not self.page_count:
            return ""
        if not self.pages_included:
            return f"no pages of {self.page_count}"
        first, last = self.pages_included[0], self.pages_included[-1]
        contiguous = self.pages_included == list(range(first, last + 1))
        if contiguous and len(self.pages_included) == self.page_count:
            return f"all {self.page_count} pages"
        if contiguous:
            return f"pages {first}-{last} of {self.page_count}"
        return f"{len(self.pages_included)} of {self.page_count} pages"

    def summary(self) -> str:
        """One line for the UI or the CLI."""
        if self.error:
            return f"{self.name}: {self.error}"
        parts = [self.format.upper()]
        if self.page_count:
            parts.append(self.page_span())
        parts.append(f"{self.char_count:,} chars")
        if self.truncated:
            parts.append("truncated")
        return f"{self.name} — {', '.join(parts)}"

    def as_prompt_block(self) -> str:
        """The text as it is pasted into a prompt."""
        if not self.has_text:
            return ""
        header = f"--- Attached file: {self.name}"
        span = self.page_span()
        if span:
            header += f" ({span})"
        header += " ---"
        note = ""
        if self.truncated:
            note = (
                f"\n[Only part of this document is included: {span or 'truncated'}.]"
            )
        return f"\n\n{header}{note}\n```\n{self.text}\n```"


# ── Format detection ─────────────────────────────────────────────────────────

def _magic_format(path: str) -> Optional[str]:
    """Identify a file by its leading bytes, which cannot be renamed away."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return None

    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        # Any OOXML/ODF/JAR/ZIP. Narrowed by inspecting the archive below.
        return "zip"
    if head.startswith(b"\x89PNG") or head[:3] == b"\xff\xd8\xff" or head[:6] in (b"GIF87a", b"GIF89a"):
        return "image"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"      # legacy .doc/.xls
    return None


def _zip_subtype(path: str) -> str:
    """Tell a .docx from any other ZIP by what is inside it."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except (zipfile.BadZipFile, OSError):
        return "binary"
    if "word/document.xml" in names:
        return "docx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    return "binary"


def detect_format(path: str) -> str:
    """Return 'pdf' | 'docx' | 'text' | 'image' | 'binary'."""
    magic = _magic_format(path)
    if magic == "pdf":
        return "pdf"
    if magic == "image":
        return "image"
    if magic == "zip":
        return _zip_subtype(path)
    if magic == "ole":
        return "binary"

    extension = os.path.splitext(path)[1].lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in TEXT_EXTENSIONS:
        return "text"

    # No magic and an unknown extension: accept it as text only if it decodes
    # cleanly and has no NUL bytes.
    try:
        with open(path, "rb") as fh:
            sample = fh.read(8192)
    except OSError:
        return "binary"
    if b"\x00" in sample:
        return "binary"
    for encoding in TEXT_ENCODINGS:
        try:
            sample.decode(encoding)
            return "text"
        except (UnicodeDecodeError, LookupError):
            continue
    return "binary"


# ── PDF ──────────────────────────────────────────────────────────────────────

def _extract_pdf(path: str, doc: ExtractedDocument, page_range: Optional[tuple[int, int]]) -> None:
    try:
        from pypdf import PdfReader
    except ImportError:
        doc.extractable = False
        doc.error = (
            "PDF text extraction needs the 'pypdf' package, which is not "
            "installed. The file can still be uploaded natively."
        )
        return

    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            # Many PDFs are encrypted with an empty owner password purely to
            # set permissions; those decrypt silently.
            try:
                if reader.decrypt("") == 0:
                    raise ValueError("password required")
            except Exception:
                doc.extractable = False
                doc.error = (
                    "This PDF is password-protected, so its text cannot be read. "
                    "Native upload may still work."
                )
                return

        total = len(reader.pages)
        doc.page_count = total
        if total == 0:
            doc.extractable = False
            doc.error = "This PDF has no pages."
            return

        first, last = _resolve_range(page_range, total)
        empty_pages = 0
        chunks: list[str] = []
        for number in range(first, last + 1):
            try:
                page_text = reader.pages[number - 1].extract_text() or ""
            except Exception as exc:
                page_text = ""
                logger.warning(f"pypdf failed on page {number} of {path}: {exc}")
            page_text = page_text.strip()
            if len(page_text) < SCANNED_PAGE_CHAR_THRESHOLD:
                empty_pages += 1
            chunks.append(f"{PAGE_MARKER.format(number=number)}\n{page_text}")
            doc.pages_included.append(number)

        doc.text = "\n\n".join(chunks).strip()

        considered = len(doc.pages_included)
        if considered and empty_pages >= SCANNED_PAGE_FRACTION * considered:
            doc.warnings.append(
                "This PDF appears to be scanned — it has little or no text layer. "
                "Native upload may still work if the platform runs OCR."
            )
    except Exception as exc:
        doc.extractable = False
        doc.error = f"Could not read this PDF: {exc}"


def _resolve_range(page_range: Optional[tuple[int, int]], total: int) -> tuple[int, int]:
    """Clamp a 1-based inclusive page range onto a document of *total* pages."""
    if not page_range:
        return 1, total
    first, last = page_range
    first = max(1, min(int(first), total))
    last = max(first, min(int(last), total))
    return first, last


# ── DOCX, without pulling in lxml ────────────────────────────────────────────
#
# python-docx would be the obvious choice, but it depends on lxml — a compiled
# extension that adds several MB to the frozen build and is exactly the kind of
# dependency that caused this project's packaging trouble.  A .docx is a ZIP of
# XML, so the stdlib is enough.

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    """Concatenate the runs of one paragraph, honouring breaks and tabs."""
    pieces: list[str] = []
    for node in paragraph.iter():
        tag = node.tag
        if tag == f"{_W_NS}t":
            pieces.append(node.text or "")
        elif tag == f"{_W_NS}tab":
            pieces.append("\t")
        elif tag in (f"{_W_NS}br", f"{_W_NS}cr"):
            pieces.append("\n")
    return "".join(pieces).strip()


def _docx_heading_prefix(paragraph: ElementTree.Element) -> str:
    """Render Word heading styles as Markdown hashes."""
    style = paragraph.find(f"{_W_NS}pPr/{_W_NS}pStyle")
    if style is None:
        return ""
    name = (style.get(f"{_W_NS}val") or "").lower()
    match = re.match(r"heading(\d)", name)
    if match:
        return "#" * min(int(match.group(1)), 6) + " "
    if name == "title":
        return "# "
    return ""


def _docx_table_markdown(table: ElementTree.Element) -> str:
    """Render a w:tbl as a Markdown table."""
    rows: list[list[str]] = []
    for row in table.findall(f"{_W_NS}tr"):
        cells = []
        for cell in row.findall(f"{_W_NS}tc"):
            cell_text = " ".join(
                _docx_paragraph_text(p) for p in cell.findall(f"{_W_NS}p")
            ).strip()
            cells.append(cell_text.replace("|", "\\|").replace("\n", " "))
        if cells:
            rows.append(cells)
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |",
             "| " + " | ".join(["---"] * width) + " |"]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _extract_docx(path: str, doc: ExtractedDocument) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        doc.extractable = False
        doc.error = f"Could not read this .docx: {exc}"
        return

    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        doc.extractable = False
        doc.error = f"This .docx contains malformed XML: {exc}"
        return

    body = root.find(f"{_W_NS}body")
    if body is None:
        doc.extractable = False
        doc.error = "This .docx has no document body."
        return

    blocks: list[str] = []
    # Direct children only, so paragraphs inside a table are not emitted twice.
    for element in body:
        if element.tag == f"{_W_NS}p":
            text = _docx_paragraph_text(element)
            if text:
                blocks.append(_docx_heading_prefix(element) + text)
        elif element.tag == f"{_W_NS}tbl":
            table = _docx_table_markdown(element)
            if table:
                blocks.append(table)

    doc.text = "\n\n".join(blocks).strip()
    if not doc.text:
        doc.warnings.append(
            "No text found in this .docx — it may contain only images or text boxes."
        )


# ── Plain text ───────────────────────────────────────────────────────────────

def _extract_text_file(path: str, doc: ExtractedDocument) -> None:
    """
    Read a text file by trying encodings in order.

    The old code passed ``errors="replace"``, which never fails and therefore
    never tells you it destroyed something: every smart quote and degree sign in
    a cp1252 file became U+FFFD before the model ever saw it.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        doc.extractable = False
        doc.error = f"Could not read this file: {exc}"
        return

    for encoding in TEXT_ENCODINGS:
        try:
            doc.text = raw.decode(encoding).strip()
            if encoding not in ("utf-8", "utf-8-sig"):
                doc.warnings.append(f"Decoded as {encoding} (not valid UTF-8).")
            return
        except (UnicodeDecodeError, LookupError):
            continue

    doc.text = raw.decode("utf-8", errors="replace").strip()
    doc.warnings.append(
        "Encoding could not be determined; some characters may be wrong."
    )


# ── Entry point ──────────────────────────────────────────────────────────────

def extract_document(
    path: str,
    page_range: Optional[tuple[int, int]] = None,
    max_chars: Optional[int] = None,
) -> ExtractedDocument:
    """
    Read *path* and return its text plus what had to be left out.

    Parameters
    ----------
    page_range : (first, last), 1-based inclusive, PDFs only.
    max_chars : hard ceiling applied after extraction.  Truncation happens on a
        page boundary where the format has pages, so the caller can always say
        which pages were actually sent.
    """
    name = os.path.basename(path)
    if not os.path.isfile(path):
        return ExtractedDocument(
            path=path, name=name, format="binary", kind=KIND_NATIVE_ONLY,
            extractable=False, error="File not found.",
        )

    fmt = detect_format(path)
    kind = {
        "pdf": KIND_NATIVE_PREFERRED,
        "docx": KIND_NATIVE_PREFERRED,
        "text": KIND_INLINE_PREFERRED,
        "image": KIND_NATIVE_ONLY,
    }.get(fmt, KIND_NATIVE_ONLY)

    doc = ExtractedDocument(path=path, name=name, format=fmt, kind=kind)

    if fmt == "pdf":
        _extract_pdf(path, doc, page_range)
    elif fmt == "docx":
        _extract_docx(path, doc)
    elif fmt == "text":
        _extract_text_file(path, doc)
    elif fmt == "image":
        doc.extractable = False
        doc.error = (
            "Images carry no text to inline. This one is uploaded natively, so "
            "it only reaches models whose upload works and that can see images."
        )
    else:
        doc.extractable = False
        doc.error = (
            f"'{name}' is a binary format this tool cannot read as text. It is "
            "uploaded natively; if that fails, nothing is sent rather than "
            "pasting unreadable bytes into the prompt."
        )

    if max_chars is not None and max_chars > 0 and len(doc.text) > max_chars:
        _truncate(doc, max_chars)

    doc.char_count = len(doc.text)
    return doc


def _truncate(doc: ExtractedDocument, max_chars: int) -> None:
    """Cut to *max_chars*, on a page boundary when the format has pages."""
    if doc.pages_included:
        kept_pages: list[int] = []
        kept_chunks: list[str] = []
        used = 0
        for chunk in doc.text.split("\n\n"):
            match = _PAGE_MARKER_RE.match(chunk.split("\n", 1)[0])
            addition = len(chunk) + 2
            if used + addition > max_chars and kept_chunks:
                break
            kept_chunks.append(chunk)
            used += addition
            if match:
                kept_pages.append(int(match.group(1)))
        if kept_chunks:
            doc.text = "\n\n".join(kept_chunks).strip()
            doc.pages_included = kept_pages or doc.pages_included[:1]
            doc.truncated = True
            return

    doc.text = doc.text[:max_chars].rstrip()
    doc.truncated = True


# ── Caching ──────────────────────────────────────────────────────────────────
#
# Swarm mode sends one attachment to several tabs.  Without a cache the same
# 300-page PDF is parsed once per tab.

def _sidecar_path(path: str) -> str:
    return f"{path}.extract.json"


def extract_document_cached(
    path: str,
    page_range: Optional[tuple[int, int]] = None,
    max_chars: Optional[int] = None,
    use_cache: bool = True,
) -> ExtractedDocument:
    """:func:`extract_document`, memoised to a sidecar JSON next to the file."""
    if not use_cache or page_range is not None:
        # A page range is a one-off view; only the full extraction is cached.
        return extract_document(path, page_range=page_range, max_chars=max_chars)

    sidecar = _sidecar_path(path)
    try:
        if os.path.isfile(sidecar) and os.path.getmtime(sidecar) >= os.path.getmtime(path):
            with open(sidecar, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if payload.get("extractor_version") == EXTRACTOR_VERSION:
                payload.pop("extractor_version", None)
                doc = ExtractedDocument(**payload)
                if max_chars is not None and max_chars > 0 and len(doc.text) > max_chars:
                    _truncate(doc, max_chars)
                    doc.char_count = len(doc.text)
                return doc
    except (OSError, ValueError, TypeError) as exc:
        logger.warning(f"Ignoring unusable extraction cache {sidecar}: {exc}")

    # Cache the untruncated result, then apply the caller's ceiling to a copy.
    full = extract_document(path, page_range=None, max_chars=None)
    try:
        payload = asdict(full)
        payload["extractor_version"] = EXTRACTOR_VERSION
        tmp_path = f"{sidecar}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp_path, sidecar)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning(f"Could not cache extraction for {path}: {exc}")

    if max_chars is not None and max_chars > 0 and len(full.text) > max_chars:
        _truncate(full, max_chars)
        full.char_count = len(full.text)
    return full


def attachment_digest(path: str, chunk_size: int = 1 << 20) -> str:
    """Short content hash, used to name stored attachments without collisions."""
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()[:10]


def safe_attachment_name(name: str) -> str:
    """Strip path separators and characters Windows rejects in filenames."""
    name = os.path.basename(name or "attachment")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    return name[:120] or "attachment"


def build_prompt_suffix(documents: list[ExtractedDocument]) -> str:
    """Join the inlinable documents into one block to append to a prompt."""
    blocks = [doc.as_prompt_block() for doc in documents if doc.has_text]
    return "".join(blocks)


# ── Send planning ────────────────────────────────────────────────────────────

@dataclass
class AttachmentPlan:
    """How a set of attachments should be delivered to one platform."""

    documents: list[ExtractedDocument] = field(default_factory=list)
    native_paths: list[str] = field(default_factory=list)
    inline_suffix: str = ""      # always appended to the prompt
    fallback_text: str = ""      # appended only if native upload fails
    notes: list[str] = field(default_factory=list)

    @property
    def has_attachments(self) -> bool:
        return bool(self.native_paths or self.inline_suffix)


def prepare_attachments(
    paths: Optional[list[str]],
    max_chars: Optional[int] = None,
    page_ranges: Optional[dict[str, tuple[int, int]]] = None,
    use_cache: bool = True,
) -> AttachmentPlan:
    """
    Decide how each attachment reaches the model.

    Text and code are pasted inline unconditionally: an upload round-trip buys
    nothing for content the model can simply read, and inline text is the only
    form that survives a cross-model context switch.  PDFs and .docx files go
    up natively first, because the platforms parse their own uploads better than
    a flat text dump, with the extracted text held in reserve for when that
    fails.  Images can only go natively, so if the upload fails they are
    reported rather than turned into bytes in the prompt.
    """
    plan = AttachmentPlan()
    if not paths:
        return plan

    ranges = page_ranges or {}
    seen: set[str] = set()
    inline_docs: list[ExtractedDocument] = []
    fallback_docs: list[ExtractedDocument] = []

    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        if not os.path.isfile(path):
            plan.notes.append(f"{os.path.basename(path)}: file is no longer on disk.")
            continue

        doc = extract_document_cached(
            path,
            page_range=ranges.get(path),
            max_chars=max_chars,
            use_cache=use_cache,
        )
        plan.documents.append(doc)

        if doc.kind == KIND_INLINE_PREFERRED:
            if doc.has_text:
                inline_docs.append(doc)
            else:
                plan.native_paths.append(path)
        else:
            plan.native_paths.append(path)
            if doc.kind == KIND_NATIVE_PREFERRED and doc.has_text:
                fallback_docs.append(doc)

        if doc.error:
            plan.notes.append(f"{doc.name}: {doc.error}")
        for warning in doc.warnings:
            plan.notes.append(f"{doc.name}: {warning}")
        if doc.truncated:
            plan.notes.append(f"{doc.name}: sending {doc.page_span() or 'a truncated excerpt'}.")

    plan.inline_suffix = build_prompt_suffix(inline_docs)
    plan.fallback_text = build_prompt_suffix(fallback_docs)
    return plan
