#!/usr/bin/env python3
import json
import os
import re
import googlemaps
from dotenv import load_dotenv
from difflib import SequenceMatcher
from math import radians, cos, sin, asin, sqrt

# ——— Configuration ———
load_dotenv()
API_KEY = os.getenv("VITE_GOOGLE_API_KEY")
gmaps = googlemaps.Client(key=API_KEY)

# ——— Helpers ———
def similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))

def normalize(text):
    mapping = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
    for a, b in mapping.items():
        text = text.replace(a, b)
    return text.strip()

def strip_suffix(text):
    generic = [" place", " site", " marker", " historic district"]
    text = normalize(text)
    for suffix in generic:
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip()

def geocode_address(addr):
    try:
        res = gmaps.geocode(addr)
        if res:
            loc = res[0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except:
        return None, None

def reverse_geocode(lat, lon):
    try:
        res = gmaps.reverse_geocode((lat, lon))
        if res:
            return res[0].get("formatted_address"), res[0].get("place_id")
    except:
        return None, None

def tokenize(text):
    return set(re.findall(r'\b[a-zA-Z0-9]+\b', text.lower()))

# ——— Core Logic ———
def forward_lookup_debug(poi):
    print(f"\n📌 Testing POI: {poi['name']}")
    print(f"📍 Geocoded original address: {poi['address']}")

    lat, lon = geocode_address(poi["address"])
    if lat is None or lon is None:
        print("❌ Failed to geocode original POI address")
        return

    variants = []
    variants.append((normalize(poi["name"]), "name"))
    variants += [(normalize(n), "alt_name") for n in poi.get("alternative_names", [])]
    variants.append((normalize(poi["search_hint"]), "search_hint"))
    variants.append((normalize(poi["search_hint"] + " san francisco"), "search_hint_city"))
    variants.append((strip_suffix(poi["search_hint"]), "search_hint_stripped"))

    seen = set()
    for variant, label in variants:
        if variant in seen:
            continue
        seen.add(variant)
        print(f"\n🔎 Query: {variant} ({label})")
        try:
            resp = gmaps.find_place(
                input=variant,
                input_type="textquery",
                fields=["name", "geometry", "formatted_address"]
            )
            candidates = resp.get("candidates", [])
            for c in candidates:
                cname = c.get("name", "")
                caddr = c.get("formatted_address", "")
                ccoords = c.get("geometry", {}).get("location", {})
                flat = ccoords.get("lat")
                flon = ccoords.get("lng")

                f_score = similar(variant, cname)
                token_fraction = len(tokenize(variant) & tokenize(cname)) / max(len(tokenize(variant)), 1)
                dist = haversine(lat, lon, flat, flon) if flat and flon else None

                print(f"→ Candidate:\n  name: {cname}\n  address: {caddr}")
                print(f"  token match: {token_fraction:.2f}\n  fuzzy match: {f_score:.2f}")
                if dist:
                    print(f"  distance to original: {round(dist)} m")

                if cname == caddr:
                    print("  ⚠️ Skipping match — name is just an address")
                    continue

                if dist and dist < 20:
                    rev_addr, _ = reverse_geocode(flat, flon)
                    if rev_addr and similar(rev_addr, poi["address"]) > 0.9:
                        print(f"  📍 Close & name match — running reverse geocode check...")
                        print(f"  ✅ Reverse geocode address matched: {rev_addr}")
                        print("  ✅ FINAL: KEEP")
                        return
        except Exception as e:
            print(f"⚠️ Lookup failed: {e}")

    print("❌ FINAL: No valid match found — RECHECK")

# ——— Run Single Test ———
if __name__ == "__main__":
    with open("src/data/pois_for_script_validation.json", "r") as f:
        data = json.load(f)
    for poi in data.get("stops", []):
        if poi["poi_id"] == "bank_california":  # Change this ID to test other POIs
            forward_lookup_debug(poi)
