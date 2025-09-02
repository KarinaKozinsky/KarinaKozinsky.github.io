#!/usr/bin/env python3
# pois_validation.py
# Validate & canonicalize POIs using Google Places:
# - Promotes Places display name/address
# - Sets name_source="google_places", name_locked=True
# - Generates unique slug (poi_id) from final name
# - Respects existing locked names
# - Writes back to { "meta": {...}, "pois": [...] }
#
# Requires:
#   pip install googlemaps python-dotenv rapidfuzz
# Env:
#   VITE_GOOGLE_API_KEY=<your key>

from __future__ import annotations
import os, re, json, argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import radians, cos, sin, asin, sqrt

from dotenv import load_dotenv
import googlemaps
import unicodedata
from rapidfuzz import fuzz

# ---------- CONFIG ----------
OUTLIER_RADIUS_METERS = 2200
PHRASE_THRESHOLD = 0.85
POINT_CAP_M = 100
WIDE_CAP_M = 400
WEAK_POINT_CAP_M = 600
WEAK_WIDE_CAP_M  = 800

ADDRESS_TOKENS = [
    "st", "ave", "blvd", "road", "dr", "pl", "lane", "way", "square", "court", "plaza",
    "park", "trail", "highway", "street", "avenue", "boulevard"
]

PURE_ADDRESS_RX = re.compile(
    r"^\s*\d{1,6}\s+[A-Za-z0-9.'-]+\s+"
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|ct|court|hwy|highway|pkwy|parkway|pl|place|ter|terrace|cir|circle|ctr|center|centre|sq|square|plz|plaza)"
    r"\b\.?(?:\s*,.*)?\s*$",
    re.I,
)

NUMERIC_NUMERIC_INT_RX = re.compile(
    r"^\s*\d{1,3}(?:st|nd|rd|th)?\s+"
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|ct|court|hwy|highway|pkwy|parkway|pl|place|ter|terrace|cir|circle|ctr|center|centre|sq|square|plz|plaza)"
    r"\s*(?:&|and|@|at)\s*"
    r"\d{1,3}(?:st|nd|rd|th)?\s+"
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|ct|court|hwy|highway|pkwy|parkway|pl|place|ter|terrace|cir|circle|ctr|center|centre|sq|square|plz|plaza)\s*$",
    re.I
)

WIDE_AREA_TYPE = [
    "port", "pier", "harbor","harbour", "wharf", "site", "park", "square", "plaza", "neighborhood", "area", "district", "historic_district", "natural_feature", 
      
]
ABBREV_VARIANTS = (
    (r"\bstreet\b",       "st"),
    (r"\bavenue\b",       "ave"),
    (r"\bboulevard\b",    "blvd"),
    (r"\broad\b",         "rd"),
    (r"\bdrive\b",        "dr"),
    (r"\bplace\b",        "pl"),
    (r"\blane\b",         "ln"),
    (r"\bcourt\b",        "ct"),
    (r"\bterrace\b",      "ter"),
    (r"\bparkway\b",      "pkwy"),
    (r"\bexpressway\b",   "expy"),
    (r"\bhighway\b",      "hwy"),
    (r"\bsquare\b",       "sq"),
    (r"\bplaza\b",        "plz"),
    (r"\bcircle\b",       "cir"),
    (r"\bcenter\b",       "ctr"),
    (r"\bcentre\b",       "ctr"),
    # geography / landmarks
    (r"\bfort\b",         "ft"),
    (r"\bmount\b",        "mt"),
    (r"\bmountain\b",     "mtn"),
)

# Map our POI types → acceptable Google types
GOOGLE_TYPE = {
    "trail":    {"route", "trail", "park", "tourist_attraction", "point_of_interest"},
    "park":     {"park", "tourist_attraction", "point_of_interest"},
    "museum":   {"museum", "tourist_attraction", "point_of_interest"},
    "church":   {"church", "temple", "place_of_worship", "tourist_attraction", "point_of_interest"},
    "building": {"premise","point_of_interest","tourist_attraction","establishment"},
    "site":     {"point_of_interest","tourist_attraction","natural_feature","neighborhood","park","premise"},
    "monument": {"point_of_interest", "tourist_attraction", "statue", "fountain", "obelisk", "column", "plaque"},
    "point_of_interest": {"point_of_interest"},

    # venues/food/nightlife
    "restaurant": {"restaurant", "food", "point_of_interest", "establishment"},
    "bar":        {"bar", "point_of_interest", "establishment"},
    "night_club": {"night_club", "bar", "point_of_interest", "establishment"},
    "cafe":       {"cafe", "food", "point_of_interest", "establishment"},
    "bakery":     {"bakery", "food", "point_of_interest", "establishment"},

    # waterfront/transport concept
    "port":       {"marina","transit_station","point_of_interest","tourist_attraction","establishment"},
}

# Generic Google types that are too weak alone; require a supporting noun in name/address
WEAK_GENERIC_TYPES = {"point_of_interest", "tourist_attraction", "establishment"}

