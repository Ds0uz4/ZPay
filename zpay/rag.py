"""Local BM25 retrieval over docs/ingested with per-agent source allowlists and citation IDs."""
import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from . import config

EXTENSIONS = {".txt", ".md", ".yaml"}
SKIP = re.compile(r"(?:clarify|specify|analyze)-command|LICENSE|README", re.I)
ALLOWED_CATEGORIES = {"finance", "product", "requirements", "security", "user"}
STOP = set(
    "the and for are but not you all any can had her was one our out has have that this with from they will would "
    "there their what about which when your than then them these into only also more such shall should must may per "
    "its been were being each other".split()
)
K1, B = 1.5, 0.75
CHUNK_CHARS, OVERLAP = 1000, 150


@dataclass
class Evidence:
    id: str
    source: str
    category: str
    score: float
    confidence: float
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Chunk:
    source: str
    category: str
    text: str
    length: int = 0


_chunks: list[_Chunk] = []
_postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
_avg_len = 1.0
_corpus_hash = ""


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9-]+", text.lower()) if t not in STOP]


def _split(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    out, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            brk = text.rfind("\n", start, end)
            if brk > start + CHUNK_CHARS * 0.5:
                end = brk
        piece = text[start:end].strip()
        if len(piece) > 80:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return out


def build_index() -> dict:
    global _avg_len, _corpus_hash
    _chunks.clear()
    _postings.clear()
    digest = hashlib.sha256()
    files = 0
    for path in sorted(config.DOCS_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS or SKIP.search(path.name):
            continue
        source = path.relative_to(config.DOCS_DIR).as_posix()
        category = source.split("/")[0]
        if category not in ALLOWED_CATEGORIES:
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore")
        digest.update(source.encode())
        digest.update(raw.encode())
        files += 1
        _chunks.extend(_Chunk(source, category, piece) for piece in _split(raw))
    total = 0
    for idx, chunk in enumerate(_chunks):
        tokens = tokenize(chunk.text)
        chunk.length = len(tokens)
        total += len(tokens)
        for term, tf in Counter(tokens).items():
            _postings[term].append((idx, tf))
    _avg_len = total / max(len(_chunks), 1)
    _corpus_hash = digest.hexdigest()
    return index_info() | {"files": files}


def index_info() -> dict:
    return {"chunks": len(_chunks), "hash": _corpus_hash}


def _idf(term: str) -> float:
    n = len(_postings.get(term, ()))
    return math.log(1 + (len(_chunks) - n + 0.5) / (n + 0.5)) if n else 0.0


def search(query: str, k: int | None = None, categories: list[str] | None = None) -> list[dict]:
    """BM25. confidence = score / best score a perfect match on the query terms could reach."""
    k = k or config.RAG_TOP_K
    terms = sorted(
        ((t, _idf(t)) for t in set(tokenize(query))), key=lambda x: x[1], reverse=True
    )
    terms = [(t, w) for t, w in terms if w > 0][:16]
    if not terms:
        return []
    scores: dict[int, float] = defaultdict(float)
    for term, weight in terms:
        for idx, tf in _postings[term]:
            chunk = _chunks[idx]
            if categories and chunk.category not in categories:
                continue
            norm = tf + K1 * (1 - B + B * chunk.length / _avg_len)
            scores[idx] += weight * (tf * (K1 + 1)) / norm
    ceiling = sum(w * (K1 + 1) for _, w in terms) or 1.0
    per_source: Counter = Counter()
    hits: list[dict] = []
    for idx, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        chunk = _chunks[idx]
        if per_source[chunk.source] >= 2:
            continue
        per_source[chunk.source] += 1
        hits.append(
            {
                "key": f"{chunk.source}#{idx}",
                "source": chunk.source,
                "category": chunk.category,
                "score": round(score, 3),
                "confidence": round(min(1.0, score / ceiling), 3),
                "text": chunk.text,
            }
        )
        if len(hits) >= k:
            break
    return hits


class EvidencePool:
    """Per-run registry that assigns stable E-numbers agents can cite."""

    def __init__(self) -> None:
        self._by_key: dict[str, Evidence] = {}

    def add(self, hits: list[dict]) -> list[Evidence]:
        out = []
        for hit in hits:
            ev = self._by_key.get(hit["key"])
            if ev is None:
                ev = Evidence(
                    id=f"E{len(self._by_key) + 1}",
                    source=hit["source"],
                    category=hit["category"],
                    score=hit["score"],
                    confidence=hit["confidence"],
                    text=hit["text"],
                )
                self._by_key[hit["key"]] = ev
            out.append(ev)
        return out

    def get(self, ev_id: str) -> Evidence | None:
        return next((e for e in self._by_key.values() if e.id == ev_id), None)

    def all(self) -> list[Evidence]:
        return list(self._by_key.values())


def format_evidence(items: list[Evidence], max_chars: int = 650) -> str:
    if not items:
        return "(no evidence retrieved - mark regulatory claims NEEDS-VALIDATION)"
    return "\n".join(f"[{e.id}] ({e.source}) {re.sub(r'\s+', ' ', e.text)[:max_chars]}" for e in items)
