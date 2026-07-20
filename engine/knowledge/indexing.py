"""Knowledge base indexing — chunk .md → BM25 index → persistent JSON."""

import json
import re
from pathlib import Path
from typing import Optional

import jieba

# Directory containing all .md knowledge files (skill root: core/, methods/, references/, ...)
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent
INDEX_FILE = Path(__file__).resolve().parent / "index_data.json"


class Chunk:
    """A single chunk of knowledge content."""
    def __init__(self, chunk_id: str, content: str, source: str,
                 section: str, category: str, doc_order: int):
        self.chunk_id = chunk_id
        self.content = content
        self.source = source       # filename, e.g. "fake-detection.md"
        self.section = section     # section title
        self.category = category   # e.g. "core", "methods", "references"
        self.doc_order = doc_order

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "source": self.source,
            "section": self.section,
            "category": self.category,
            "doc_order": self.doc_order,
        }

    @staticmethod
    def from_dict(d: dict) -> "Chunk":
        return Chunk(d["chunk_id"], d["content"], d["source"],
                     d["section"], d["category"], d["doc_order"])


def _tokenize(text: str) -> list[str]:
    """Tokenize Chinese + English text for BM25."""
    # Replace markdown syntax with spaces
    text = re.sub(r'[#*`\[\]()|>]', ' ', text)
    words = jieba.lcut(text)
    # Filter short tokens and whitespace
    return [w.strip().lower() for w in words if len(w.strip()) > 1]


def chunk_md(content: str, source: str, category: str) -> list[Chunk]:
    """Split a .md file into chunks by ## headings."""
    lines = content.split("\n")
    chunks = []
    current_section = "前言"
    current_lines: list[str] = []
    doc_order = 0
    chunk_counter = 0

    for line in lines:
        h2_match = re.match(r"^##\s+(.+)$", line)
        if h2_match:
            if current_lines and any(l.strip() for l in current_lines):
                chunk_content = "\n".join(current_lines).strip()
                if len(chunk_content) > 20:  # skip empty/small chunks
                    chunk_id = f"{source}::{chunk_counter}"
                    chunks.append(Chunk(chunk_id, chunk_content, source,
                                        current_section, category, doc_order))
                    doc_order += 1
                    chunk_counter += 1
            current_section = h2_match.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Last chunk
    if current_lines and any(l.strip() for l in current_lines):
        chunk_content = "\n".join(current_lines).strip()
        if len(chunk_content) > 20:
            chunk_id = f"{source}::{chunk_counter}"
            chunks.append(Chunk(chunk_id, chunk_content, source,
                                current_section, category, doc_order))

    return chunks


def build_index(knowledge_dir: Optional[Path] = None) -> dict:
    """Build BM25 index from all .md files in the knowledge directory."""
    from rank_bm25 import BM25Okapi

    base_dir = knowledge_dir or KNOWLEDGE_DIR
    all_chunks: list[Chunk] = []

    # Walk skill root for category directories
    for category_dir in sorted(base_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        # Skip directories that don't contain knowledge .md files
        if category.startswith(".") or category in ("engine", "scripts", "__pycache__"):
            continue
        for md_file in sorted(category_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            source = md_file.name
            chunks = chunk_md(content, source, category)
            all_chunks.extend(chunks)

    # Prepare corpus for BM25
    corpus = [_tokenize(c.content) for c in all_chunks]
    bm25 = BM25Okapi(corpus)

    return {"index_data": {"chunks": [c.to_dict() for c in all_chunks]}, "bm25": bm25, "chunks": all_chunks}


def save_index(index_data: dict, path: Optional[Path] = None):
    """Persist chunks to JSON."""
    save_path = path or INDEX_FILE
    save_path.parent.mkdir(parents=True, exist_ok=True)
    chunks = index_data.get("chunks", [])
    data = {
        "chunks": [c.to_dict() if isinstance(c, Chunk) else c for c in chunks],
    }
    save_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_index(path: Optional[Path] = None) -> dict:
    """Load index from JSON file and rebuild BM25."""
    from rank_bm25 import BM25Okapi

    load_path = path or INDEX_FILE
    if not load_path.exists():
        return build_index()

    data = json.loads(load_path.read_text(encoding="utf-8"))
    chunks = [Chunk.from_dict(d) for d in data["chunks"]]
    corpus = [_tokenize(c.content) for c in chunks]
    bm25 = BM25Okapi(corpus)

    return {"index_data": data, "bm25": bm25, "chunks": chunks}


def query_index(query: str, index_result: dict, top_k: int = 5) -> list[dict]:
    """Query the BM25 index and return top-k results."""
    bm25 = index_result["bm25"]
    chunks = index_result["chunks"]
    tokenized_query = _tokenize(query)
    scores = bm25.get_scores(tokenized_query)

    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

    results = []
    for idx in top_indices:
        if scores[idx] > 0:
            result = chunks[idx].to_dict()
            result["score"] = round(float(scores[idx]), 4)
            results.append(result)

    return results


def list_sources(index_result: dict) -> list[dict]:
    """List all unique knowledge sources with chunk counts."""
    from collections import Counter
    chunks = index_result["chunks"]
    sources = Counter((c.source, c.category) for c in chunks)
    return [
        {"source": source, "category": cat, "chunks": count}
        for (source, cat), count in sorted(sources.items())
    ]