# Nouns we’ll accept in name/address when only weak generics matched
TYPE_NOUNS = {
    "trail":    ["trail", "route", "walk"],
    "park":     ["park", "greenway"],
    "museum":   ["museum"],
    "church":   ["church", "cathedral", "basilica", "temple"],
    "building": ["building", "hall", "tower", "mint", "fort"],
    "site":     ["square", "district", "area", "neighborhood", "site", "plaza", "center"],
    "monument": ["monument", "memorial", "statue", "fountain", "obelisk", "column", "plaque"],
    "restaurant":["restaurant", "diner", "eatery", "bistro"],
    "bar":      ["bar", "pub", "tavern", "saloon"],
    "night_club":["nightclub", "club"],
    "cafe":     ["cafe", "coffee"],
    "bakery":   ["bakery", "bakeshop"],
    "port":     ["port", "pier", "dock", "harbor", "harbour", "wharf", "marina", "ferry"],
    "point_of_interest": [],
}

# Treat these Google types as clearly "business-like" listings
_BUSINESS_TYPES = {
    "restaurant","bar","cafe","bakery","food","lodging","hotel","motel",
    "store","convenience_store","supermarket","shopping_mall","point_of_sale"
}
# Treat these as "institutional" (can close as an org even if landmark remains)
_INSTITUTIONAL_TYPES = {
    "museum","library","school","university","church","place_of_worship","synagogue","hindu_temple","mosque"
}
# Curate nouns allowed to override CLOSED_PERMANENTLY when the physical landmark persists
_LANDMARK_TYPES = {"park", "site", "monument", "building", "port", "trail"}

_LANDMARK_NOUNS = set().union(
    *(TYPE_NOUNS[t] for t in _LANDMARK_TYPES if t in TYPE_NOUNS)
)

# Prune overly generic/ambiguous tokens that can cause false positives
_LANDMARK_NOUNS -= {"building", "area", "neighborhood", "center", "site"}

# Add a few reliable landmark nouns explicitly
_LANDMARK_NOUNS.update({
    "square", "plaza", "wharf", "dock", "harbor", "harbour", "pier",
    "fountain", "statue", "obelisk", "column", "plaque",
    "tower", "fort", "mint", "greenway", "route", "walk", "trail",
})


CLEAN_PARENS_RX = re.compile(r"\([^)]*\)")
BIAS_RX = re.compile(r"circle:(\d+)\@([\-0-9.]+),([\-0-9.]+)")
_ADDR_TAIL_RX = re.compile(r",?\s*(usa|united states)\.?$", re.I)
_ZIP_RX       = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_SUITE_RX     = re.compile(r"(?:#\s*\w+|\bste\.?\s*\w+|\bsuite\s+\w+)", re.I)

# ---------- ENV / CLIENT ----------
load_dotenv()
API_KEY = os.getenv("VITE_GOOGLE_API_KEY")
if not API_KEY:
    raise RuntimeError("VITE_GOOGLE_API_KEY is not set in environment.")
gmaps = googlemaps.Client(key=API_KEY)

# ---------- UTILS ----------
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def haversine(coord1, coord2):
    lat1, lng1 = coord1
    lat2, lng2 = coord2
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return R * 2 * asin(sqrt(a))

def effective_cap_m(poi: dict, cand_name: str | None, cand_types: list[str] | None) -> int:
    """Select 100/400 normally, or 600/800 if geocode is weak."""
    wide = is_wide_area_candidate(cand_name, cand_types)
    weak = bool((poi.get("flags") or {}).get("weak_geocode"))
    if wide and weak:
        return WEAK_WIDE_CAP_M
    if wide:
        return WIDE_CAP_M
    if weak:
        return WEAK_POINT_CAP_M
    return POINT_CAP_M

def is_type_aligned(poi_type: str | None, cand_types, cand_name: str = "", cand_addr: str = "") -> bool:
    """
    Generic, reusable alignment:
      • If candidate has a strong synonym (not only weak generic), it aligns.
      • If only weak generics match, require a noun hint in name/address.
      • Unknown POI types don't block.
    """
    t = (poi_type or "").lower()
    if not t:
        return True

    types   = set(cand_types or [])
    allowed = set(GOOGLE_TYPE.get(t, set()))
    if not allowed:
        return True  # no mapping → don't block

    strong = allowed - WEAK_GENERIC_TYPES
    if types & strong:
        return True

    if types & allowed:
        txt   = f"{cand_name} {cand_addr}".lower()
        nouns = TYPE_NOUNS.get(t, [])
        if any(n in txt for n in nouns):
            return True

    if t == "point_of_interest" and types:
        return True

    return False

def type_alignment_bonus(poi_type: str | None, cand_types, cand_name: str = "", cand_addr: str = "") -> float:
    """
    Small ranking nudge for aligned types (does NOT affect rule-based acceptance).
    """
    return 0.2 if is_type_aligned(poi_type, cand_types, cand_name, cand_addr) else 0.0


def add_abbrev_variants(s: str) -> list[str]:
    out = []
    low = s.lower()
    for pat, repl in ABBREV_VARIANTS:
        if re.search(pat, low):
            out.append(re.sub(pat, repl, low))
    return out

def _has_landmark_noun_in_texts(texts: list[str]) -> bool:
    low = " ".join([(t or "") for t in texts]).lower()
    return any(n in low for n in _LANDMARK_NOUNS)

