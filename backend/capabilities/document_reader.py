"""
Document Intelligence & File-Type-Aware Reader for Cortex Agent.
Extracts readable text and structural context from various document types
(plain text, Markdown, JSON, CSV, PDF, DOCX, XLSX, PPTX) without returning
binary noise or failing on non-text encodings.
"""

from __future__ import annotations

import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class DocumentReadResult:
    ok: bool
    file_path: Path
    file_type: str
    content: str
    error: Optional[str] = None
    page_or_slide_count: int = 0
    metadata: Optional[dict[str, Any]] = None


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx",
    ".py", ".sh", ".bash", ".zsh", ".sql", ".log", ".ini", ".cfg",
    ".conf", ".env", ".toml", ".rst", ".c", ".cpp", ".h", ".swift",
    ".java", ".rs", ".go", ".rb", ".php"
}

# XML namespace mapping for Office Open XML
DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
PPTX_A_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
PPTX_P_NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


def is_binary_content(data: bytes) -> bool:
    """Checks if raw bytes appear to be non-text binary data."""
    if not data:
        return False
    if b"\x00" in data:
        return True
    # Count non-printable characters in initial chunk
    chunk = data[:1024]
    non_text = sum(1 for byte in chunk if byte < 32 and byte not in (9, 10, 13))
    return (non_text / len(chunk)) > 0.30


def read_document(file_path: str | Path, max_chars: int = 60000) -> DocumentReadResult:
    """
    Reads and extracts text from a file according to its format.
    Supports TXT, MD, PDF, PPTX, DOCX, XLSX, CSV, JSON.
    Gracefully explains unsupported, proprietary, or binary formats.
    """
    p = Path(file_path).expanduser().resolve()
    if not p.exists():
        return DocumentReadResult(
            ok=False,
            file_path=p,
            file_type="unknown",
            content="",
            error=f"File not found: {p}",
        )

    if p.is_dir():
        # Directory listing
        try:
            items = sorted(os.listdir(p))
            preview = items[:30]
            count_note = f" (showing first 30 of {len(items)})" if len(items) > 30 else ""
            content = f"Directory contents of '{p.name}'{count_note}:\n" + "\n".join(f"• {item}" for item in preview)
            return DocumentReadResult(
                ok=True,
                file_path=p,
                file_type="directory",
                content=content,
                metadata={"item_count": len(items)},
            )
        except Exception as e:
            return DocumentReadResult(
                ok=False,
                file_path=p,
                file_type="directory",
                content="",
                error=f"Cannot list directory '{p}': {e}",
            )

    file_size = p.stat().st_size
    if file_size == 0:
        return DocumentReadResult(
            ok=True,
            file_path=p,
            file_type="empty",
            content=f"Document '{p.name}' is empty (0 bytes).",
            metadata={"size_bytes": 0},
        )

    suffix = p.suffix.lower()

    # 1. Plain text and source code formats
    if suffix in TEXT_EXTENSIONS or suffix == "":
        return _read_text_file(p, max_chars=max_chars)

    # 2. PDF documents
    if suffix == ".pdf":
        return _read_pdf_file(p, max_chars=max_chars)

    # 3. PowerPoint presentations
    if suffix in (".pptx", ".potx", ".ppsx"):
        return _read_pptx_file(p, max_chars=max_chars)

    # 4. Word documents
    if suffix in (".docx", ".dotx"):
        return _read_docx_file(p, max_chars=max_chars)

    # 5. Excel spreadsheets
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx_file(p, max_chars=max_chars)

    # 6. Apple Keynote
    if suffix == ".key":
        return _handle_keynote_file(p)

    # 7. Images
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff"):
        return DocumentReadResult(
            ok=True,
            file_path=p,
            file_type="image",
            content=f"Image file '{p.name}' ({suffix.upper()}, {file_size:,} bytes). Use image inspection to examine visual details.",
            metadata={"size_bytes": file_size, "is_image": True},
        )

    # 8. Compressed archives
    if suffix in (".zip", ".tar", ".gz", ".bz2", ".xz", ".7z"):
        try:
            if suffix == ".zip" and zipfile.is_zipfile(p):
                with zipfile.ZipFile(p, "r") as z:
                    names = z.namelist()
                    content = f"Archive '{p.name}' contains {len(names)} files:\n" + "\n".join(f"• {n}" for n in names[:25])
                    if len(names) > 25:
                        content += f"\n... and {len(names) - 25} more items."
                    return DocumentReadResult(
                        ok=True,
                        file_path=p,
                        file_type="archive",
                        content=content,
                        metadata={"file_count": len(names)},
                    )
        except Exception:
            pass
        return DocumentReadResult(
            ok=True,
            file_path=p,
            file_type="archive",
            content=f"Compressed archive '{p.name}' ({file_size:,} bytes).",
        )

    # 9. Fallback: test if file contains readable UTF-8 text
    try:
        raw_head = p.read_bytes()[:2048]
        if not is_binary_content(raw_head):
            return _read_text_file(p, max_chars=max_chars)
    except Exception:
        pass

    return DocumentReadResult(
        ok=False,
        file_path=p,
        file_type="binary",
        content="",
        error=f"File '{p.name}' ({suffix}) is in an unsupported binary format and cannot be displayed as plain text.",
    )


