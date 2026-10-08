"""Buscar trozos de código relacionados con embeddings (P12 del plan), sin dependencias.

Un llama-server con un modelo de embeddings (p. ej. Qwen3-Embedding-0.6B, arrancado con --embeddings; vale en la
CPU) convierte cada trozo del repo en un vector. Los vectores se guardan en SQLite por HUELLA del texto del trozo,
no por ruta: cada tarea tiene su worktree, pero un trozo que no cambió no se vuelve a calcular. La similitud es el
coseno, en Python: para repos pequeños sobra.
"""

import array
import hashlib
import json
import math
import sqlite3
import tempfile
import threading
import urllib.request
from pathlib import Path

from localharness.repomap import SKIP_DIRS, TEXT_EXT

CHUNK_CHARS = 1200
MAX_FILE_CHARS = 200_000
BATCH = 16
_lock = threading.Lock()


def default_db() -> Path:
    return Path(tempfile.gettempdir()) / "localharness-rag.sqlite"


def chunks(root: Path) -> list[dict]:
    """Trozos de ~CHUNK_CHARS cortados por líneas en blanco (funciones, reglas, secciones), con su ruta y línea."""
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT or SKIP_DIRS.intersection(p.relative_to(root).parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
        except OSError:
            continue
        rel = p.relative_to(root).as_posix()
        buf, start, line = [], 1, 1
        for para in text.split("\n\n"):
            if buf and sum(len(b) for b in buf) + len(para) > CHUNK_CHARS:
                out.append({"path": rel, "line": start, "text": "\n\n".join(buf)})
                buf, start = [], line
            buf.append(para[:CHUNK_CHARS * 2])
            line += para.count("\n") + 2
        if buf:
            out.append({"path": rel, "line": start, "text": "\n\n".join(buf)})
    return out


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def embed(url: str, texts: list[str], post=None) -> list[list[float]]:
    body = {"input": texts}
    data = (post or _post)(url.rstrip("/") + "/v1/embeddings", body)
    return [d["embedding"] for d in sorted(data.get("data") or [], key=lambda d: d.get("index", 0))]


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def _db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE IF NOT EXISTS vec (key TEXT PRIMARY KEY, v BLOB)")
    return con


def search(root: Path, query: str, url: str, k: int = 5, db: Path | None = None, post=None,
           only: set[str] | None = None) -> list[dict]:
    """Los `k` trozos del repo más parecidos a `query`: [{path, line, text, score}]."""
    items = [c for c in chunks(root) if not only or c["path"] in only]
    if not items:
        return []
    with _lock:
        con = _db(db or default_db())
        try:
            have = {}
            keys = [_key(c["text"]) for c in items]
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                q = f"SELECT key, v FROM vec WHERE key IN ({','.join('?' * len(part))})"
                have.update({key: array.array("f", v).tolist() for key, v in con.execute(q, part)})
            missing = [(key, c["text"]) for key, c in zip(keys, items) if key not in have]
            for i in range(0, len(missing), BATCH):
                part = missing[i:i + BATCH]
                vecs = embed(url, [t for _, t in part], post)
                for (key, _), v in zip(part, vecs):
                    have[key] = v
                    con.execute("INSERT OR REPLACE INTO vec VALUES (?, ?)", (key, array.array("f", v).tobytes()))
            con.commit()
        finally:
            con.close()
    qv = embed(url, [query], post)[0]
    scored = [{**c, "score": round(cosine(qv, have[key]), 3)} for key, c in zip(keys, items) if key in have]
    return sorted(scored, key=lambda c: -c["score"])[:k]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