def decide_business_status_action(poi: dict, cand: dict) -> tuple[str, str]:
    """
    Decide what to do with a candidate based on its Google business_status.

    Returns one of:
      ("accept", "operational")
      ("recheck", "<reason>")
      ("drop",    "<reason>")
    """
    bs = (cand.get("business_status") or "UNKNOWN").upper()
    if bs == "OPERATIONAL":
        return ("accept", "operational")

    # Build some context
    poi_type = (poi.get("type") or "").lower()
    c_types  = set((cand.get("types") or []))
    texts    = [poi.get("name","")] + (poi.get("alt_names") or []) + [cand.get("name","")]

    if bs == "CLOSED_TEMPORARILY":
        return ("recheck", "closed_temporarily")

    if bs == "CLOSED_PERMANENTLY":
        # If this looks like a pure business → drop
        if c_types & _BUSINESS_TYPES:
            return ("drop", "closed_permanently_business")

        # If it's a clearly institutional listing (museum, church, etc.)
        # and not obviously a landmark noun → drop
        if (poi_type in {"museum","church"} or (c_types & _INSTITUTIONAL_TYPES)) and not _has_landmark_noun_in_texts(texts):
            return ("drop", "closed_permanently_institution")

        # Landmark override (pier/park/plaza/monument/… in name/alts) → recheck
        if _has_landmark_noun_in_texts(texts):
            return ("recheck", "closed_permanently_landmark_override")

        # Default conservative
        return ("drop", "closed_permanently")

    # Unknown / missing business status → accept (don’t block)
    if bs in ("UNKNOWN", "", None):
        return ("accept", "business_status_unknown")

    # Fallback conservative: recheck
    return ("recheck", f"business_status:{bs}")


def bias_center_tuple(bias: str | None):
    """
    Parse 'circle:<meters>@<lat>,<lng>' → (lat, lng, meters) or None.
    """
    if not bias:
        return None
    m = BIAS_RX.fullmatch(bias.strip())
    if not m:
        return None
    radius = float(m.group(1))
    lat = float(m.group(2)); lng = float(m.group(3))
    return (lat, lng, radius)

def distance_to_bias_anchor(poi: dict, cand_coords: dict, bias: str | None) -> float | None:
    """
    Distance from candidate to POI coords if present; otherwise to bias center.
    Returns meters, or None if we can’t compute.
    """
    if cand_coords is None or "lat" not in cand_coords or "lng" not in cand_coords:
        return None
    if "lat" in poi and "lng" in poi:
        anchor = (poi["lat"], poi["lng"])
    else:
        bc = bias_center_tuple(bias)
        if not bc:
            return None
        anchor = (bc[0], bc[1])
    return haversine(anchor, (cand_coords["lat"], cand_coords["lng"]))

def is_pure_postal_address(text: str) -> bool:
    return bool(PURE_ADDRESS_RX.match((text or "").strip()))

def is_strict_numeric_numeric_intersection(text: str) -> bool:
    return bool(NUMERIC_NUMERIC_INT_RX.match((text or "").strip()))

def normalize_punct(text: str) -> str:
    if not text:
        return ""
    # Normalize first to collapse many odd forms
    t = unicodedata.normalize("NFKC", text)

    # Map lookalikes → ASCII
    mapping = {
        # --- single quotes / apostrophes ---
        "’": "'",   # U+2019 RIGHT SINGLE QUOTATION MARK
        "‘": "'",   # U+2018 LEFT SINGLE QUOTATION MARK
        "‚": "'",   # U+201A SINGLE LOW-9 QUOTATION MARK
        "‛": "'",   # U+201B SINGLE HIGH-REVERSED-9 QUOTATION MARK
        "ʼ": "'",   # U+02BC MODIFIER LETTER APOSTROPHE
        "ʹ": "'",   # U+02B9 MODIFIER LETTER PRIME
        "ʻ": "'",   # U+02BB MODIFIER LETTER TURNED COMMA
        "ʽ": "'",   # U+02BD MODIFIER LETTER REVERSED COMMA
        "′": "'",   # U+2032 PRIME
        "᾽": "'",   # U+1FBF GREEK KORONIS
        "´": "'",   # U+00B4 ACUTE ACCENT (often misused as apostrophe)
        "̓": "'",   # U+0313 COMBINING COMMA ABOVE
        "＇": "'",   # U+FF07 FULLWIDTH APOSTROPHE

        # --- double quotes ---
        "”": '"',   # U+201D RIGHT DOUBLE QUOTATION MARK
        "“": '"',   # U+201C LEFT DOUBLE QUOTATION MARK
        "„": '"',   # U+201E DOUBLE LOW-9 QUOTATION MARK
        "‟": '"',   # U+201F DOUBLE HIGH-REVERSED-9 QUOTATION MARK
        "″": '"',   # U+2033 DOUBLE PRIME
        "‴": '"',   # U+2034 TRIPLE PRIME
        "ˮ": '"',   # U+02EE MODIFIER LETTER DOUBLE APOSTROPHE
        "〝": '"',   # U+301D REVERSED DOUBLE PRIME QUOTATION MARK
        "〞": '"',   # U+301E DOUBLE PRIME QUOTATION MARK
        "〟": '"',   # U+301F LOW DOUBLE PRIME QUOTATION MARK
        "＂": '"',   # U+FF02 FULLWIDTH QUOTATION MARK

        # --- dashes / hyphens / minus ---
        "‐": "-",   # U+2010 HYPHEN
        "-": "-",   # U+2011 NON-BREAKING HYPHEN
        "‒": "-",   # U+2012 FIGURE DASH
        "–": "-",   # U+2013 EN DASH
        "—": "-",   # U+2014 EM DASH
        "―": "-",   # U+2015 HORIZONTAL BAR
        "−": "-",   # U+2212 MINUS SIGN
        "﹘": "-",  # U+FE58 SMALL EM DASH
        "﹣": "-",  # U+FE63 SMALL HYPHEN-MINUS
        "－": "-",  # U+FF0D FULLWIDTH HYPHEN-MINUS
    }

    for a, b in mapping.items():
        t = t.replace(a, b)

    # Remove soft hyphen + zero-widths
    removals = {
        "\u00AD",  # SOFT HYPHEN
        "\u200B",  # ZERO WIDTH SPACE
        "\u200C",  # ZERO WIDTH NON-JOINER
        "\u200D",  # ZERO WIDTH JOINER
        "\u2060",  # WORD JOINER
        "\ufeff",  # BYTE ORDER MARK
    }
    for ch in removals:
        t = t.replace(ch, "")

    # Normalize exotic spaces to regular space
    spacelikes = {
        "\u00A0",  # NO-BREAK SPACE
        "\u2000", "\u2001", "\u2002", "\u2003", "\u2004",
        "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200A",
        "\u202F",  # NARROW NO-BREAK SPACE
        "\u205F",  # MEDIUM MATHEMATICAL SPACE
        "\u3000",  # IDEOGRAPHIC SPACE
    }
    for ch in spacelikes:
        t = t.replace(ch, " ")

    return t