def _read_text_file(path: Path, max_chars: int) -> DocumentReadResult:
    """Reads a text file with encoding fallback."""
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = path.read_text(encoding=enc)
            truncated = False
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[... truncated: showing first {max_chars:,} characters of {len(text):,} ...]"
                truncated = True
            return DocumentReadResult(
                ok=True,
                file_path=path,
                file_type="text",
                content=text,
                metadata={"encoding": enc, "truncated": truncated, "total_chars": len(text)},
            )
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return DocumentReadResult(
                ok=False,
                file_path=path,
                file_type="text",
                content="",
                error=f"Failed to read text file '{path.name}': {e}",
            )

    return DocumentReadResult(
        ok=False,
        file_path=path,
        file_type="text",
        content="",
        error=f"File '{path.name}' could not be decoded as text.",
    )


def _read_pdf_file(path: Path, max_chars: int) -> DocumentReadResult:
    """Extracts text page-by-page from a PDF document using pypdf."""
    try:
        import pypdf
    except ImportError:
        return DocumentReadResult(
            ok=False,
            file_path=path,
            file_type="pdf",
            content="",
            error="PDF reader dependency ('pypdf') is not installed in the current environment.",
        )

    try:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted:
            try:
                # Try empty password
                reader.decrypt("")
            except Exception:
                return DocumentReadResult(
                    ok=False,
                    file_path=path,
                    file_type="pdf",
                    content="",
                    error=f"PDF document '{path.name}' is password-protected and cannot be read without credentials.",
                )

        num_pages = len(reader.pages)
        if num_pages == 0:
            return DocumentReadResult(
                ok=True,
                file_path=path,
                file_type="pdf",
                content=f"PDF document '{path.name}' has 0 pages.",
                page_or_slide_count=0,
            )

        extracted_pages: list[str] = []
        total_chars = 0
        truncated = False

        for idx, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            clean_page_text = page_text.strip()
            if clean_page_text:
                header = f"--- Page {idx + 1} of {num_pages} ---"
                extracted_pages.append(f"{header}\n{clean_page_text}")
                total_chars += len(clean_page_text)
            if total_chars >= max_chars:
                extracted_pages.append(f"\n[... truncated: showing first {idx + 1} of {num_pages} pages ...]")
                truncated = True
                break

        if not extracted_pages:
            return DocumentReadResult(
                ok=True,
                file_path=path,
                file_type="pdf",
                content=f"PDF document '{path.name}' ({num_pages} pages) contains no extractable text (it may consist of scanned images).",
                page_or_slide_count=num_pages,
            )

        full_content = "\n\n".join(extracted_pages)
        return DocumentReadResult(
            ok=True,
            file_path=path,
            file_type="pdf",
            content=full_content,
            page_or_slide_count=num_pages,
            metadata={"num_pages": num_pages, "truncated": truncated},
        )
    except Exception as e:
        return DocumentReadResult(
            ok=False,
            file_path=path,
            file_type="pdf",
            content="",
            error=f"Error reading PDF '{path.name}': {e}",
        )


def _read_pptx_file(path: Path, max_chars: int) -> DocumentReadResult:
    """Extracts text slide-by-slide from an OOXML PowerPoint presentation (.pptx)."""
    if not zipfile.is_zipfile(path):
        return DocumentReadResult(
            ok=False,
            file_path=path,
            file_type="pptx",
            content="",
            error=f"File '{path.name}' is not a valid PPTX zip container.",
        )

    try:
        with zipfile.ZipFile(path, "r") as z:
            # Find all slides in order: ppt/slides/slide1.xml, slide2.xml, ...
            slide_entries = []
            for name in z.namelist():
                m = re.match(r"^ppt/slides/slide(\d+)\.xml$", name)
                if m:
                    slide_entries.append((int(m.group(1)), name))

            slide_entries.sort(key=lambda x: x[0])
            num_slides = len(slide_entries)

            if num_slides == 0:
                return DocumentReadResult(
                    ok=True,
                    file_path=path,
                    file_type="pptx",
                    content=f"Presentation '{path.name}' contains 0 slides.",
                    page_or_slide_count=0,
                )

            extracted_slides: list[str] = []
            total_chars = 0
            truncated = False

            for slide_num, slide_path in slide_entries:
                xml_data = z.read(slide_path)
                root = ET.fromstring(xml_data)

                # Extract text elements
                texts = []
                for node in root.iter():
                    if node.text and node.text.strip():
                        texts.append(node.text.strip())

                if texts:
                    slide_text = " ".join(texts)
                    extracted_slides.append(f"--- Slide {slide_num} of {num_slides} ---\n{slide_text}")
                    total_chars += len(slide_text)

                if total_chars >= max_chars:
                    extracted_slides.append(f"\n[... truncated: showing first {slide_num} of {num_slides} slides ...]")
                    truncated = True
                    break

            if not extracted_slides:
                return DocumentReadResult(
                    ok=True,
                    file_path=path,
                    file_type="pptx",
                    content=f"Presentation '{path.name}' ({num_slides} slides) contains no extractable text.",
                    page_or_slide_count=num_slides,
                )

            full_content = "\n\n".join(extracted_slides)
            return DocumentReadResult(
                ok=True,
                file_path=path,
                file_type="pptx",
                content=full_content,
                page_or_slide_count=num_slides,
                metadata={"num_slides": num_slides, "truncated": truncated},
            )
    except Exception as e:
        return DocumentReadResult(
            ok=False,
            file_path=path,
            file_type="pptx",
            content="",
            error=f"Error reading presentation '{path.name}': {e}",
        )


