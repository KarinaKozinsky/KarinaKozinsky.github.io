# merge_narrations_into_tour.py
import os, json

TOUR_PATH = "public/tours/sf/gold_rush/gold_rush.json"
NARRATION_PATH = "public/tours/sf/gold_rush/gold_rush_narration.json"
OUTPUT_PATH = "public/tours/sf/gold_rush/gold_rush.json"  # overwrite; or change to a new file

def norm(s): return " ".join((s or "").strip().lower().split())

with open(TOUR_PATH, "r", encoding="utf-8") as f:
    tour = json.load(f)

with open(NARRATION_PATH, "r", encoding="utf-8") as f:
    narrs = json.load(f)

by_id = {n.get("poi_id"): n for n in narrs if n.get("poi_id")}
by_name = {norm(n.get("name","")): n for n in narrs}

updated = 0
for stop in tour.get("stops", []):
    nid = stop.get("poi_id")
    nm = norm(stop.get("name",""))
    n = by_id.get(nid) if nid in by_id else by_name.get(nm)
    if not n: 
        continue
    stop["narration_text"] = n.get("text", "")
    # if the TTS step already saved a combined file, attach it here:
    if "narration_audio" in n and n["narration_audio"]:
        stop["narration_audio"] = n["narration_audio"]
    updated += 1

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(tour, f, ensure_ascii=False, indent=2)

print(f"Updated {updated} stops with narration.")
