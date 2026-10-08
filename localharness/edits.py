"""Edición por buscar/reemplazar: el modelo local devuelve solo los trozos que cambian, no el archivo entero.

El 08/10 el autopiloto generó ~505k tokens, muchos copiando archivos enteros «carácter por carácter» para añadir
una línea (2 min por archivo en el modelo de 4B, y a veces se comía versos o entradas). Con esto el modelo escribe:

    <<<<<<< BUSCAR
    líneas exactas que ya están en el archivo
    =======
    cómo tienen que quedar
    >>>>>>> REEMPLAZAR

Se aplican en orden: coincidencia exacta → coincidencia ignorando los espacios de cada línea → si no, error con
las líneas más parecidas del archivo para que el modelo lo intente otra vez.
"""

import difflib
import re

SYSTEM_EDIT = (
    "Eres un programador. NO reescribas el archivo: devuelve SOLO los cambios, como uno o varios bloques así:\n"
    "<<<<<<< BUSCAR\n(líneas copiadas EXACTAMENTE del archivo actual, las justas para que sean únicas)\n=======\n"
    "(cómo tienen que quedar esas líneas)\n>>>>>>> REEMPLAZAR\n"
    "Para añadir algo, BUSCA la línea junto a la que va y en REEMPLAZAR pon esa línea más lo nuevo. "
    "Para crear un archivo que no existe, un solo bloque con BUSCAR vacío. Nada de explicaciones fuera de los "
    "bloques.")

# las palabras BUSCAR/REEMPLAZAR no son obligatorias: gpt-oss con poco razonamiento escribe a veces
# «<<<<<<< CHANGELOG.md … >>>>>>> CHANGELOG.md» (lo que manda es la forma <<<<<<< / ======= / >>>>>>>)
_BLOCK = re.compile(r"^<{5,9}[^\n<]*\n(.*?)^={5,9}[ \t]*\n(.*?)^>{5,9}[^\n>]*$", re.S | re.M)


class EditError(Exception):
    pass


def parse_edits(text: str) -> list[tuple[str, str]]:
    """Los pares (buscar, reemplazar) de la respuesta del modelo, en orden. Sin bloques → lista vacía."""
    out = []
    for m in _BLOCK.finditer(text.replace("\r\n", "\n")):
        out.append((m.group(1), m.group(2)))
    return out


def apply_edits(content: str, edits: list[tuple[str, str]]) -> tuple[str, int]:
    """Aplica los cambios en orden y devuelve (contenido nuevo, cuántos se aplicaron). Si uno no encaja, EditError
    con lo que no encontró y las líneas más parecidas (para reintentar)."""
    if not edits:
        raise EditError("no hay ningún bloque <<<<<<< BUSCAR / ======= / >>>>>>> REEMPLAZAR en la respuesta")
    text = content.replace("\r\n", "\n")
    for i, (search, replace) in enumerate(edits, 1):
        if not search.strip():
            if text.strip():
                raise EditError(f"el cambio {i} tiene BUSCAR vacío, pero el archivo no está vacío: copia las líneas "
                                "junto a las que va el cambio")
            text = replace
            continue
        # exacta y desde principio de línea (si no, «return 1» encajaría a media línea y la sangría se duplicaría)
        hits = len(re.findall("(?=" + re.escape("\n" + search) + ")", "\n" + text))  # contando solapadas
        if hits == 1:
            text = ("\n" + text).replace("\n" + search, "\n" + replace, 1)[1:]
            continue
        if hits > 1:
            raise EditError(f"el cambio {i}: lo que buscas aparece {hits} veces; copia más líneas "
                            "alrededor para que sea único")
        span = _loose(text, search)
        if span is None:
            raise EditError(f"el cambio {i}: no encuentro estas líneas en el archivo:\n{_cut(search)}\n"
                            f"Lo más parecido que hay:\n{_nearest(text, search)}")
        lines = text.split("\n")
        a, b = span
        new = replace[:-1] if replace.endswith("\n") else replace
        lines[a:b] = new.split("\n") if replace else []
        text = "\n".join(lines)
    return text, len(edits)


def _loose(text: str, search: str) -> tuple[int, int] | None:
    """Índices de líneas [a, b) donde está `search` comparando cada línea sin espacios a los lados (los modelos
    pequeños cambian la sangría). Solo si es única."""
    want = [ln.strip() for ln in search.rstrip("\n").split("\n")]
    while want and not want[0]:
        want.pop(0)
    while want and not want[-1]:
        want.pop()
    if not want:
        return None
    have = [ln.strip() for ln in text.split("\n")]
    hits = [i for i in range(len(have) - len(want) + 1) if have[i:i + len(want)] == want]
    return (hits[0], hits[0] + len(want)) if len(hits) == 1 else None


def _nearest(text: str, search: str, context: int = 2) -> str:
    lines = text.split("\n")
    first = next((ln for ln in search.split("\n") if ln.strip()), "")
    best = difflib.get_close_matches(first.strip(), [ln.strip() for ln in lines], n=1, cutoff=0.3)
    if not best:
        return "(nada parecido)"
    i = next(k for k, ln in enumerate(lines) if ln.strip() == best[0])
    n = len(search.strip("\n").split("\n"))
    return _cut("\n".join(lines[max(0, i - context): i + n + context]))


def _cut(s: str, limit: int = 800) -> str:
    return s if len(s) <= limit else s[:limit] + "\n[…]"
