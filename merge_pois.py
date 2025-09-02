# merge_pois.py
# Merge selection runs (A/B/C...) and refine batches into current_pois.json
# - Selection input:  src/data/gpt_output.json        ({"runs":[...]} as produced by your runner)
# - Refine input:     src/data/refine_output.json     (single batch or {"batches":[...]})
# - Current working:  src/data/current_pois.json      (created/updated here)
#
# Usage examples:
#   python merge_pois.py
#   python merge_pois.py --selection src/data/gpt_output.json --refine src/data/refine_output.json \
#                        --current src/data/current_pois.json --out src/data/current_pois.json \
#
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from difflib import SequenceMatcher
import argparse, json, re, unicodedata, hashlib, shutil
from collections import Counter

# ------------- Config -------------
NAME_SIM_THRESHOLD = 0.92
NAME_SIM_MARGIN = 0.03
MAX_ALT_NAMES = 3
TEASER_CHAR_CAP = 120

BASE = Path("src/data")
REFINEMENT_FILES = {
    "gpt_out": BASE / "gpt_output.json",
    "backups": BASE / "backups",
    "log": BASE / "tour_log.jsonl",
}

REFINEMENT_FILES["backups"].mkdir(parents=True, exist_ok=True)

STATUS_PRIORITY = {
    "keep": 5,
    "gpt_refined": 4,
    "raw": 3,
    "recheck": 2,
    "drop": 1,
}

TYPE_PREFERENCE = {
    "museum": 3, "church": 3, "trail": 3,
    "monument": 2, "memorial": 2, "park": 2, "site": 2, "plaque": 2,
    "building": 1, "point_of_interest": 1, "other": 1,
}

ADDR_VAGUE_HINTS = (
    "rough", "boundary", "boundaries", "district", "route",
    "starts at", "trailhead", "southern trailhead", "northern trailhead", "—", " / "
)
TYPE_NOUNS = {
    "mint","square","trail","pier","cathedral","museum","building","district",
    "fort","plaza","tower","ferry","park","monument","memorial","church","site"
}

STREET_WORDS = r"(st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|ct|court|hwy|highway|pkwy|parkway)\b"
ADDRISH_RX = re.compile(rf"^\s*\d+[\w\s\-.,/]*\b{STREET_WORDS}", re.I)
WALKING_ROUTE_RX = re.compile(r"\b(walking trail|trail route|route|view|viewing area|viewpoint|overlook)\b", re.I)
CLEAN_PARENS_RX = re.compile(r"\s*\([^)]*\)")
TRADEMARK_RX = re.compile(r"[®™]")

# ------------- Utils -------------
def has_type_noun(nm: str) -> bool:
    words = {w.lower() for w in name_tokens(nm)}
    return any(t in words for t in TYPE_NOUNS)

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

_norm_rx = re.compile(r"[^\w\s-]+", re.UNICODE)

def normalize_key(s: str) -> str:
    if not s: return ""
    s = s.lower()
    s = _norm_rx.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

_spaces_rx = re.compile(r"\s+")
def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = _spaces_rx.sub("-", s).strip("-")
    return s or "poi"

def short_hash(s: str, n: int = 6) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:n]

def norm_name(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = _spaces_rx.sub(" ", s).strip()
    return s

def normalize_base_name(nm: str) -> str:
    s = (nm or "").strip()
    if not s:
        return s
    # drop trademarks and parentheticals
    s = TRADEMARK_RX.sub("", s)
    s = CLEAN_PARENS_RX.sub("", s)
    # keep only left side of slashes
    if " / " in s:
        s = s.split(" / ", 1)[0]
    # drop leading "The "
    if s.lower().startswith("the "):
        s = s[4:]
    # collapse spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s

def name_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_name(a), norm_name(b)).ratio()

def clean_teaser(t: str) -> str:
    t = (t or "").strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return t
    # take up to 2 sentences
    parts = re.split(r'(?<=[.!?])\s+', t)
    t = " ".join(parts[:2]).strip()
    # final hard cap (keep your TEASER_CHAR_CAP or bump to ~180 if you want)
    if len(t) > TEASER_CHAR_CAP:
        t = t[:TEASER_CHAR_CAP].rsplit(" ", 1)[0] + "…"
    return t


def clean_address(a: str) -> str:
    a = (a or "").strip()
    a = re.sub(r"\s*\([^)]*\)\s*", " ", a)  # drop parenthetical notes
    a = re.sub(r"\s+", " ", a).strip()
    return a

def address_needs_refine(a: str) -> bool:
    aa = (a or "").lower()
    return any(k in aa for k in ADDR_VAGUE_HINTS)

def dedupe_preserve(seq: List[str], cap: int = MAX_ALT_NAMES) -> List[str]:
    seen, out = set(), []
    for s in seq or []:
        s2 = (s or "").strip()
        if not s2:
            continue
        key = s2.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s2)
        if len(out) >= cap:
            break
    return out

def majority_type(types: List[str]) -> str:
    if not types:
        return "point_of_interest"
    counts: Dict[str, int] = {}
    for t in types:
        tt = (t or "point_of_interest").lower()
        if "trail" in tt: tt = "trail"
        counts[tt] = counts.get(tt, 0) + 1
    best = None
    for t, c in counts.items():
        if best is None:
            best = (t, c)
            continue
        bt, bc = best
        if c > bc or (c == bc and TYPE_PREFERENCE.get(t, 1) > TYPE_PREFERENCE.get(bt, 1)):
            best = (t, c)
    return best[0] if best else "point_of_interest"

def importance_weights(votes: Dict[str, int]) -> float:
    total = sum(votes.values()) or 1
    return (
        1.0 * votes.get("primary", 0) +
        0.6 * votes.get("secondary", 0) +
        0.3 * votes.get("hidden_gem", 0)
    ) / total

def confidence_from(f: int, votes: Dict[str,int], mean_narr: float) -> float:
    consensus = min(1.0, f / 3.0)
    imp = importance_weights(votes)
    story = (mean_narr or 0.0) / 5.0
    return round(0.40*consensus + 0.35*imp + 0.25*story, 4)

def consensus_label_from(f: int) -> str:
    return "unanimous" if f >= 3 else ("majority" if f == 2 else "single")

def status_rank(s: Optional[str]) -> int:
    return STATUS_PRIORITY.get((s or "raw"), 0)

def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def default_meta():
    return {
        "schema_version": "1",
        "city": None,
        "tour_title": None,
        "merged_selection_runs": [],
        "merged_refine_batches": [],
        "last_updated": now_iso(),
    }

