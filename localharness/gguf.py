"""Leer la cabecera de un GGUF sin cargarlo: arquitectura, parámetros, contexto, capas, cabezas y plantilla de chat.

Solo se lee la tabla de metadatos del principio del archivo (unos MB como mucho por el vocabulario); los tensores
no se tocan. Con eso se sabe cuánta memoria pide cada tamaño de contexto y si la plantilla admite herramientas.
Formato: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
"""

import re
import struct
from pathlib import Path
from typing import Any, BinaryIO

# tipo → formato de struct (los escalares)
_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9
# arrays que no interesan y pueden ser enormes (vocabulario): se saltan sin guardarlos
_SKIP_ARRAYS = ("tokenizer.ggml.tokens", "tokenizer.ggml.scores", "tokenizer.ggml.token_type",
                "tokenizer.ggml.merges")

# general.file_type → nombre de la cuantización (enum llama_ftype de llama.cpp)
FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K",
              11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M",
              18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S",
              25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M",
              32: "BF16", 36: "TQ1_0", 37: "TQ2_0", 38: "MXFP4"}


class GGUFError(ValueError):
    pass


def _read(f: BinaryIO, n: int) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise GGUFError("archivo GGUF cortado")
    return b


def _string(f: BinaryIO, long: bool) -> str:
    n = struct.unpack("<Q" if long else "<I", _read(f, 8 if long else 4))[0]
    if n > 64 * 2**20:
        raise GGUFError("cadena imposible en la cabecera")
    return _read(f, n).decode("utf-8", errors="replace")


def _value(f: BinaryIO, t: int, long: bool, keep: bool = True) -> Any:
    if t in _SCALAR:
        fmt = _SCALAR[t]
        return struct.unpack(fmt, _read(f, struct.calcsize(fmt)))[0]
    if t == _STRING:
        return _string(f, long)
    if t == _ARRAY:
        it = struct.unpack("<I", _read(f, 4))[0]
        n = struct.unpack("<Q" if long else "<I", _read(f, 8 if long else 4))[0]
        if it in _SCALAR and not keep:
            f.seek(n * struct.calcsize(_SCALAR[it]), 1)
            return None
        items = [_value(f, it, long, keep) for _ in range(n)]
        return items if keep else None
    raise GGUFError(f"tipo de valor desconocido {t}")


def read_metadata(path: str | Path) -> dict[str, Any]:
    """Todos los pares clave-valor de la cabecera, salvo el vocabulario."""
    with open(path, "rb") as f:
        if _read(f, 4) != b"GGUF":
            raise GGUFError("no es un archivo GGUF")
        version = struct.unpack("<I", _read(f, 4))[0]
        long = version >= 2  # v1 usaba enteros de 32 bits para longitudes
        cnt = "<Q" if long else "<I"
        size = 8 if long else 4
        _tensors = struct.unpack(cnt, _read(f, size))[0]
        n_kv = struct.unpack(cnt, _read(f, size))[0]
        if n_kv > 100_000:
            raise GGUFError("cabecera GGUF imposible")
        meta: dict[str, Any] = {"GGUF.version": version, "GGUF.tensor_count": _tensors}
        for _ in range(n_kv):
            key = _string(f, long)
            t = struct.unpack("<I", _read(f, 4))[0]
            keep = key not in _SKIP_ARRAYS
            v = _value(f, t, long, keep)
            if keep:
                meta[key] = v
            elif t == _ARRAY:
                meta[key + ".__skipped__"] = True
        return meta


def _params_from_label(label: str | None) -> float | None:
    """'8B' → 8.0, '30B-A3B' → 30.0, '500M' → 0.5"""
    if not label:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*([BM])", str(label), re.I)
    if not m:
        return None
    return float(m.group(1)) / (1000 if m.group(2).upper() == "M" else 1)


def summarize(meta: dict[str, Any]) -> dict[str, Any]:
    """Lo que hace falta para estimar memoria y valorar el modelo."""
    arch = meta.get("general.architecture") or "?"

    def g(key: str, default: Any = None) -> Any:
        v = meta.get(f"{arch}.{key}", default)
        if isinstance(v, list):  # algunas arquitecturas guardan un valor por capa: basta el máximo
            nums = [x for x in v if isinstance(x, (int, float))]
            return max(nums) if nums else default
        return v

    n_layer = g("block_count")
    n_embd = g("embedding_length")
    n_head = g("attention.head_count")
    n_head_kv = g("attention.head_count_kv", n_head)
    key_len = g("attention.key_length") or (n_embd // n_head if n_embd and n_head else None)
    val_len = g("attention.value_length") or key_len
    experts = g("expert_count") or 0
    experts_used = g("expert_used_count") or 0
    # híbridos (Qwen3-Next/3.5, Granite 4…): solo 1 de cada N capas usa atención con caché KV completa
    interval = g("full_attention_interval")
    attn_layers = n_layer
    if n_layer and isinstance(interval, int) and interval > 1:
        attn_layers = max(1, n_layer // interval)
    sliding = g("attention.sliding_window")

    template = meta.get("tokenizer.chat_template") or ""
    if isinstance(template, list):
        template = " ".join(str(t) for t in template)
    tools = bool(re.search(r"\btools\b|tool_call|<tool_call>|\[TOOL_CALLS\]|function_call", template))
    thinking = bool(re.search(r"<think>|enable_thinking|reasoning_content|reasoning_effort", template))

    ftype = meta.get("general.file_type")
    label = meta.get("general.size_label")
    return {
        "arch": arch,
        "name": meta.get("general.name") or meta.get("general.basename"),
        "size_label": label,
        "params_b": _params_from_label(label),
        "quant": FILE_TYPES.get(ftype) if isinstance(ftype, int) else None,
        "ctx_train": g("context_length"),
        "n_layer": n_layer,
        "attn_layers": attn_layers,
        "n_embd": n_embd,
        "n_head": n_head,
        "n_head_kv": n_head_kv,
        "key_length": key_len,
        "value_length": val_len,
        "sliding_window": sliding if isinstance(sliding, int) else None,
        "experts": experts,
        "experts_used": experts_used,
        "moe": bool(experts and experts > 1),
        "vocab": len(meta["tokenizer.ggml.tokens"]) if isinstance(meta.get("tokenizer.ggml.tokens"), list) else None,
        "chat_template": bool(template),
        "tools_in_template": tools,
        "thinking": thinking,
        "license": meta.get("general.license"),
    }


def inspect(path: str | Path) -> dict[str, Any]:
    return summarize(read_metadata(path))
