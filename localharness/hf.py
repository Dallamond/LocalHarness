"""Hugging Face: buscar GGUF, ver qué archivos (y tamaños) tiene un repo y descargarlos a tu carpeta de modelos.

Solo la API pública (sin librerías). Para repos con acceso restringido hace falta un token (Ajustes → llama →
hf_token); se manda únicamente a huggingface.co. Las descargas se reanudan si se cortan (archivo `.part`).
"""

import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co"
TOKEN: str | None = None  # lo rellena settings.apply
_tree_cache: dict[str, tuple[float, list[dict]]] = {}
TREE_TTL = 6 * 3600


def _request(url: str, timeout: float = 15) -> urllib.request.Request:
    req = urllib.request.Request(url, headers={"User-Agent": "LocalHarness"})
    if TOKEN and url.startswith(BASE):
        req.add_header("Authorization", f"Bearer {TOKEN}")
    return req


def _get_json(url: str, timeout: float = 15):
    with urllib.request.urlopen(_request(url), timeout=timeout) as r:
        return json.loads(r.read())


def tree(repo: str, cached_only: bool = False) -> list[dict] | None:
    """[{path, size}] de todos los archivos del repo (recursivo: algunas cuantizaciones van en subcarpetas)."""
    hit = _tree_cache.get(repo)
    if hit and time.time() - hit[0] < TREE_TTL:
        return hit[1]
    if cached_only:
        return None
    data = _get_json(f"{BASE}/api/models/{urllib.parse.quote(repo, safe='/')}/tree/main?recursive=true")
    files = [{"path": f["path"], "size": f.get("lfs", {}).get("size") or f.get("size") or 0}
             for f in data if f.get("type") == "file"]
    _tree_cache[repo] = (time.time(), files)
    return files


def search(query: str, limit: int = 20) -> list[dict]:
    """Repos con GGUF que contienen `query`, los más descargados primero."""
    q = urllib.parse.urlencode({"search": query, "filter": "gguf", "sort": "downloads", "direction": "-1",
                                "limit": str(limit)})
    data = _get_json(f"{BASE}/api/models?{q}")
    return [{"repo": m["id"], "downloads": m.get("downloads"), "likes": m.get("likes"),
             "updated": m.get("lastModified"), "url": f"{BASE}/{m['id']}"} for m in data]


def file_url(repo: str, path: str) -> str:
    return f"{BASE}/{repo}/resolve/main/{urllib.parse.quote(path)}"


class Downloads:
    """Descargas en segundo plano (una a la vez, para no saturar el disco ni la red)."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._cancel: set[str] = set()

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(j) for j in self.jobs.values()]

    def start(self, repo: str, files: list[str], dest_dir: Path, total: int = 0) -> dict:
        job_id = f"{repo}:{files[0]}"
        with self._lock:
            j = self.jobs.get(job_id)
            if j and j["state"] in ("queued", "downloading"):
                return dict(j)
            j = {"id": job_id, "repo": repo, "files": files, "dest": str(dest_dir), "state": "queued",
                 "done": 0, "total": total, "speed": 0.0, "error": None, "path": None, "started": time.time()}
            self.jobs[job_id] = j
            self._cancel.discard(job_id)
        threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
        return dict(j)

    def cancel(self, job_id: str) -> None:
        self._cancel.add(job_id)

    def _set(self, job_id: str, **kw) -> None:
        with self._lock:
            self.jobs[job_id].update(kw)

    def _run(self, job_id: str) -> None:
        j = self.jobs[job_id]
        dest = Path(j["dest"]) / j["repo"].split("/")[-1]
        try:
            dest.mkdir(parents=True, exist_ok=True)
            self._set(job_id, state="downloading")
            done_before = 0
            for rel in j["files"]:
                target = dest / Path(rel).name
                if target.exists():
                    done_before += target.stat().st_size
                    self._set(job_id, done=done_before)
                    continue
                done_before += self._file(job_id, file_url(j["repo"], rel), target, done_before)
            first = dest / Path(j["files"][0]).name
            self._set(job_id, state="done", path=str(first), done=j["total"] or done_before)
        except _Cancelled:
            self._set(job_id, state="cancelled")
        except Exception as e:  # red, disco lleno, 401 de repo restringido…
            msg = str(e)
            if "401" in msg or "403" in msg:
                msg += " (repo restringido: acepta la licencia en huggingface.co y pon tu token en Ajustes)"
            self._set(job_id, state="failed", error=msg)

    def _file(self, job_id: str, url: str, target: Path, offset: int) -> int:
        part = target.with_name(target.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        req = _request(url)
        if have:
            req.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(req, timeout=30) as r:
            if have and r.status != 206:  # el servidor no reanuda: empezar de cero
                have = 0
            mode = "ab" if have else "wb"
            t0, last, got = time.time(), have, have
            with open(part, mode) as f:
                while True:
                    if job_id in self._cancel:
                        raise _Cancelled()
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    now = time.time()
                    if now - t0 >= 1:
                        self._set(job_id, done=offset + got, speed=round((got - last) / (now - t0) / 2**20, 1))
                        t0, last = now, got
        part.replace(target)
        return got


class _Cancelled(Exception):
    pass