def _normalize_addr_for_compare(s: str) -> str:
    t = normalize_punct(s or "").lower().strip()
    t = _ADDR_TAIL_RX.sub("", t)
    t = _ZIP_RX.sub("", t)
    t = _SUITE_RX.sub("", t)
    t = re.sub(r"^\d+\s+", "", t)          # drop leading street number (e.g., "1 Ferry Building" → "Ferry Building")
    t = re.sub(r"\s+", " ", t).strip()
    return t

def addresses_equivalent(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return _normalize_addr_for_compare(a) == _normalize_addr_for_compare(b)

def bump_recheck(poi: dict, reason: str):
    poi.setdefault("reasons", [])
    if reason not in poi["reasons"]:
        poi["reasons"].append(reason)
    poi.setdefault("flags", {})
    tries = int(poi["flags"].get("recheck_attempts") or 0) + 1
    poi["flags"]["recheck_attempts"] = tries
    if tries >= 2:
        poi["status"] = "drop"
        if "recheck_limit_exceeded" not in poi["reasons"]:
            poi["reasons"].append("recheck_limit_exceeded")
    else:
        poi["status"] = "recheck"
        
def is_wide_area_candidate(name: str | None, types: list[str] | None) -> bool:
    tokens = set(WIDE_AREA_TYPE)  # you already defined WIDE_AREA_TYPE above
    name_l = (name or "").lower()
    if any(tok in name_l for tok in tokens):
        return True
    tset = set(types or [])
    return any(tok in tset for tok in tokens)

def strip_suffixes(text: str) -> str:
    suffixes = [" Marker", " Site", " Historic District"]
    t = normalize_punct(text).strip()
    for s in suffixes:
        if t.endswith(s):
            t = t[:-len(s)]
    return t.strip()

def is_address_like(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(PURE_ADDRESS_RX.match(t))


def split_compound(text: str):
    """
    Split on comma/ampersand/slash/spaced dashes AFTER removing ALL parentheticals.
    Keep parts with ≥2 tokens, OR single-token parts that contain a type noun.
    """
    # remove ALL parentheticals anywhere
    base = re.sub(r"\([^)]*\)", " ", normalize_punct(text or ""))
    # split
    parts = re.split(r'\s*[&,/]\s*|\s+[–—-]\s+', base)
    out = []

    # flat set of nouns
    noun_set = set(n for lst in TYPE_NOUNS.values() for n in lst)

    for p in parts:
        p = re.sub(r"\s+", " ", p.strip())
        if not p:
            continue
        # tokens
        toks = re.findall(r"[A-Za-z0-9]+", p)
        if len(toks) >= 2:
            out.append(p)
            continue
        # allow one-token only if it contains a type noun (e.g., "Fountain", "Pier")
        low = p.lower()
        if any(n in low for n in noun_set):
            out.append(p)
    return out

def consensus_noun_from_variants(variants: list[str], threshold: float = 0.50) -> str | None:
    """
    Compute a consensus noun from the original name/alt variants.
    We count the *presence* of allowed nouns per variant (once per noun per variant).
    If the top noun's share >= threshold of total variants, return it; else None.
    """
    if not variants:
        return None

    allowed_nouns = set(n for lst in TYPE_NOUNS.values() for n in lst)

    counts: dict[str,int] = {}
    total = 0

    for v in variants:
        if not v:
            continue
        # strip parentheticals only; no suffix stripping or splitting at this stage
        t = CLEAN_PARENS_RX.sub(" ", (v or "")).lower()
        t = re.sub(r"[^\w\s]", " ", t)
        toks = [x for x in t.split() if x]  # no stopword trick here

        if not toks:
            continue

        total += 1

        # presence-based increment for each allowed noun appearing in the variant
        seen_here = set()
        for tok in toks:
            if tok in allowed_nouns and tok not in seen_here:
                counts[tok] = counts.get(tok, 0) + 1
                seen_here.add(tok)

    if not total or not counts:
        return None

    # pick the noun with max support; require share >= threshold
    noun, cnt = max(counts.items(), key=lambda kv: kv[1])
    return noun if (cnt / total) >= threshold else None



def get_alt_names(poi) -> list[str]:
    return poi.get("alt_names") or poi.get("alternative_names") or []

def clamp01(x: float) -> float:
    if x < 0: return 0.0
    if x > 1: return 1.0
    return x

def generate_variants(poi):
    """
    Build alias/name variants from name + alt_names for SCORING.
    Exclude pure postal addresses and strict numeric–numeric intersections.
    Deduplicate by normalized form and track pre-dedupe counts.
    """
    fields = [poi.get("name", "")]
    fields += get_alt_names(poi)

    all_candidates = []

    for field in fields:
        if not field:
            continue
        norm = normalize_punct(field)
        all_candidates.append(norm)
        all_candidates += split_compound(norm)
        all_candidates.append(strip_suffixes(norm))
        all_candidates.append(norm.lower().replace("'", ""))
        for ab in add_abbrev_variants(norm):
            all_candidates.append(ab)

    # Filter out address-like and strict numeric–numeric intersection strings
    filtered = [
        v for v in all_candidates
        if v and not is_address_like(v) and not is_strict_numeric_numeric_intersection(v)
    ]

    def normalize_for_alias(v):
        v = (v or "").lower().strip()
        v = re.sub(r"[^\w\s]", " ", v)
        v = re.sub(r"\s+", " ", v)
        return v

    norm_map = defaultdict(list)
    for v in filtered:
        nv = normalize_for_alias(v)
        if nv:
            norm_map[nv].append(v)

    variant_counts = {nv: len(orig_list) for nv, orig_list in norm_map.items()}
    return variant_counts, norm_map


def geocode_address(addr: str):
    if not addr:
        return None
    try:
        geo = gmaps.geocode(addr)
        if geo:
            loc = geo[0]["geometry"]["location"]
            return {
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
                "formatted": geo[0].get("formatted_address", ""),
                "location_type": geo[0]["geometry"].get("location_type", "")
            }
    except Exception:
        pass
    return None

def compute_city_bias(city: str | None):
    if not city:
        return None
    try:
        g = gmaps.geocode(city)
        if g:
            c = g[0]["geometry"]["location"]
            return f"circle:4000@{c['lat']:.6f},{c['lng']:.6f}"
    except Exception:
        return None

def make_bias_for_poi(poi, city_bias: str | None):
    if poi.get("lat") and poi.get("lng"):
        return f"circle:500@{poi['lat']:.6f},{poi['lng']:.6f}"
    return city_bias

def get_google_candidates(poi, bias: str | None):
    """
    Collect raw Google candidates only:
      - Suppress pure postal addresses & strict numeric–numeric intersections
      - Require coords
      - Far filter (15km from POI anchor; else 2× city-bias radius)
      - Deduplicate by place_id, then (name_norm, address_norm)
      - Tie-breaker = completeness (coords > street-level addr > more types > longer addr)
    """
    _, norm_map = generate_variants(poi)

    # Query keys are just the normalized variant strings we built
    keys = list(norm_map.keys())

    candidates = []

    def _far_cutoff():
        bc = bias_center_tuple(bias)
        if ("lat" in poi and "lng" in poi):
            return 15000.0  # 15 km when we have a precise POI anchor
        if bc:
            return 2.0 * bc[2]  # ~2× bias radius when using city bias
        return None

    far_cut = _far_cutoff()

    for norm_variant in keys:
        query_variant = norm_map[norm_variant][0]

        # Suppress noisy queries: pure postal addresses and strict numeric–numeric intersections
        if is_pure_postal_address(query_variant) or is_strict_numeric_numeric_intersection(query_variant):
            continue

        try:
            res = gmaps.find_place(
                input=query_variant,
                input_type="textquery",
                fields=["name","formatted_address","geometry","types","business_status","place_id"],
                location_bias=bias,
                language="en"
            )
        except Exception:
            continue

        for c in res.get("candidates", []):
            name = c.get("name") or ""
            addr = c.get("formatted_address") or ""
            types = c.get("types") or []
            coord = ((c.get("geometry") or {}).get("location") or {})  # expect {'lat':..., 'lng':...}

            # Require coords
            if not ("lat" in coord and "lng" in coord):
                continue

            # Far filter
            if far_cut is not None:
                d = distance_to_bias_anchor(poi, coord, bias)
                if d is not None and d > far_cut:
                    continue

            candidates.append({
                "name": name,
                "address": addr,
                "types": types,
                "coords": coord,
                "business_status": (c.get("business_status") or "UNKNOWN"),
                "place_id": c.get("place_id"),
                # lightweight debug breadcrumbs
                "query_norm": norm_variant,
                "query_count": len(norm_map.get(norm_variant, [])),
            })

    # ---- Deduplicate with completeness tie-breaker ----
    def _norm(s: str) -> str:
        s = (s or "").lower().strip()
        s = re.sub(r"[^\w\s]", "", s)
        return re.sub(r"\s+", " ", s)

    # simple street-level heuristic: number present → strongest; else street token → medium; else generic
    def _street_level_rank(addr: str) -> int:
        a = (addr or "").lower()
        if not a:
            return 0
        if re.search(r"\d", a):
            return 2
        if any(re.search(rf"\b{tok}\b", a) for tok in ADDRESS_TOKENS):
            return 1
        return 0

    def _completeness_key(c: dict) -> tuple:
        has_coords = 1 if ("coords" in c and "lat" in c["coords"] and "lng" in c["coords"]) else 0
        street_rank = _street_level_rank(c.get("address", ""))
        types_count = len(c.get("types") or [])
        addr_len = len(c.get("address") or "")
        return (has_coords, street_rank, types_count, addr_len)

    grouped: dict[tuple, dict] = {}

    for c in candidates:
        pid = c.get("place_id")
        if pid:
            key = ("pid", pid)
        else:
            key = ("na", _norm(c.get("name")), _norm(c.get("address")))

        prev = grouped.get(key)
        if prev is None:
            grouped[key] = c
        else:
            # keep the most complete representative
            if _completeness_key(c) > _completeness_key(prev):
                grouped[key] = c

    return list(grouped.values())



_slug_rx = re.compile(r"[^a-z0-9_-]+")

def slugify(s: str) -> str:
    s = re.sub(r"\s+", "-", (s or "").strip().lower())
    return _slug_rx.sub("", s) or "poi"

def dedupe_preserve(seq):
    seen = set()
    out = []
    for x in seq or []:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out

def apply_places_match(poi, best, existing_slugs: set[str]):
    # if already locked, don't overwrite display name/address; still attach place block
    if poi.get("name_locked"):
        poi.setdefault("place", {})
        poi["place"].update({
            "provider": "google_places",
            "place_id": best.get("place_id"),
            "name": best.get("name"),
            "formatted_address": best.get("address"),
            "lat": best.get("coords", {}).get("lat"),
            "lng": best.get("coords", {}).get("lng"),
            "types": best.get("types", []),
        })
        # Mirror coords to top-level too (drives outlier math/route)
        pl = poi["place"]
        if pl.get("lat") is not None and pl.get("lng") is not None:
            poi["lat"] = pl["lat"]
            poi["lng"] = pl["lng"]
        return poi

    prev_name = poi.get("name") or ""
    new_name  = best.get("name") or prev_name
    if new_name != prev_name and prev_name:
        poi["alt_names"] = dedupe_preserve((poi.get("alt_names") or []) + [prev_name])
    poi["name"] = new_name
    poi["address"] = best.get("address") or poi.get("address", "")

    poi["place"] = {
        "provider": "google_places",
        "place_id": best.get("place_id"),
        "name": best.get("name"),
        "formatted_address": best.get("address"),
        "lat": best.get("coords", {}).get("lat"),
        "lng": best.get("coords", {}).get("lng"),
        "types": best.get("types", []),
    }
    pl = poi.get("place", {})
    if pl.get("lat") is not None and pl.get("lng") is not None:
        poi["lat"] = pl["lat"]
        poi["lng"] = pl["lng"]
    poi["name_source"] = "google_places"
    poi["name_locked"] = True

    # slug (poi_id) – ensure uniqueness within the file
    base = slugify(poi["name"])
    slug = base
    i = 2
    # allow keeping same slug if already set & matches
    if poi.get("poi_id") and poi["poi_id"] == slug:
        existing_slugs.add(slug)
    else:
        while slug in existing_slugs:
            slug = f"{base}-{i}"
            i += 1
        poi["poi_id"] = slug
        existing_slugs.add(slug)

    return poi

# ---------- MAIN ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",  default="src/data/current_pois.json")
    ap.add_argument("--output", default=None, help="Defaults to --input in non-dry mode.")
    ap.add_argument("--summary", default="src/data/validation_summary.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="Validate at most N POIs.")
    args = ap.parse_args()

    with open(args.input, "r") as f:
        root = json.load(f)

    if not (isinstance(root, dict) and "pois" in root and "meta" in root):
        raise ValueError("Expected an object with 'meta' and 'pois'.")

    city = (root.get("meta") or {}).get("city")
    city_bias = compute_city_bias(city)

    pois = root["pois"]
    results = []
    processed = 0

    # existing slugs set for uniqueness
    existing_slugs = {p.get("poi_id") for p in pois if p.get("poi_id")}
    existing_slugs = {s for s in existing_slugs if s}

    for poi in pois:
        if args.limit is not None and processed >= args.limit:
            results.append(poi)
            continue

        # Skip already final states
        if poi.get("status") in ("keep", "drop"):
            results.append(poi)
            continue

        orig_status = (poi.get("status") or "").lower()

        # ---- GEOCODE GATE ----
        addr = (poi.get("address") or "").strip()
        geo = geocode_address(addr) if addr else None

        if not geo:
            # count refined attempts (optional)
            if orig_status == "gpt_refined":
                poi["refined_attempts"] = int(poi.get("refined_attempts") or 0) + 1

            bump_recheck(poi, "geocode_failed")
            poi["validation_debug"] = {"rule": "geocode_gate_failed"}
            results.append(poi); processed += 1
            continue

        # Persist coordinates and geocode debug
        poi["lat"], poi["lng"] = geo["lat"], geo["lng"]
        poi.setdefault("validation_debug", {})
        poi["validation_debug"]["geocode"] = {
            "formatted_address": geo.get("formatted"),
            "location_type": geo.get("location_type"),
            "lat": geo["lat"], "lng": geo["lng"]
        }
        if geo.get("location_type") in {"GEOMETRIC_CENTER", "APPROXIMATE"}:
            poi.setdefault("flags", {})["weak_geocode"] = True

        bias = make_bias_for_poi(poi, city_bias)
        # ---- END GEOCODE GATE ----

        # Quick guard: address-like-only names → recheck
        name_fields = [poi.get("name", "")] + get_alt_names(poi)
        name_fields = [n for n in name_fields if n]
        if name_fields and all(is_address_like(n) for n in name_fields):
            bump_recheck(poi, "address_like_name_no_real_name")
            results.append(poi); processed += 1
            continue

        # --- Consensus noun (raw aliases only; no split/strip/abbr) ---
        raw_aliases = [poi.get("name", "")] + get_alt_names(poi)
        raw_for_noun = []
        for field in raw_aliases:
            if not field:
                continue
            t = normalize_punct(field)
            t = CLEAN_PARENS_RX.sub(" ", t).strip()
            if t and not is_address_like(t):  # skip pure addresses
                raw_for_noun.append(t)

        consensus_noun = consensus_noun_from_variants(raw_for_noun, threshold=0.50)
        poi.setdefault("validation_debug", {})["consensus_noun"] = consensus_noun


        # Get Google candidates (now noun-aware)
        candidates = get_google_candidates(poi, bias)


        # -------- Unified identity scoring (single-pass decision) --------
        # Build alias variants & counts (for phrase/supported-by-alias signals)
        variant_counts, norm_map = generate_variants(poi)
        alias_norm_keys = set(norm_map.keys())  # normalized alias strings

        def _norm_name(s: str) -> str:
            s = (s or "").lower()
            s = re.sub(r"[^\w\s]", " ", s)
            return re.sub(r"\s+", " ", s).strip()

        scored = []
        for c in candidates:
            name = c.get("name", "") or ""
            addr = c.get("formatted_address", "") or c.get("address", "") or ""
            types = c.get("types", []) or []
            coords = c.get("coords")  # support both raw Places and our dict form

            # --- 5.1 Phrase identity (exact alias → 1.0; else fuzzy 40/40/20) ---
            cand_norm_raw = name.lower()
            cand_norm = _norm_name(name)
            exact_alias = cand_norm in alias_norm_keys

            best_phrase = 1.0 if exact_alias else 0.0
            best_alias_key = cand_norm if exact_alias else None

            if not exact_alias:
                for v_norm in alias_norm_keys:
                    token_sort = fuzz.token_sort_ratio(v_norm, cand_norm_raw) / 100.0
                    token_set  = fuzz.token_set_ratio(v_norm,  cand_norm_raw) / 100.0
                    partial    = fuzz.partial_ratio(v_norm,    cand_norm_raw) / 100.0
                    score = 0.4*token_sort + 0.4*token_set + 0.2*partial
                    if score > best_phrase:
                        best_phrase = score
                        best_alias_key = v_norm

            if (not exact_alias) and (best_phrase < PHRASE_THRESHOLD):
                continue  # discard weak identity

            phrase = clamp01(best_phrase)

            # --- 5.2 Support bonus (alias repetition pre-dedupe) ---
            support_count = variant_counts.get(best_alias_key, 1) if best_alias_key else 1
            support_bonus = min(0.25, 0.10 * (support_count - 1))  # 1x→0.00, 2x→+0.10, 3x→+0.20, 4x+→+0.25

            # --- 5.3 Consensus noun bonus (±0.50) ---
            noun_bonus = 0.0
            if consensus_noun:
                tokens = set(cand_norm.split())
                noun_bonus = 0.50 if (consensus_noun in tokens) else -0.50

            # --- 5.4/5.5 Address equivalence & distance bonuses/caps ---
            geocode_fmt = ((poi.get("validation_debug") or {}).get("geocode") or {}).get("formatted_address", "")
            addr_equiv = addresses_equivalent(addr, geocode_fmt) or addresses_equivalent(addr, poi.get("address", ""))

            d = distance_to_bias_anchor(poi, {"lat": (coords or {}).get("lat"), "lng": (coords or {}).get("lng")}, bias)
            distance_bonus = 0.0
            cap_m = effective_cap_m(poi, name, types)

            if addr_equiv:
                # treat as d = 0 and bypass cap enforcement (grant ≤50m bonus)
                d = 0.0
                distance_bonus = 1.0
            else:
                if d is None:
                    continue
                if d > cap_m:
                    continue
                if d <= 50: distance_bonus = 1.0
                elif d <= 100: distance_bonus = 0.5
                elif d <= 150: distance_bonus = 0.2

            # --- 5.6 Route penalty (avoid overlays) ---
            route_penalty = -0.30 if ("route" in types and (poi.get("type") or "").lower() != "trail") else 0.0

            # --- 5.7 Type nudge (+0.20 if aligned) ---
            type_bonus = type_alignment_bonus(poi.get("type"), types, name, addr)

            # --- 5.8 Final score (identity only) ---
            final = phrase + support_bonus + noun_bonus + distance_bonus + type_bonus + route_penalty

            c_scored = {
                "name": name,
                "address": addr,
                "types": types,
                "coords": coords,
                "business_status": c.get("business_status", "UNKNOWN"),
                "place_id": c.get("place_id"),
                # scoring breakdown:
                "phrase_score": phrase,
                "support_count": support_count,
                "support_bonus": round(support_bonus, 3),
                "noun_bonus": noun_bonus,
                "address_equivalent": bool(addr_equiv),
                "distance_m": d,
                "distance_bonus": distance_bonus,
                "type_bonus": type_bonus,
                "route_penalty": route_penalty,
                "final_score": final,
            }
            scored.append(c_scored)

        # nothing viable → fallback path handled below
        if not scored:
            # (do not return; fall through to Stage 3 / Fallback block)
            poi.setdefault("validation_debug", {})["candidates_top2"] = []
        else:
            scored.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)

            # Debug top-2 after unified scoring
            top2_dbg = []
            for s in scored[:2]:
                top2_dbg.append({
                    "name": s["name"],
                    "address": s["address"],
                    "business_status": s.get("business_status"),
                    "phrase": round(s.get("phrase_score", 0.0), 3),
                    "final": round(s.get("final_score", 0.0), 3),
                    "distance_m": None if s.get("distance_m") is None else round(s["distance_m"], 1),
                    "address_equivalent": s.get("address_equivalent", False),
                    "wide_area": is_wide_area_candidate(s.get("name"), s.get("types")),
                })
            poi.setdefault("validation_debug", {})["candidates_top2"] = top2_dbg

            # --- 5.9 Ambiguity rule ---
            ambig = False
            if len(scored) >= 2:
                s1, s2 = scored[0], scored[1]
                if abs(s1["final_score"] - s2["final_score"]) < 0.02:
                    d1, d2 = s1.get("distance_m"), s2.get("distance_m")
                    if (d1 is not None) and (d2 is not None) and abs(d1 - d2) <= 30:
                        ambig = True

            if ambig:
                bump_recheck(poi, "ambiguous_nearby")
                results.append(poi); processed += 1
                continue

            # Winner by unified score
            best = scored[0]

            # --- Business status gate (after identity chosen) ---
            action, reason = decide_business_status_action(poi, best)

            if action == "drop":
                poi["status"] = "drop"
                poi.setdefault("reasons", []).append(reason)
                results.append(poi); processed += 1
                continue

            elif action == "recheck":
                bump_recheck(poi, reason)
                poi.setdefault("validation_debug", {})["business_status_note"] = {
                    "reason": reason,
                    "candidate": best.get("name"),
                    "business_status": best.get("business_status"),
                }
                results.append(poi); processed += 1
                continue

            # accept (OPERATIONAL or UNKNOWN)
            poi = apply_places_match(poi, best, existing_slugs)
            poi["status"] = "keep"
            poi["reasons"] = []
            poi.setdefault("flags", {})["recheck_attempts"] = 0
            poi.setdefault("validation_debug", {})["business_status"] = best.get("business_status")
            results.append(poi); processed += 1
            continue


        # -------- Stage 3: Fallback or Recheck --------
        if orig_status == "gpt_refined":
            poi["status"] = "keep"
            poi["reasons"] = []
            poi["name_source"] = poi.get("name_source") or "gpt"
            poi.setdefault("flags", {})["recheck_attempts"] = 0
            poi.setdefault("validation_debug", {})["rule"] = "gpt_refined_accepted_no_places"
        else:
            bump_recheck(poi, "no_strong_match")

        results.append(poi); processed += 1

    # --- OUTLIER CHECK (final sweep across all keep-able POIs) ---
    potential_keep = [r for r in results if ("lat" in r and "lng" in r and r.get("status") != "drop")]
    for r in potential_keep:
        distances = [haversine((r["lat"], r["lng"]), (o["lat"], o["lng"]))
                    for o in potential_keep if o is not r]
        nnd = min(distances) if distances else None
        if nnd and nnd > OUTLIER_RADIUS_METERS:
            r["status"] = "drop"
            r.setdefault("reasons", []).append("outlier_far")
        else:
            # if we never set a status explicitly, keep it
            if not r.get("status"):
                r["status"] = "keep"

    # ---------- SUMMARY ----------
    summary = Counter()
    for r in results:
        summary[r.get("status","recheck")] += 1

    # ---------- WRITE ----------
    if args.dry_run:
        print(f"DRY RUN — no files written")
        print(f"Summary: {dict(summary)}")
        return

    root["pois"] = results
    root["meta"]["last_updated"] = now_iso()

    out_path = args.output or args.input
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(root, f, indent=2)
    os.replace(tmp, out_path)

    with open(args.summary, "w") as f:
        json.dump(dict(summary), f, indent=2)

    print(f"✅ Validation complete. KEEP: {summary.get('keep',0)} | RECHECK: {summary.get('recheck',0)} | DROP: {summary.get('drop',0)}")

if __name__ == "__main__":
    main()