def _read_docx_file(path: Path, max_chars: int) -> DocumentReadResult:
    """Extracts text from an OOXML Word document (.docx)."""
    if not zipfile.is_zipfile(path):
        return DocumentReadResult(
            ok=False,
            file_path=path,
            file_type="docx",
            content="",
            error=f"File '{path.name}' is not a valid DOCX container.",
        )

    try:
        with zipfile.ZipFile(path, "r") as z:
            if "word/document.xml" not in z.namelist():
                return DocumentReadResult(
                    ok=False,
                    file_path=path,
                    file_type="docx",
                    content="",
                    error=f"Word document '{path.name}' missing document.xml.",
                )

            xml_data = z.read("word/document.xml")
            root = ET.fromstring(xml_data)

            paragraphs: list[str] = []
            for p_node in root.findall(".//w:p", DOCX_NS):
                texts = [node.text for node in p_node.findall(".//w:t", DOCX_NS) if node.text]
                if texts:
                    paragraphs.append("".join(texts).strip())

            full_text = "\n\n".join(p for p in paragraphs if p)
            if not full_text:
                full_text = f"Document '{path.name}' contains no readable paragraphs."

            if len(full_text) > max_chars:
                full_text = full_text[:max_chars] + f"\n\n[... truncated: showing first {max_chars:,} characters ...]"

            return DocumentReadResult(
                ok=True,
                file_path=path,
                file_type="docx",
                content=full_text,
                page_or_slide_count=len(paragraphs),
            )
    except Exception as e:
        return DocumentReadResult(
            ok=False,
            file_path=path,
            file_type="docx",
            content="",
            error=f"Error reading Word document '{path.name}': {e}",
        )


def _read_xlsx_file(path: Path, max_chars: int) -> DocumentReadResult:
    """Extracts text strings from an OOXML Excel spreadsheet (.xlsx)."""
    if not zipfile.is_zipfile(path):
        return DocumentReadResult(
            ok=False,
            file_path=path,
            file_type="xlsx",
            content="",
            error=f"File '{path.name}' is not a valid XLSX container.",
        )

    try:
        with zipfile.ZipFile(path, "r") as z:
            # Load shared strings if available
            shared_strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in ss_root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"):
                    if si.text:
                        shared_strings.append(si.text.strip())

            # Find sheets
            sheet_files = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            summary = [f"Spreadsheet '{path.name}' contains {len(sheet_files)} sheet(s)."]
            if shared_strings:
                preview = shared_strings[:50]
                summary.append("Extracted cell contents:\n" + "\n".join(f"• {s}" for s in preview))
                if len(shared_strings) > 50:
                    summary.append(f"... and {len(shared_strings) - 50} more entries.")

            return DocumentReadResult(
                ok=True,
                file_path=path,
                file_type="xlsx",
                content="\n\n".join(summary),
                page_or_slide_count=len(sheet_files),
            )
    except Exception as e:
        return DocumentReadResult(
            ok=False,
            file_path=path,
            file_type="xlsx",
            content="",
            error=f"Error reading spreadsheet '{path.name}': {e}",
        )


def _handle_keynote_file(path: Path) -> DocumentReadResult:
    """Handles Apple Keynote (.key) presentation files gracefully."""
    # Look for a sibling PPTX or PDF if available
    parent = path.parent
    base_name = path.stem
    pptx_sibling = parent / f"{base_name}.pptx"
    pdf_sibling = parent / f"{base_name}.pdf"

    sibling_note = ""
    if pptx_sibling.exists():
        sibling_note = f"\n\nNote: A matching PowerPoint version is available at '{pptx_sibling.name}'. You can say 'Read {pptx_sibling.name}' to extract its text."
    elif pdf_sibling.exists():
        sibling_note = f"\n\nNote: A matching PDF version is available at '{pdf_sibling.name}'. You can say 'Read {pdf_sibling.name}' to extract its text."

    return DocumentReadResult(
        ok=True,
        file_path=path,
        file_type="keynote",
        content=(
            f"Keynote presentation '{path.name}' is stored in Apple's proprietary Keynote bundle format. "
            f"You can open it directly in Keynote by saying 'Open {path.name}'."
            f"{sibling_note}"
        ),
    )