def append_log_evt(evt: dict):
    REFINEMENT_FILES["log"].parent.mkdir(parents=True, exist_ok=True)
    evt["ts"] = now_iso()
    with open(REFINEMENT_FILES["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(evt, ensure_ascii=False) + "\n")

def backup_current_pois(src_path: Path, loop_id: int):
    if not src_path.exists():
        return
    dst = REFINEMENT_FILES["backups"] / f"current_pois_{loop_id:04d}.json"
    shutil.copyfile(src_path, dst)        

# --- Tour lock helpers ---
def tour_locked(meta: dict) -> bool:
    return bool(meta.get("city")) and bool(meta.get("tour_title"))

def same_tour(meta: dict, city: str, title: str) -> bool:
    if not city or not title:
        return True  # tolerate missing fields in older runs
    return (meta.get("city") == city) and (meta.get("tour_title") == title)

def _pick_soft_match_index(norm_key: str, name_index: dict, pois: list) -> int | None:
    """
    Find a single best index using containment first, then fuzzy.
    Returns a single poi index or None if ambiguous/not found.
    """
    # 1) containment pass
    candidate_idxs = set()
    for key, idxs in name_index.items():
        if not key:
            continue
        if norm_key.startswith(key) or key.startswith(norm_key) or (key in norm_key) or (norm_key in key):
            for i in idxs:
                candidate_idxs.add(i)
    if len(candidate_idxs) == 1:
        return next(iter(candidate_idxs))
    if len(candidate_idxs) > 1:
        return None  # ambiguous

    # 2) fuzzy pass over keys that map to exactly one poi index
    from difflib import SequenceMatcher
    best_score, best_idx = -1.0, None
    second_best = -1.0
    for key, idxs in name_index.items():
        if not key or len(idxs) != 1:
            continue  # skip ambiguous keys
        r = SequenceMatcher(None, norm_key, key).ratio()
        if r > best_score:
            second_best = best_score
            best_score, best_idx = r, idxs[0]
        elif r > second_best:
            second_best = r

    if best_score >= NAME_SIM_THRESHOLD and (best_score - second_best) >= NAME_SIM_MARGIN:
        return best_idx
    return None

def apply_refinement_proposals(current: dict, proposals: list) -> dict:
    """
    Mutates current['pois'] in-place.
    Returns counters for logging.
    """
    pois = current.get("pois") or []
    # Build name/alt index
    name_index = {}  # norm_name -> [poi_idx,...]
    for i, p in enumerate(pois):
        keys = set()
        keys.add(normalize_key(p.get("name", "")))
        for alt in (p.get("alt_names") or []):
            keys.add(normalize_key(alt))
        for k in keys:
            if not k: continue
            name_index.setdefault(k, []).append(i)

    # Simple unique slug helper (reuse yours if present)
    def ensure_unique_slug(base: str, existing_slugs: set) -> str:
        slug = base
        n = 2
        while slug in existing_slugs:
            slug = f"{base}-{n}"
            n += 1
        return slug

    # Existing slugs set
    existing_slugs = {p.get("poi_id") for p in pois if p.get("poi_id")}
    existing_slugs = {s for s in existing_slugs if s}

    # Deduper for “new” insertions by name
    existing_name_keys = set(name_index.keys())

    c = dict(
        proposals_total=0,
        applied_fixes=0,
        inserted_new=0,
        skipped_unmatched_fix=0,
        skipped_duplicate_new=0,
        skipped_keep_match=0,
        skipped_ambiguous_fix=0,
        type_coerced=0,
    )

    # Coerce type if outside your enum
    VALID_TYPES = {
        "point_of_interest","museum","church","monument","site","park",
        "building","memorial","trail","plaque","other"
    }

    def coerce_type(t):
        nonlocal c
        if not t or t not in VALID_TYPES:
            c["type_coerced"] += 1
            return "other"
        return t

    for prop in proposals or []:
        c["proposals_total"] += 1

        # Validate minimal fields
        if not isinstance(prop, dict):
            continue
        name = (prop.get("name") or "").strip()
        addr = (prop.get("address") or "").strip()
        typ  = coerce_type((prop.get("type") or "").strip())

        if not name or not addr or not typ:
            # incomplete proposal, skip quietly
            continue

        refined = bool(prop.get("gpt_refined"))
        norm = normalize_key(name)

        if refined:
            # FIX: find existing by name/alt-name (exact normalized key)
            idxs = name_index.get(norm, [])
            if not idxs:
                # try soft match (containment → fuzzy)
                soft_i = _pick_soft_match_index(norm, name_index, pois)
                if soft_i is None:
                    c["skipped_unmatched_fix"] += 1
                    continue
                idxs = [soft_i]

            if len(idxs) > 1:
                c["skipped_ambiguous_fix"] += 1
                continue

            i = idxs[0]
            tgt = pois[i]

            # Don’t overwrite finalized KEEP
            if (tgt.get("status") or "").lower() == "keep":
                c["skipped_keep_match"] += 1
                continue

            # Update only the editable content fields
            # If name changed, push previous into alt_names
            prev_name = tgt.get("name")
            if name and name != prev_name and prev_name:
                alts = (tgt.get("alt_names") or []) + [prev_name]
                # dedupe, compact
                dedup = []
                seen = set()
                for a in alts:
                    k = normalize_key(a)
                    if k and k not in seen:
                        seen.add(k)
                        dedup.append(a)
                tgt["alt_names"] = dedup

            tgt["name"] = name
            tgt["address"] = addr
            tgt["type"] = typ

            # optional fields if present
            for k in ("alt_names","importance","narration_score","teaser","sources"):
                if k in prop and prop[k] is not None:
                    tgt[k] = prop[k]

            # Clear stale validation artifacts and mark as refined
            tgt["reasons"] = []
            tgt.pop("validation_debug", None)
            tgt.pop("lat", None)
            tgt.pop("lng", None)
            tgt.pop("place", None)

            if "teaser" in prop and prop["teaser"]:
                tgt["teaser"] = clean_teaser(prop["teaser"])

            # Recompute flags from the new fields
            tgt.setdefault("flags", {})
            tgt["flags"]["address_needs_refine"] = address_needs_refine(addr)

            # Default: trust refined (validator should just geocode + outlier check)
            tgt["status"] = "gpt_refined"

            # Safety fallback: if the address looks non-visitable (route-like / no anchor),
            # keep it as 'recheck' so the validator can try to resolve it more carefully.
            _non_visitable = (
                not re.search(r"\d", addr) and                       # no street number
                not re.search(r"\b(Square|Pier|Park|Building|Cathedral|Fountain|Library|Mint|Wharf)\b", addr, re.I)
            )
            if tgt["flags"]["address_needs_refine"] or _non_visitable:
                tgt["status"] = "recheck"

            # Provenance
            tgt.setdefault("merge_debug", {}).update({
                "from": "gpt_refined",
                "ts": now_iso(),
                "schema": "poi_candidates@v7"
            })


            # Refresh index with potential new name
            new_norms = {normalize_key(tgt.get("name",""))}
            for a in (tgt.get("alt_names") or []):
                new_norms.add(normalize_key(a))
            for key in new_norms:
                if not key: continue
                name_index.setdefault(key, [])
                if i not in name_index[key]:
                    name_index[key].append(i)

            c["applied_fixes"] += 1
        else:
            # NEW: same rules as your initial merge for brand-new entries
            if norm in existing_name_keys:
                c["skipped_duplicate_new"] += 1
                continue

            # Build the new POI shell
            new_p = {
                "name": name,
                "address": addr,
                "type": typ,
                "alt_names": prop.get("alt_names") or [],
                "importance": prop.get("importance") or "secondary",
                "narration_score": prop.get("narration_score") or 3,
                "teaser": prop.get("teaser") or "",
                "sources": prop.get("sources") or [],
                "status": "raw",  # same as first-time merge behavior
                "name_source": "gpt_refinement",
                "merge_debug": {"from": "gpt_new", "ts": now_iso(), "schema": "poi_candidates@v7"},
            }

            # slug (reuse your slugify if present)
            base = re.sub(r"[^a-z0-9\-]+", "", re.sub(r"\s+", "-", name.strip().lower()))
            base = base or "poi"
            slug = ensure_unique_slug(base, existing_slugs)
            new_p["poi_id"] = slug
            existing_slugs.add(slug)

            pois.append(new_p)
            existing_name_keys.add(norm)
            name_index.setdefault(norm, []).append(len(pois)-1)
            c["inserted_new"] += 1

    return c

# --- Canonical-name helper (GPT wins → then pool → deterministic tie-break) ---
NICK_RX = re.compile(r"^(old|former|historic)\b", re.I)

def _tie_score(norm_key: str, names_pool: list[str]) -> float:
    # recover a representative original-casing string
    pool_norm_map = {normalize_key(n): n for n in names_pool}
    s = pool_norm_map.get(norm_key, "")
    toks = [t for t in re.split(r"\s+", s.strip()) if t]
    score = 0.0
    score += 1.0 if 2 <= len(toks) <= 4 else 0.0       # concise length
    score += 1.0 if has_type_noun(s) else 0.0          # contains a type noun
    score -= 1.0 if NICK_RX.search(s) else 0.0         # penalize nicknamey prefixes
    score -= 0.001 * len(s)                            # tiny nudge to shorter
    return score

def choose_canonical_name(rec: dict, g) -> tuple[str, str, dict, dict, list[str]]:
    """
    Returns (winner_name, rule_used, gpt_counts_norm, pool_counts_norm, other_names_list)

    Rules:
      1) GPT unanimous -> winner
      2) GPT majority (>50% of group) -> winner
      3) Else most frequent in pool (existing name+alts + group primary+alts). Tie → _tie_score.
    """

    names_pool = [rec.get("name","")] + (rec.get("alt_names") or []) + g.all_names()
    names_pool = [n for n in names_pool if n and n.strip()]
    norm = normalize_key

    # counts from GPT *primary* names
    gpt_primary = [it.name for it in g.items if getattr(it, "name", None)]
    gpt_counts = Counter(norm(n) for n in gpt_primary if n)
    pool_counts = Counter(norm(n) for n in names_pool)

    # 1) GPT unanimous
    if gpt_counts:
        total = sum(gpt_counts.values())
        top_norm, top_count = gpt_counts.most_common(1)[0]
        if top_count == total:
            winner_norm, rule = top_norm, "gpt_unanimous"
        elif top_count > total / 2.0:
            # 2) GPT majority
            winner_norm, rule = top_norm, "gpt_majority"
        else:
            # 3) Pool most common
            maxc = max(pool_counts.values()) if pool_counts else 0
            tied = [k for k,v in pool_counts.items() if v == maxc]
            if len(tied) == 1:
                winner_norm, rule = tied[0], "pool_most_common"
            else:
                winner_norm = max(tied, key=lambda k: _tie_score(k, names_pool))
                rule = "pool_tie_break"
    else:
        # no GPT names (rare): fall back to pool
        if pool_counts:
            maxc = max(pool_counts.values())
            tied = [k for k,v in pool_counts.items() if v == maxc]
            if len(tied) == 1:
                winner_norm, rule = tied[0], "pool_most_common"
            else:
                winner_norm = max(tied, key=lambda k: _tie_score(k, names_pool))
                rule = "pool_tie_break"
        else:
            # empty pool (extremely rare)
            winner = rec.get("name") or "Unnamed place"
            return winner, "empty_pool", dict(gpt_counts), dict(pool_counts), []

    # reconstruct winner with original casing (prefer pool, then GPT)
    norm_map_pool = {norm(n): n for n in names_pool}
    winner = norm_map_pool.get(winner_norm)
    if not winner and gpt_primary:
        norm_map_gpt = {norm(n): n for n in gpt_primary}
        winner = norm_map_gpt.get(winner_norm, winner_norm)

    # the rest become alt_names
    other_names, seen = [], {winner_norm}
    for n in names_pool:
        k = norm(n)
        if k not in seen:
            other_names.append(n); seen.add(k)

    return winner, rule, dict(gpt_counts), dict(pool_counts), other_names


# --- Canonical-name scoring helpers ---
GENERIC_QUALIFIERS_RX = re.compile(r"\b(viewing area|trail medallion route|historic bar|museum wing)\b", re.I)
ACRONYM_RX = re.compile(r"^[A-Z]{2,4}$")  # e.g., BCT
PARENS_SLASH_RX = re.compile(r"[()/®]")

def is_acronym(s: str) -> bool:
    return bool(ACRONYM_RX.match(s.strip()))

def is_nicknamey(s: str) -> bool:
    return s.strip().lower().startswith("the ")  # e.g., "The Granite Lady"

def name_tokens(s: str) -> list:
    return [w for w in re.split(r"[^\w]+", s or "") if w]

def pick_canonical_name(candidates: list[str], addr_hint: str = "") -> str:
    if not candidates:
        return "Unnamed place"

    
    # Build an augmented set: originals + normalized bases
    aug = []
    seen = set()
    for nm in (candidates or []):
        nm = (nm or "").strip()
        if not nm:
            continue
        if nm not in seen:
            aug.append(nm); seen.add(nm)
        base = normalize_base_name(nm)
        if base and base.lower() != nm.lower() and base not in seen:
            aug.append(base); seen.add(base)

    # frequency (over augmented list)
    freq = {}
    for nm in aug:
        freq[nm] = freq.get(nm, 0) + 1

    addr_l = (addr_hint or "").lower()

    FREQ_W = 40            # ↓ from 100
    TYPE_BONUS = 12
    HINT_PREFIX_BONUS = 12
    HINT_TOKEN_BONUS = 6
    LEN_PENALTY5 = 2
    LEN_PENALTY6 = 5

    def score(nm: str):
        f = freq.get(nm, 0)
        s = FREQ_W * f
        words = name_tokens(nm)
        nm_l = nm.lower()

        # bonuses: proper length, type nouns, hint/address alignment
        if 2 <= len(words) <= 4: s += 8
        if has_type_noun(nm): s += TYPE_BONUS
        if addr_l.startswith(nm_l): s += HINT_PREFIX_BONUS
        if any(w.lower() in addr_l for w in words[:3]): s += HINT_TOKEN_BONUS

        # penalties: acronyms, nicknamey (“The …”) without type noun, noisy punctuation, generic qualifiers, over/under length
        if is_acronym(nm): s -= 35                    # ↑ stronger
        if is_nicknamey(nm) and not has_type_noun(nm): s -= 20
        if PARENS_SLASH_RX.search(nm): s -= 10
        if GENERIC_QUALIFIERS_RX.search(nm) or WALKING_ROUTE_RX.search(nm): s -= 8
        if len(words) == 1 and nm_l not in {"coit tower","transamerica","ferry"}: s -= 4
        if len(words) > 6: s -= LEN_PENALTY6
        elif len(words) > 5: s -= LEN_PENALTY5

        return (s, -len(nm), nm_l)

    return sorted(freq.keys(), key=score, reverse=True)[0]


def normalize_poi(p: dict) -> dict:
    q = dict(p)

    # Ensure poi_id
    if not q.get("poi_id"):
        q["poi_id"] = slugify(q.get("name", "poi"))

    # Ensure name (derive from poi_id if missing)
    nm = (q.get("name") or "").strip()
    if not nm:
        base = (q.get("poi_id") or "poi").replace("-", " ").strip()
        nm = base.title() if base else "Unnamed place"
    q["name"] = nm

    # alt_names normalized & deduped
    alts = q.get("alt_names") or []
    if not isinstance(alts, list):
        alts = [str(alts)]
    q["alt_names"] = dedupe_preserve([a for a in alts if a])

    # Clean address / type / teaser
    if q.get("address"):
        q["address"] = clean_address(q["address"])
    if q.get("type"):
        t = str(q["type"]).lower()
        if "trail" in t:
            t = "trail"
        q["type"] = t
    if q.get("teaser"):
        q["teaser"] = clean_teaser(q["teaser"])

    # Status & analytics defaults
    q["status"] = q.get("status") or "raw"
    q.setdefault("appeared_in", [])
    q.setdefault("importance_votes", {"primary": 0, "secondary": 0, "hidden_gem": 0})
    if "narration" not in q:
        ns = int(q.get("narration_score") or 0)
        q["narration"] = {
            "mean": float(ns) if ns else 0.0,
            "var": 0.0,
            "passes": 1 if ns else 0
        }
    q.setdefault("confidence", 0.0)
    q.setdefault("consensus_label", "single")

    return q


def normalize_stops_to_pois(stops) -> list:
    if not isinstance(stops, list):
        return []
    pois = []
    for p in stops:
        if not isinstance(p, dict): 
            continue
        pois.append(normalize_poi(p))
    return pois

def ensure_current_structure(obj) -> dict:
    """
    Accepts:
      - new format: {"meta": {...}, "pois": [...]}
      - legacy: {"stops": [...]}
      - legacy: [ ... ]  (list of POIs)
      - anything else → new empty structure
    Returns new-format dict.
    """
    # list-only legacy
    if isinstance(obj, list):
        return {"meta": default_meta(), "pois": normalize_stops_to_pois(obj)}
    # dict shapes
    if isinstance(obj, dict):
        if "meta" in obj and "pois" in obj:
            # ensure meta has required keys and normalize pois
            m = obj["meta"] if isinstance(obj["meta"], dict) else {}
            obj["meta"] = {
                "schema_version": m.get("schema_version","1"),
                "city": m.get("city"),
                "tour_title": m.get("tour_title"),
                "merged_selection_runs": m.get("merged_selection_runs", []),
                "merged_refine_batches": m.get("merged_refine_batches", []),
                "last_updated": m.get("last_updated", now_iso()),
            }
            obj["pois"] = normalize_stops_to_pois(obj.get("pois", []))
            return obj
        # legacy with "stops"
        if "stops" in obj:
            return {"meta": default_meta(), "pois": normalize_stops_to_pois(obj["stops"])}
    # fallback new empty
    return {"meta": default_meta(), "pois": []}

# ------------- Data structures -------------
@dataclass
class IncomingPOI:
    name: str
    alt_names: List[str]
    address: str
    type: str
    importance: str
    narration_score: int
    teaser: str
    pass_label: str  # e.g., "A","B","C","Refine_Add"
    run_or_batch_id: str

@dataclass
class Group:
    items: List[IncomingPOI] = field(default_factory=list)

    def all_names(self) -> List[str]:
        names = []
        for it in self.items:
            names.append(it.name)
            names += it.alt_names
        return names

    def all_types(self) -> List[str]:
        return [it.type for it in self.items if it.type]

    def passes_set(self) -> List[str]:
        return sorted({it.pass_label for it in self.items})

    def importance_votes(self) -> Dict[str,int]:
        votes = {"primary":0, "secondary":0, "hidden_gem":0}
        for it in self.items:
            if it.importance in votes:
                votes[it.importance] += 1
        return votes

    def narration_stats(self) -> Tuple[int, float, float]:
        xs = [float(it.narration_score) for it in self.items if it.narration_score is not None]
        if not xs:
            return 0, 0.0, 0.0
        n = len(xs)
        s = sum(xs)
        mean = s / n
        sumsq = sum(x*x for x in xs)
        var = max(0.0, sumsq/n - mean*mean)
        return n, round(mean,3), round(var,3)

    def canonical_name(self) -> str:
        names = [n for n in self.all_names() if n.strip()]
        addr = self.canonical_address()
        return pick_canonical_name(names, addr_hint=addr)

    def canonical_address(self) -> str:
        cands = [clean_address(it.address) for it in self.items if it.address]
        if not cands:
            return ""
        def addr_score(a: str) -> Tuple[int,int]:
            has_num = 1 if re.search(r"\d", a) else 0
            is_vague = 1 if address_needs_refine(a) else 0
            return (has_num - is_vague, -len(a))
        return sorted(cands, key=addr_score, reverse=True)[0]


# ------------- Matching / grouping -------------
def group_items(items: List[IncomingPOI]) -> List[Group]:
    groups: List[Group] = []
    for it in items:
        placed = False
        for g in groups:
            if any(name_sim(it.name, n) >= NAME_SIM_THRESHOLD for n in g.all_names()):
                g.items.append(it); placed = True; break
            ca = clean_address(it.address)
            if ca and any(clean_address(j.address) == ca for j in g.items):
                g.items.append(it); placed = True; break
        if not placed:
            groups.append(Group(items=[it]))
    return groups

def match_group_to_existing(group: Group, existing_by_id: Dict[str, Any]) -> Optional[str]:
    can_name = group.canonical_name()
    can_addr = clean_address(group.canonical_address())
    for pid, rec in existing_by_id.items():
        names = [rec.get("name","")] + rec.get("alt_names", [])
        if any(name_sim(can_name, n) >= NAME_SIM_THRESHOLD for n in names):
            return pid
        if can_addr and clean_address(rec.get("address","")) == can_addr:
            return pid
    return None

# ------------- Merge selection runs -------------
def merge_selection_runs(gpt_output: Dict[str, Any], current: Dict[str, Any], metrics: Dict[str,Any]) -> None:
    meta = current["meta"]
    merged_runs: List[str] = meta.get("merged_selection_runs", [])
    runs = [r for r in gpt_output.get("runs", []) if r.get("run_id") not in merged_runs]
    if not runs:
        return

    # Initialize meta city/title if missing
    if meta.get("city") is None:
        meta["city"] = runs[0].get("inputs",{}).get("city")
    if meta.get("tour_title") is None:
        meta["tour_title"] = runs[0].get("inputs",{}).get("tour_title")

    # Parse incoming selection POIs
    incoming: List[IncomingPOI] = []
    for r in runs:
        pass_label = r.get("pass","") or "Sel"
        run_id = r.get("run_id") or ""
        for p in r.get("pois", []) or []:
            name = (p.get("name") or "").strip()
            if not name: continue
            alt = [a for a in p.get("alt_names", []) or [] if a]
            incoming.append(IncomingPOI(
                name=name,
                alt_names=alt,
                address=p.get("address",""),
                type=(p.get("type") or "point_of_interest").lower(),
                importance=(p.get("importance") or "secondary").lower(),
                narration_score=int(p.get("narration_score") or 0),
                teaser=p.get("teaser",""),
                pass_label=pass_label,
                run_or_batch_id=run_id,
            ))

    # Group within this selection ingestion
    groups = group_items(incoming)

    # Index current by poi_id (ensure every rec has an id)
    existing_by_id: Dict[str, Any] = {p["poi_id"]: p for p in current.get("pois", []) if "poi_id" in p}
    for p in current.get("pois", []):
        if "poi_id" not in p:
            p["poi_id"] = slugify(p.get("name","poi"))
            existing_by_id[p["poi_id"]] = p

    added = 0
    updated = 0

    for g in groups:
        # precompute everything that doesn't depend on rec
        passes = g.passes_set()
        f = len(passes)
        votes = g.importance_votes()
        n_count, n_mean, n_var = g.narration_stats()
        can_name = g.canonical_name()
        can_addr = g.canonical_address()
        type_major = majority_type(g.all_types())
        flags = {"address_needs_refine": address_needs_refine(can_addr)}
        conf = confidence_from(f, votes, n_mean)
        t_new = clean_teaser((g.items[0].teaser if g.items else "") or "")

        pid_match = match_group_to_existing(g, existing_by_id)

        if pid_match:
            # ---- update existing record ----
            rec = existing_by_id[pid_match]
            rec.setdefault("flags", {})

            # Canonical name from pool (existing + new)
            winner, rule, gpt_counts, pool_counts, other_names = choose_canonical_name(rec, g)
            rec["name"] = winner
            rec["alt_names"] = dedupe_preserve(other_names, cap=MAX_ALT_NAMES)

            # log to tour_log.jsonl
            append_log_evt({
                "stage": "canonical_name_decision",
                "poi_id": rec.get("poi_id"),
                "rule_used": rule,
                "winner": winner,
                "gpt_counts": gpt_counts,
                "pool_top": dict(sorted(pool_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]),
                "group_size": len(g.items),
                "passes": g.passes_set(),
            })

            # Address (pick best)
            cand_addrs = [clean_address(rec.get("address","")), can_addr]
            cand_addrs = [a for a in cand_addrs if a]
            if cand_addrs:
                def addr_score(a: str):
                    has_num = 1 if re.search(r"\d", a) else 0
                    is_vague = 1 if address_needs_refine(a) else 0
                    return (has_num - is_vague, -len(a))
                best_addr = sorted(cand_addrs, key=addr_score, reverse=True)[0]
                rec["address"] = best_addr
                rec["flags"]["address_needs_refine"] = address_needs_refine(best_addr)

            # Type & teaser
            rec["type"] = majority_type([rec.get("type")] + g.all_types())
            t_old = clean_teaser(rec.get("teaser","") or "")
            rec["teaser"] = t_old if t_old and len(t_old) <= len(t_new) else (t_new or t_old)

            # Ensemble fields
            rec["appeared_in"] = sorted(set((rec.get("appeared_in") or []) + passes))

            iv = rec.get("importance_votes") or {"primary":0,"secondary":0,"hidden_gem":0}
            for k, v in votes.items():
                iv[k] = iv.get(k, 0) + v
            rec["importance_votes"] = iv

            stats = rec.get("_narration_stats") or {"sum":0.0,"sumsq":0.0,"n":0}
            stats["sum"]   += n_mean * n_count
            stats["sumsq"] += (n_var + n_mean*n_mean) * n_count
            stats["n"]     += n_count
            rec["_narration_stats"] = stats

            if stats["n"] > 0:
                mean = stats["sum"]/stats["n"]
                var  = max(0.0, stats["sumsq"]/stats["n"] - mean*mean)
            else:
                mean, var = 0.0, 0.0
            rec["narration"] = {"mean": round(mean,3), "var": round(var,3), "passes": int(stats["n"])}

            f2 = len(rec["appeared_in"])
            rec["consensus_label"] = consensus_label_from(f2)
            rec["confidence"] = confidence_from(f2, rec["importance_votes"], rec["narration"]["mean"])

            # Provenance
            prov = rec.get("provenance") or {}
            prov.setdefault("first_seen_run", runs[0].get("run_id"))
            prov["last_seen_run"] = runs[-1].get("run_id")
            prov["last_update"] = now_iso()
            rec["provenance"] = prov

            updated += 1

        else:
            # ---- create new record ----
            # Decide canonical name using GPT-first rule (unanimous/majority → winner; else pool most-common)
            _tmp_rec = {"name": "", "alt_names": []}
            winner, rule, gpt_counts, pool_counts, other_names = choose_canonical_name(_tmp_rec, g)
            canonical_name = winner
            alt_names = dedupe_preserve(other_names, cap=MAX_ALT_NAMES)

            # audit
            append_log_evt({
                "stage": "canonical_name_decision",
                "source": "selection_new",
                "rule_used": rule,
                "winner": canonical_name,
                "gpt_counts": gpt_counts,
                "pool_top": dict(sorted(pool_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]),
                "group_size": len(g.items),
                "passes": g.passes_set(),
            })

            base_pid = slugify(canonical_name)
            pid = base_pid
            while pid in existing_by_id:
                pid = f"{base_pid}-{short_hash(can_addr or canonical_name)}"
                if pid in existing_by_id:
                    pid = f"{base_pid}-{short_hash(pid+'x')}"

            mean, var = n_mean, n_var

            rec = {
                "poi_id": pid,
                "name": canonical_name,
                "alt_names": alt_names,
                "address": can_addr,
                "type": type_major,
                "teaser": t_new,
                "importance_votes": votes,
                "narration": {"mean": round(mean,3), "var": round(var,3), "passes": int(n_count)},
                "_narration_stats": {"sum": n_mean*n_count, "sumsq": (n_var + n_mean*n_mean)*n_count, "n": n_count},
                "appeared_in": passes,
                "consensus_label": consensus_label_from(f),
                "confidence": conf,
                "status": "raw",
                "provenance": {
                    "first_seen_run": (incoming[0].run_or_batch_id if incoming else None),
                    "last_seen_run": (incoming[-1].run_or_batch_id if incoming else None),
                    "last_update": now_iso(),
                },
                "flags": dict(flags),
            }

            existing_by_id[pid] = rec
            current["pois"].append(rec)
            added += 1

    # Record merged run ids
    meta["merged_selection_runs"] = merged_runs + [r.get("run_id") for r in runs]
    metrics["selection_added"] = metrics.get("selection_added", 0) + added
    metrics["selection_updated"] = metrics.get("selection_updated", 0) + updated
    append_log_evt({
    "stage": "merge_selection_runs",
    "added": added,
    "updated": updated,
    "merged_runs": current["meta"].get("merged_selection_runs", []),
    })

# ------------- Merge refine batches -------------
def coerce_batches(obj: Any) -> List[Dict[str,Any]]:
    # Accept a single batch object, {"batches":[...]}, or a list of batches
    if isinstance(obj, dict) and "batches" in obj and isinstance(obj["batches"], list):
        return obj["batches"]
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and "batch_id" in obj:
        return [obj]
    return []

def merge_refine_batches(refine_obj: Dict[str,Any], current: Dict[str,Any], metrics: Dict[str,Any]) -> None:
    batches = coerce_batches(refine_obj)
    if not batches:
        return

    meta = current["meta"]
    merged_batches: List[str] = meta.get("merged_refine_batches", [])
    existing_by_id: Dict[str, Any] = {p["poi_id"]: p for p in current.get("pois", []) if "poi_id" in p}

    added = 0
    updated = 0
    ignored_unknown = 0
    locked_ignored = 0
    drop_suggested = 0
    needs_more = 0
    new_merged = 0

    for b in batches:
        batch_id = b.get("batch_id")
        if not batch_id or batch_id in merged_batches:
            continue

        # ---- explicit actions ----
        for it in b.get("items", []) or []:
            pid = it.get("poi_id")
            action = (it.get("action") or "").lower()
            fields = it.get("fields") or {}
            reason = it.get("reason")
            rec = existing_by_id.get(pid)

            if rec is None:
                ignored_unknown += 1
                continue

            # never modify locked statuses
            if rec.get("status") in ("keep","drop"):
                locked_ignored += 1
                continue

            if action == "approve":
                rec["status"] = "gpt_refined"
                rec.setdefault("provenance", {})
                rec["provenance"]["last_seen_batch"] = batch_id
                rec["provenance"]["last_update"] = now_iso()
                updated += 1

            elif action == "update":
                # Apply partial patch (sanitize fields)
                if "name" in fields:
                    old_name = rec.get("name","")
                    new_name = (fields["name"] or "").strip()
                    if new_name and new_name != old_name:
                        # keep stable poi_id, move old name to alts
                        rec["name"] = new_name
                        rec["alt_names"] = dedupe_preserve([old_name] + rec.get("alt_names", []), cap=MAX_ALT_NAMES)
                if "alt_names" in fields and isinstance(fields["alt_names"], list):
                    rec["alt_names"] = dedupe_preserve(list(fields["alt_names"]) + rec.get("alt_names", []), cap=MAX_ALT_NAMES)
                if "address" in fields:
                    addr = clean_address(fields["address"])
                    rec["address"] = addr
                    rec.setdefault("flags", {})
                    rec["flags"]["address_needs_refine"] = address_needs_refine(addr)
                if "type" in fields:
                    t = (fields["type"] or "").lower()
                    if "trail" in t: t = "trail"
                    rec["type"] = t or rec.get("type","point_of_interest")
                if "teaser" in fields and fields["teaser"]:
                    rec["teaser"] = clean_teaser(fields["teaser"])
                # mark refined
                rec["status"] = "gpt_refined"
                rec.setdefault("provenance", {})
                rec["provenance"]["last_seen_batch"] = batch_id
                rec["provenance"]["last_update"] = now_iso()
                updated += 1

            elif action == "drop":
                rec.setdefault("flags", {})
                rec["flags"]["gpt_drop_suggested"] = True
                if reason:
                    rec["flags"]["gpt_drop_reason"] = reason
                rec.setdefault("provenance", {})
                rec["provenance"]["last_seen_batch"] = batch_id
                rec["provenance"]["last_update"] = now_iso()
                drop_suggested += 1

            elif action == "needs_more_info":
                rec.setdefault("flags", {})
                if reason:
                    rec["flags"]["needs_more_info_reason"] = reason
                rec.setdefault("provenance", {})
                rec["provenance"]["last_seen_batch"] = batch_id
                rec["provenance"]["last_update"] = now_iso()
                needs_more += 1

        # ---- optional new_pois (treat like mini selection) ----
        new_items: List[IncomingPOI] = []
        for p in b.get("new_pois", []) or []:
            name = (p.get("name") or "").strip()
            if not name: continue
            alt = [a for a in p.get("alt_names", []) or [] if a]
            new_items.append(IncomingPOI(
                name=name,
                alt_names=alt,
                address=p.get("address",""),
                type=(p.get("type") or "point_of_interest").lower(),
                importance=(p.get("importance") or "secondary").lower(),
                narration_score=int(p.get("narration_score") or 0),
                teaser=p.get("teaser",""),
                pass_label="Refine_Add",
                run_or_batch_id=batch_id,
            ))

        if new_items:
            groups = group_items(new_items)
            # rebuild existing_by_id (in case of prior updates)
            existing_by_id = {p["poi_id"]: p for p in current.get("pois", []) if p.get("poi_id")}

            for g in groups:
                pid_match = match_group_to_existing(g, existing_by_id)
                rec = None 
                t_new = clean_teaser((g.items[0].teaser if g.items else "") or "")
                passes = g.passes_set()
                f = len(passes)
                votes = g.importance_votes()
                n_count, n_mean, n_var = g.narration_stats()
                can_name = g.canonical_name()
                can_addr = g.canonical_address()
                type_major = majority_type(g.all_types())
                flags = {
                    "address_needs_refine": address_needs_refine(can_addr),
                }
                conf = confidence_from(f, votes, n_mean)

                if pid_match:
                    # ---- merge into existing record ----
                    rec = existing_by_id[pid_match]
                    rec.setdefault("flags", {})
                    # Canonical name (use scorer)
                    winner, rule, gpt_counts, pool_counts, other_names = choose_canonical_name(rec, g)
                    rec["name"] = winner
                    rec["alt_names"] = dedupe_preserve(other_names, cap=MAX_ALT_NAMES)

                    append_log_evt({
                        "stage": "canonical_name_decision",
                        "source": "refine",
                        "poi_id": rec.get("poi_id"),
                        "rule_used": rule,
                        "winner": winner,
                        "gpt_counts": gpt_counts,
                        "pool_top": dict(sorted(pool_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]),
                        "group_size": len(g.items),
                        "passes": g.passes_set(),
                    })

                    # Address
                    cand_addrs = [clean_address(rec.get("address","")), can_addr]
                    cand_addrs = [a for a in cand_addrs if a]
                    if cand_addrs:
                        def addr_score(a: str):
                            has_num = 1 if re.search(r"\d", a) else 0
                            is_vague = 1 if address_needs_refine(a) else 0
                            return (has_num - is_vague, -len(a))
                        best_addr = sorted(cand_addrs, key=addr_score, reverse=True)[0]
                        rec["address"] = best_addr
                        rec["flags"]["address_needs_refine"] = address_needs_refine(best_addr)

                    # Type, teaser
                    rec["type"] = majority_type([rec.get("type")] + g.all_types())
                    t_new = clean_teaser((g.items[0].teaser if g.items else "") or "")
                    t_old = clean_teaser(rec.get("teaser",""))
                    rec["teaser"] = t_old if t_old and len(t_old) <= len(t_new) else (t_new or t_old)
                    

                    # Ensemble updates
                    rec["appeared_in"] = sorted(set((rec.get("appeared_in") or []) + passes))
                    f2 = len(rec["appeared_in"])
                    iv = rec.get("importance_votes") or {"primary":0,"secondary":0,"hidden_gem":0}
                    for k, v in votes.items():
                        iv[k] = iv.get(k, 0) + v
                    rec["importance_votes"] = iv

                    stats = rec.get("_narration_stats") or {"sum":0.0,"sumsq":0.0,"n":0}
                    stats["sum"] += n_mean * n_count
                    stats["sumsq"] += (n_var + n_mean*n_mean) * n_count
                    stats["n"] += n_count
                    rec["_narration_stats"] = stats
                    if stats["n"] > 0:
                        mean = stats["sum"]/stats["n"]
                        var = max(0.0, stats["sumsq"]/stats["n"] - mean*mean)
                    else:
                        mean, var = 0.0, 0.0
                    rec["narration"] = {"mean": round(mean,3), "var": round(var,3), "passes": int(stats["n"])}
                    rec["consensus_label"] = consensus_label_from(f2)
                    rec["confidence"] = confidence_from(f2, rec["importance_votes"], rec["narration"]["mean"])

                    # Provenance
                    rec.setdefault("provenance", {})
                    rec["provenance"]["last_seen_batch"] = batch_id
                    rec["provenance"]["last_update"] = now_iso()

                    updated += 1

                else:
                    # ---- new record ----
                    # Decide canonical name using GPT-first rule (unanimous/majority → winner; else pool most-common)
                    _tmp_rec = {"name": "", "alt_names": []}
                    winner, rule, gpt_counts, pool_counts, other_names = choose_canonical_name(_tmp_rec, g)
                    canonical_name = winner
                    alt_names = dedupe_preserve(other_names, cap=MAX_ALT_NAMES)

                    # audit
                    append_log_evt({
                        "stage": "canonical_name_decision",
                        "source": "refine_new",
                        "rule_used": rule,
                        "winner": canonical_name,
                        "gpt_counts": gpt_counts,
                        "pool_top": dict(sorted(pool_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]),
                        "group_size": len(g.items),
                        "passes": g.passes_set(),
                    })

                    base_pid = slugify(canonical_name)
                    pid = base_pid
                    while pid in existing_by_id:
                        pid = f"{base_pid}-{short_hash(can_addr or canonical_name)}"
                        if pid in existing_by_id:
                            pid = f"{base_pid}-{short_hash(pid+'x')}"

                    mean, var = n_mean, n_var
                    t_new = clean_teaser((g.items[0].teaser if g.items else "") or "")
                    rec = {
                        "poi_id": pid,
                        "name": canonical_name,
                        "alt_names": alt_names,
                        "address": can_addr,
                        "type": type_major,
                        "importance_votes": votes,
                        "teaser": t_new,
                        "narration": {"mean": round(mean,3), "var": round(var,3), "passes": int(n_count)},
                        "_narration_stats": {"sum": n_mean*n_count, "sumsq": (n_var + n_mean*n_mean)*n_count, "n": n_count},
                        "appeared_in": passes,
                        "consensus_label": consensus_label_from(f),
                        "confidence": conf,
                        "status": "raw",
                        "provenance": {
                            "first_seen_batch": batch_id,
                            "last_seen_batch": batch_id,
                            "last_update": now_iso(),
                        },
                        "flags": flags,
                    }

                    current["pois"].append(rec)
                    existing_by_id[pid] = rec
                    new_merged += 1
                    added += 1

        merged_batches.append(batch_id)

    meta["merged_refine_batches"] = merged_batches
    metrics["refine_added"] = metrics.get("refine_added", 0) + added
    metrics["refine_updated"] = metrics.get("refine_updated", 0) + updated
    metrics["refine_ignored_unknown_id"] = metrics.get("refine_ignored_unknown_id", 0) + ignored_unknown
    metrics["refine_locked_ignored"] = metrics.get("refine_locked_ignored", 0) + locked_ignored
    metrics["refine_drop_suggested"] = metrics.get("refine_drop_suggested", 0) + drop_suggested
    metrics["refine_needs_more_info"] = metrics.get("refine_needs_more_info", 0) + needs_more
    metrics["refine_new_pois_created"] = metrics.get("refine_new_pois_created", 0) + new_merged
    append_log_evt({
    "stage": "merge_refine_batches",
    "added": added,
    "updated": updated,
    "ignored_unknown_id": ignored_unknown,
    "locked_ignored": locked_ignored,
    "drop_suggested": drop_suggested,
    "needs_more_info": needs_more,
    "new_pois_created": new_merged,
    "merged_batches": current["meta"].get("merged_refine_batches", []),
    })
# ------------- Orchestration -------------
def finalize_and_write(current: Dict[str,Any], out_path: Path, backup: bool) -> None:
    current = ensure_current_structure(current)
    # Recompute confidence sort, drop internal stats
    for r in current.get("pois", []):
        r.pop("_narration_stats", None)
    current["meta"]["last_updated"] = now_iso()
    # Sort: status priority → confidence desc → name
    current["pois"].sort(key=lambda r: (-status_rank(r.get("status")), -(r.get("confidence") or 0.0), r.get("name","")))

    # backup (only if requested)
    if backup:
        loop_id = 0
        try:
            loop_id = int((BASE / "loop_counter.txt").read_text().strip())
        except Exception:
            loop_id = 0
        backup_current_pois(out_path, loop_id)

    # Write
    write_json(out_path, current)

    # Metrics summary
    counts_by_status: Dict[str,int] = {}
    for r in current["pois"]:
        s = r.get("status","raw")
        counts_by_status[s] = counts_by_status.get(s,0) + 1

    append_log_evt({
        "stage": "merge_finalize",
        "last_updated": current["meta"]["last_updated"],
        "counts_by_status": counts_by_status,
        "total_pois": len(current["pois"]),
        "merged_selection_runs": current["meta"].get("merged_selection_runs", []),
        "merged_refine_batches": current["meta"].get("merged_refine_batches", []),
        "top_confidence_sample": [
            {"poi_id": r["poi_id"], "name": r["name"], "confidence": r.get("confidence"), "consensus": r.get("consensus_label")}
            for r in current["pois"][:10]
        ]
    })

def main():
    ap = argparse.ArgumentParser(description="Merge selection runs and refine batches into current_pois.json")
    ap.add_argument("--selection", default="src/data/gpt_output.json", help="Selection runs file (JSON with {'runs':[...]})")
    ap.add_argument("--refine", default="src/data/refine_output.json", help="Refine batches file (single batch, list, or {'batches':[...]}). Optional.")
    ap.add_argument("--current", default="src/data/current_pois.json", help="Existing current_pois.json (in/out)")
    ap.add_argument("--out", default="src/data/current_pois.json", help="Output path for merged current_pois.json")
    ap.add_argument("--backup", action="store_true", help="Backup current_pois.json before writing")
    args = ap.parse_args()

    sel_path = Path(args.selection)
    ref_path = Path(args.refine)
    cur_path = Path(args.current)
    out_path = Path(args.out)

    # Initialize current structure
    if cur_path.exists():
        current = read_json(cur_path)
    else:
        current = {"meta": {"schema_version":"1", "city": None, "tour_title": None,
                            "merged_selection_runs": [], "merged_refine_batches": [], "last_updated": now_iso()},
                   "pois": []}
        
    current = ensure_current_structure(current)
    rollup_metrics: Dict[str,Any] = {}

    # Merge selection runs (if file exists and has content)
    if sel_path.exists():
        try:
            gpt_output = read_json(sel_path)
            merge_selection_runs(gpt_output, current, rollup_metrics)
        except Exception as e:
            print(f"⚠️ selection merge skipped due to error: {e}")

    # Merge refine batches (optional)
    if ref_path.exists():
        try:
            refine_obj = read_json(ref_path)
            merge_refine_batches(refine_obj, current, rollup_metrics)
        except Exception as e:
            print(f"⚠️ refine merge skipped due to error: {e}")

    # ... your existing batch-merge completed; current holds {"meta":..., "pois":[...]}
        # ---- Apply proposals from gpt_output.json (if present) ----
    gpt_path = REFINEMENT_FILES["gpt_out"]
    if gpt_path.exists():
        try:
            gpt_obj = json.loads(gpt_path.read_text(encoding="utf-8"))
        except Exception:
            gpt_obj = {}

        proposals = gpt_obj.get("proposals") or gpt_obj.get("pois") or []
        if proposals:
            # Optional loop counter (for backup naming)
            loop_id = 0
            try:
                loop_id = int((BASE / "loop_counter.txt").read_text().strip() or "0")
            except Exception:
                pass

            # Backup BEFORE applying
            backup_current_pois(Path(args.current), loop_id)

            # Apply in-place to `current`
            counters = apply_refinement_proposals(current, proposals)

            # Log what happened; writing of current_pois.json happens in finalize_and_write
            append_log_evt({
                "stage": "merge",
                "source": "gpt_output",
                "loop_id": loop_id,
                **counters,
            })


    # Finalize & write
    finalize_and_write(current, out_path, backup=args.backup)
    print(f"✅ merged → {out_path}")
    print(f"   • selection runs: {len(current['meta'].get('merged_selection_runs',[]))}")
    print(f"   • refine batches: {len(current['meta'].get('merged_refine_batches',[]))}")
    print(f"   • total POIs: {len(current.get('pois',[]))}")

if __name__ == "__main__":
    main()
