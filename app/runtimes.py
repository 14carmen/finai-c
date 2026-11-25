"""Clients for LOCAL model servers.

- Ollama (http://localhost:11434) — the simplest option on a laptop.
- Any OpenAI-compatible server running locally: llama.cpp `llama-server` (e.g. Bonsai), LM Studio,
  `mlx_vlm.server` (Mac), ...

A model is identified in the app as "ollama/qwen2.5vl:3b" or "openai/<model-id>".
"""
import time

import httpx


class RuntimeError_(Exception):
    pass


def split_id(model_id: str):
    runtime, _, name = model_id.partition("/")
    if runtime not in ("ollama", "openai") or not name:
        raise RuntimeError_(f"Invalid model id: {model_id}")
    return runtime, name


# ---------------------------------------------------------------- listing
def list_models(settings) -> dict:
    out, errors = [], {}
    try:
        r = httpx.get(f"{settings['ollama_url']}/api/tags", timeout=5)
        r.raise_for_status()
        for m in r.json().get("models", []):
            caps = _ollama_caps(settings, m["name"])
            det = m.get("details") or {}
            out.append({
                "id": f"ollama/{m['name']}", "runtime": "ollama", "name": m["name"],
                "parameters": det.get("parameter_size"), "quantization": det.get("quantization_level"),
                "size_gb": round(m.get("size", 0) / 1e9, 2),
                "vision": "vision" in caps if caps else None,
                "embedding": "embedding" in caps if caps else ("embed" in m["name"]),
            })
    except Exception as e:
        errors["ollama"] = str(e)
    try:
        r = httpx.get(f"{settings['openai_url']}/models", timeout=5)
        r.raise_for_status()
        for m in r.json().get("data", []):
            out.append({"id": f"openai/{m['id']}", "runtime": "openai", "name": m["id"],
                        "parameters": None, "quantization": None, "size_gb": None, "vision": None,
                        "embedding": "embed" in m["id"].lower()})
    except Exception as e:
        errors["openai"] = str(e)
    return {"models": out, "errors": errors}


_CAPS: dict[str, list] = {}


def _ollama_caps(settings, name):
    if name not in _CAPS:
        try:
            _CAPS[name] = httpx.post(f"{settings['ollama_url']}/api/show", json={"model": name},
                                     timeout=10).json().get("capabilities") or []
        except Exception:
            return []
    return _CAPS[name]


# ---------------------------------------------------------------- generation
def chat(settings, model_id: str, prompt: str, images_b64: list[str], schema: dict | None) -> dict:
    """Returns {text, total_time, load_time, tokens_generated, tokens_per_sec, memory_mb, schema_used}."""
    runtime, name = split_id(model_id)
    timeout = float(settings.get("timeout_s", 900))
    if runtime == "ollama":
        return _ollama(settings, name, prompt, images_b64, schema, timeout)
    return _openai(settings, name, prompt, images_b64, schema, timeout)


def _ollama(settings, name, prompt, images, schema, timeout):
    msg = {"role": "user", "content": prompt}
    if images:
        msg["images"] = images
    body = {"model": name, "messages": [msg], "stream": False,
            "options": {"temperature": 0, "num_ctx": int(settings.get("num_ctx", 8192))}}
    if schema:
        body["format"] = schema
    if "thinking" in _ollama_caps(settings, name):
        # "thinking" models (e.g. qwen3-vl) may reason for minutes before the JSON;
        # thinking=yes lets them think (an interesting comparison in itself)
        body["think"] = settings.get("thinking", "no") == "yes"
    t0 = time.perf_counter()
    r = httpx.post(f"{settings['ollama_url']}/api/chat", json=body, timeout=timeout)
    wall = time.perf_counter() - t0
    if r.status_code != 200:
        raise RuntimeError_(f"Ollama {r.status_code}: {r.text[:300]}")
    j = r.json()
    if j.get("error"):
        raise RuntimeError_(f"Ollama: {j['error']}")
    ev, evd = j.get("eval_count"), j.get("eval_duration")
    return {
        "text": (j.get("message") or {}).get("content", ""),
        "total_time": wall,
        "load_time": (j.get("load_duration") or 0) / 1e9,
        "tokens_generated": ev,
        "tokens_per_sec": round(ev / (evd / 1e9), 2) if ev and evd else None,
        "memory_mb": ollama_memory(settings, name),
        "schema_used": bool(schema),
    }


def ollama_memory(settings, name):
    try:
        for m in httpx.get(f"{settings['ollama_url']}/api/ps", timeout=5).json().get("models", []):
            if m.get("name") == name or m.get("model") == name:
                return round(m.get("size", 0) / 1e6, 1)
    except Exception:
        pass
    return None


def unload(settings, model_id):
    """Frees memory after a model has finished (useful on laptops with little RAM)."""
    runtime, name = split_id(model_id)
    if runtime == "ollama":
        try:
            httpx.post(f"{settings['ollama_url']}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)
        except Exception:
            pass


def _openai(settings, name, prompt, images, schema, timeout):
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b}"}} for b in images]
    body = {"model": name, "messages": [{"role": "user", "content": content if images else prompt}],
            "temperature": 0, "stream": False}
    if schema:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "financial_statement", "schema": schema, "strict": True}}
    url = f"{settings['openai_url']}/chat/completions"
    schema_used = bool(schema)
    t0 = time.perf_counter()
    r = httpx.post(url, json=body, timeout=timeout)
    if r.status_code in (400, 422) and schema:          # some servers do not support json_schema
        body.pop("response_format")
        schema_used = False
        t0 = time.perf_counter()
        r = httpx.post(url, json=body, timeout=timeout)
    wall = time.perf_counter() - t0
    if r.status_code != 200:
        raise RuntimeError_(f"OpenAI-compatible server {r.status_code}: {r.text[:300]}")
    j = r.json()
    usage = j.get("usage") or {}
    timings = j.get("timings") or {}                     # llama.cpp reports exact generation speed here
    ct = usage.get("completion_tokens") or timings.get("predicted_n")
    tps = timings.get("predicted_per_second") or (ct / wall if ct and wall else None)
    return {
        "text": j["choices"][0]["message"].get("content") or "",
        "total_time": wall, "load_time": None,
        "tokens_generated": ct,
        "tokens_per_sec": round(tps, 2) if tps else None,
        "memory_mb": None,
        "schema_used": schema_used,
    }


def embed(settings, model_id: str, texts: list[str]) -> list[list[float]]:
    """Embedding vectors from a local model (Ollama /api/embed or OpenAI-compatible /embeddings)."""
    runtime, name = split_id(model_id)
    timeout = float(settings.get("timeout_s", 900))
    if runtime == "ollama":
        r = httpx.post(f"{settings['ollama_url']}/api/embed", json={"model": name, "input": texts}, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError_(f"Ollama embed {r.status_code}: {r.text[:300]}")
        j = r.json()
        if j.get("error"):
            raise RuntimeError_(f"Ollama: {j['error']}")
        return j["embeddings"]
    r = httpx.post(f"{settings['openai_url']}/embeddings", json={"model": name, "input": texts}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError_(f"OpenAI-compatible server {r.status_code}: {r.text[:300]}")
    return [d["embedding"] for d in r.json()["data"]]
