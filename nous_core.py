"""Fetch the live free-model catalog from the Nous Portal + inference API."""
import json
import os
import urllib.request

DEFAULT_PORTAL = "https://portal.nousresearch.com"
DEFAULT_INFERENCE = "https://inference-api.nousresearch.com/v1"


def hermes_home():
    """Locate the Hermes home directory that holds auth.json."""
    candidates = [
        os.environ.get("HERMES_HOME"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes"),
        os.path.expanduser("~/.hermes"),
    ]
    for cand in candidates:
        if cand and os.path.isfile(os.path.join(cand, "auth.json")):
            return cand
    return None


def load_auth():
    home = hermes_home()
    if not home:
        raise RuntimeError(
            "Could not find Hermes auth.json. Run `hermes setup` / log in first."
        )
    with open(os.path.join(home, "auth.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    prov = data["providers"]["nous"]
    return {
        "token": prov["access_token"],
        "portal": prov.get("portal_base_url", DEFAULT_PORTAL).rstrip("/"),
        "inference": prov.get("inference_base_url", DEFAULT_INFERENCE).rstrip("/"),
    }


def _get_json(url, token):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "User-Agent": "hfmm/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"), strict=False)


def _price_is_free(value):
    try:
        return float(str(value).replace("$", "").strip() or "nan") == 0.0
    except ValueError:
        return False


def _catalog_info(model):
    """Context / modality facts for any catalog entry, free or paid."""
    arch = model.get("architecture") or {}
    modalities = arch.get("input_modalities") or ["text"]
    return {
        "context": model.get("context_length") or model.get("contextLength"),
        "inputs": ", ".join(modalities),
        "vision": "image" in modalities,
        "video": "video" in modalities,
    }


def _catalog_row(model, source="catalog"):
    pricing = model.get("pricing") or {}
    if not (_price_is_free(pricing.get("prompt")) and _price_is_free(pricing.get("completion"))):
        return None
    row = _catalog_info(model)
    row["name"] = model.get("id")
    row["compaction"] = False
    row["source"] = source
    return row


_OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_HEADERS = {"User-Agent": "hfmm/1.0"}

_openrouter_cache = {}


def _env_openrouter_key():
    """OpenRouter token lives in Hermes's .env, the same file the CLI loads."""
    home = hermes_home()
    if not home:
        return None
    try:
        with open(os.path.join(home, ".env"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _pool_openrouter_key():
    """Also accept a pooled credential from auth.json if no .env is present."""
    home = hermes_home()
    if not home:
        return None
    try:
        with open(os.path.join(home, "auth.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    pool = (data.get("credential_pool") or {}).get("openrouter")
    if not isinstance(pool, list):
        return None
    for entry in pool:
        if isinstance(entry, dict):
            for field in ("api_key", "access_token", "key"):
                if entry.get(field):
                    return entry[field]
    return None


def _openrouter_key_accepts(key):
    req = urllib.request.Request(
        _OPENROUTER_KEY_URL,
        headers={"Authorization": f"Bearer {key}", **_OPENROUTER_HEADERS},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def openrouter_key():
    """Return a valid OpenRouter token, checked once per process, or None."""
    cached = _openrouter_cache.get("key")
    if cached is not None:
        return cached
    for candidate in (_env_openrouter_key, _pool_openrouter_key):
        key = candidate()
        if key and _openrouter_key_accepts(key):
            _openrouter_cache["key"] = key
            return key
    _openrouter_cache["key"] = None
    return None


def _get_json_http(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"), strict=False)


def fetch_free_models():
    """Return (list_of_free_models, meta_dict)."""
    auth = load_auth()
    portal = _get_json(auth["portal"] + "/api/nous/recommended-models", auth["token"])
    catalog = _get_json(auth["inference"] + "/models", auth["token"]).get("data", [])

    by_id = {}
    for model in catalog:
        row = _catalog_row(model)
        if row:
            by_id[row["name"]] = row

    # Context/flags for every catalog entry (paid ones too), so the config tab
    # can show them for models that are not on the free list.
    lookup = {}
    for model in catalog:
        rid = model.get("id")
        if rid:
            lookup[rid] = _catalog_info(model)

    by_name = {}

    def add(record, source):
        name = record["name"]
        existing = by_name.get(name)
        if existing is None:
            merged = dict(record, sources={source})
            by_name[name] = merged
            return
        existing["sources"].add(source)
        existing["vision"] = existing["vision"] or record["vision"]
        existing["video"] = existing["video"] or record["video"]
        existing["compaction"] = existing["compaction"] or record["compaction"]
        if not existing["context"]:
            existing["context"] = record["context"]
        if record["inputs"] != "text":
            existing["inputs"] = record["inputs"]

    for rec in portal.get("freeRecommendedModels") or []:
        slug = rec.get("modelName")
        if not slug:
            continue
        catalog_hit = by_id.get(slug, {})
        add(
            {
                "name": slug,
                "context": catalog_hit.get("context") or rec.get("contextLength"),
                "inputs": catalog_hit.get("inputs")
                or ("text, image" if rec.get("isVisionModel") else "text"),
                "vision": bool(rec.get("isVisionModel")) or catalog_hit.get("vision", False),
                "video": catalog_hit.get("video", False),
                "compaction": bool(rec.get("isCompactionModel")),
            },
            "portal",
        )

    for key in ("freeRecommendedVisionModel", "freeRecommendedCompactionModel"):
        rec = portal.get(key)
        if not rec or not rec.get("modelName"):
            continue
        catalog_hit = by_id.get(rec["modelName"], {})
        add(
            {
                "name": rec["modelName"],
                "context": catalog_hit.get("context") or rec.get("contextLength"),
                "inputs": catalog_hit.get("inputs")
                or ("text, image" if rec.get("isVisionModel") else "text"),
                "vision": bool(rec.get("isVisionModel")) or catalog_hit.get("vision", False),
                "video": catalog_hit.get("video", False),
                "compaction": bool(rec.get("isCompactionModel")),
            },
            "portal",
        )

    for slug, row in sorted(by_id.items()):
        if slug not in by_name:
            add(row, "catalog")

    or_key = openrouter_key()
    or_count = 0
    if or_key:
        try:
            payload = _get_json_http(
                _OPENROUTER_MODELS_URL,
                {"Authorization": f"Bearer {or_key}", **_OPENROUTER_HEADERS},
            )
        except Exception:  # noqa: BLE001
            pass
        else:
            for model in payload.get("data", []):
                rid = model.get("id") or model.get("model") or ""
                pricing = model.get("pricing") or {}
                # Free on OpenRouter: the :free marker, or $0 input AND $0 output.
                free_marker = rid.endswith(":free")
                zero_in_out = (_price_is_free(pricing.get("prompt"))
                               and _price_is_free(pricing.get("completion")))
                if not (free_marker or zero_in_out):
                    continue
                row = dict(_catalog_info(model))
                row["name"] = model.get("id")
                row["compaction"] = False
                row["source"] = "openrouter"
                add(row, "openrouter")
                or_count += 1

    results = []
    for name, rec in sorted(by_name.items()):
        sources = rec.pop("sources")
        if sources == {"portal", "catalog"}:
            rec["source"] = "portal+catalog"
        else:
            rec["source"] = next(iter(sources))
        results.append(rec)

    # Free rows carry portal-derived context/flags for models the catalog does
    # not describe; fold them into the lookup as well.
    for rec in results:
        info = lookup.setdefault(rec["name"], {})
        info.setdefault("context", rec.get("context"))
        info.setdefault("inputs", rec.get("inputs"))
        info.setdefault("vision", rec.get("vision", False))
        info.setdefault("video", rec.get("video", False))
        info.setdefault("compaction", rec.get("compaction", False))

    return results, {
        "catalog_rows": len(catalog),
        "free_count": len(results),
        "catalog_ids": [m.get("id") for m in catalog if m.get("id")],
        "openrouter": or_count,
        "catalog_lookup": lookup,
    }
