from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re
import mimetypes
import tempfile
from urllib.parse import urlparse

import requests
from docling.document_converter import DocumentConverter  # Docling API

# -----------------------------
# Sentence splitting & aliases
# -----------------------------
# Simple sentence splitter: look for punctuation followed by whitespace and a capital or '('.
# You can swap to spaCy/scispaCy later if needed.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

# Normalize common section titles to a small canonical set
DEFAULT_SECTION_ALIASES = {
    "abstract": {"abstract"},
    "introduction": {"introduction", "background"},
    "methods": {"methods", "materials and methods", "method", "patients and methods"},
    "results": {"results"},
    "discussion": {"discussion", "conclusions", "conclusion"},
}

@dataclass
class Section:
    """Holds a single section's content and absolute offsets into the full document text."""
    name: str
    text: str
    start_offset: int
    end_offset: int
    sentences: List[Dict[str, Any]]  # [{"text": "...", "start": int, "end": int}]

# -----------------------------
# Helpers
# -----------------------------
def _split_markdown_into_sections(md: str) -> List[Tuple[str, str]]:
    """
    Split Markdown on ATX headings (#, ##, ###, ...).
    Returns a list of (section_name, section_text).
    """
    lines = md.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    current_name = "Document"
    current_buf: List[str] = []

    for ln in lines:
        if ln.strip().startswith("#"):  # heading line
            if current_buf:
                sections.append((current_name, current_buf))
                current_buf = []
            # strip leading #'s and whitespace to get the heading text
            current_name = re.sub(r"^#+\s*", "", ln).strip() or "Section"
        else:
            current_buf.append(ln)

    if current_buf:
        sections.append((current_name, current_buf))

    # Normalize into (name, text) tuples and drop empty text sections
    out: List[Tuple[str, str]] = []
    for name, buf in sections:
        text = "\n".join(buf).strip()
        if text:
            out.append((name, text))
    return out

def _normalize_section_name(raw: str) -> str:
    """Map raw section headers to canonical labels when possible."""
    base = raw.lower().strip(" :")
    for canon, aliases in DEFAULT_SECTION_ALIASES.items():
        if base in aliases:
            return canon
    return raw.strip()

def _sentences_with_offsets(text: str, base_offset: int) -> List[Dict[str, Any]]:
    """
    Split a section's text into sentences and compute ABSOLUTE start/end offsets
    by adding base_offset (the index where the section text starts within full_text).
    """
    sentences: List[Dict[str, Any]] = []
    if not text:
        return sentences

    spans: List[Tuple[int, int]] = []
    last = 0
    for m in _SENT_SPLIT.finditer(text):
        spans.append((last, m.start()))
        last = m.end()
    spans.append((last, len(text)))  # tail

    for s, e in spans:
        frag = text[s:e].strip()
        if not frag:
            continue
        sentences.append({"text": frag, "start": base_offset + s, "end": base_offset + e})
    return sentences

def _download_if_url(source: str | Path) -> tuple[str, Optional[str]]:
    """
    If source is an http(s) URL, download to a temp file and return (local_path, content_type).
    Otherwise return (path_str, None).
    """
    s = str(source)
    parsed = urlparse(s)
    if parsed.scheme in {"http", "https"}:
        r = requests.get(s, timeout=60)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        ext = mimetypes.guess_extension(ct) or ".bin"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.write(r.content)
        tmp.flush()
        tmp.close()
        return tmp.name, ct
    return s, None

def _clean_html_to_text(local_html_path: str) -> str:
    """
    Quick HTML→text extraction path using trafilatura (install if missing).
    For better structure (headings/tables), consider rendering HTML→PDF then run Docling.
    """
    try:
        import trafilatura
    except ImportError as e:
        raise RuntimeError(
            "Please install trafilatura to parse HTML pages: pip install trafilatura"
        ) from e
    raw = Path(local_html_path).read_text(encoding="utf-8", errors="ignore")
    clean = trafilatura.extract(raw) or ""
    return clean

# -----------------------------
# Public API
# -----------------------------
def parse_document(
    source: str | Path,
    *,
    source_id: Optional[str] = None,
    save_intermediate_dir: Optional[Path] = Path("data/interim"),
    export_markdown: bool = True,
    export_json: bool = True,
) -> Dict[str, Any]:
    """
    Convert a PDF/URL into sectioned text + sentence spans + metadata.

    Output schema:
      {
        "full_text": "...",
        "sections": [
          {
            "name": "results",
            "text": "...",
            "start_offset": 1234,
            "end_offset": 2345,
            "sentences": [{"text":"...", "start": 1290, "end": 1320}, ...]
          },
          ...
        ],
        "metadata": {"source_id","title","year","origin"}
      }
    """
    src_in = str(source)
    local_src, content_type = _download_if_url(src_in)
    sid = source_id or Path(local_src if local_src else src_in).stem

    # HTML path (quick): extract readable text and wrap as a single "Document" section.
    if content_type and "text/html" in content_type:
        clean = _clean_html_to_text(local_src)
        sentences = _sentences_with_offsets(clean, 0)
        return {
            "full_text": clean,
            "sections": [{
                "name": "Document",
                "text": clean,
                "start_offset": 0,
                "end_offset": len(clean),
                "sentences": sentences
            }],
            "metadata": {"source_id": sid, "title": sid, "year": None, "origin": src_in},
        }

    # 1) Convert with Docling (PDFs and similar doc types)
    converter = DocumentConverter()  # basic pipeline (enable OCR later if needed)
    doc = converter.convert(local_src).document

    # 2) Export text/markdown (public API)
    md = doc.export_to_markdown()
    full_text = doc.export_to_text()

    # 3) Save raw artifacts for debugging/repro (optional)
    if save_intermediate_dir:
        save_dir = Path(save_intermediate_dir) / "docling" / sid
        save_dir.mkdir(parents=True, exist_ok=True)
        if export_markdown:
            (save_dir / "document.md").write_text(md, encoding="utf-8")
        if export_json:
            # Correct: pass a filename to save_as_json
            doc.save_as_json(str(save_dir / "document.json"))
            # OR, if you want a string to manipulate in code:
            # import json
            # (save_dir / "document.json").write_text(
            #     json.dumps(doc.export_to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            # )


    # 4) Split by headings → sections; compute absolute offsets in full_text
    raw_sections = _split_markdown_into_sections(md)
    sections: List[Section] = []
    for name, text in raw_sections:
        norm = _normalize_section_name(name)

        # Find the first occurrence of this section's text inside full_text to anchor offsets.
        # (Heuristic; for perfect alignment, walk the Docling item tree later.)
        start = full_text.find(text) if text else -1
        if start == -1:
            start = len(full_text)  # fallback: put at end to keep offsets monotonic
        end = start + len(text)

        sentences = _sentences_with_offsets(text, start)
        sections.append(Section(name=norm, text=text, start_offset=start, end_offset=end, sentences=sentences))

    # 5) Emit structured output for downstream extraction step
    return {
        "full_text": full_text,
        "sections": [s.__dict__ for s in sections],
        "metadata": {"source_id": sid, "title": sid, "year": None, "origin": src_in},
    }

def parse_document_advanced(source: str | Path) -> Dict[str, Any]:
    """
    Placeholder for later: iterate Docling's item tree (e.g., SectionHeaderItem/TextItem)
    to build sections directly from the structure rather than markdown headings.
    """
    # For now, reuse the basic path
    return parse_document(source)
