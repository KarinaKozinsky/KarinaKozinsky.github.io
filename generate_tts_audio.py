import os, re, json, tempfile, shutil, subprocess
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# ----------------- CONFIG -----------------
TOUR_PATH = "public/tours/sf/gold_rush/gold_rush.json"

AUDIO_DIR = "public/tours/sf/gold_rush/audio"
AUDIO_URL_PREFIX = ""  

OPENAI_TTS_MODEL = "tts-1"
OPENAI_TTS_VOICE = "ash"
CHUNK_TARGET_CHARS = 1400  # ~60–90s per chunk; safe for tts-1
REGENERATE = False         # True = overwrite existing final MP3s

# If your narrations ever include meta “Double-check:” tails, strip them:
STRIP_TRAILING_DOUBLECHECK = True
# ------------------------------------------

def slugify(name: str) -> str:
    s = (name or "").strip().lower()
    # Replace punctuation with space
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "stop"

def clean_text(text: str) -> str:
    t = text.strip()

    # Optional: strip “Double-check:” meta section if present
    if STRIP_TRAILING_DOUBLECHECK:
        t = re.sub(r"\n{2,}double[-–—]check:.*$", "", t, flags=re.IGNORECASE | re.DOTALL).strip()

    # Normalize pauses (OpenAI TTS doesn’t use SSML; these just hint cadence)
    t = t.replace("[long pause]", " …… ")
    t = t.replace("[pause]", " … ")

    # Normalize whitespace
    t = re.sub(r"\r\n?", "\n", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t

def split_into_chunks(text: str, target_chars=CHUNK_TARGET_CHARS):
    """
    Split on paragraph gaps and pause markers first; then sentences if still too long.
    """
    # Coarse split by blank lines and pause ellipses
    # Keep the separators so we don’t lose the natural breaks
    parts = re.split(r"(\n{2,}|…+)", text)
    parts = [p for p in parts if p and p.strip()]

    chunks, buf = [], ""
    def commit():
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for part in parts:
        candidate = (buf + ("\n\n" if buf and not buf.endswith("\n\n") else "") + part).strip() if buf else part.strip()
        if len(candidate) <= target_chars:
            buf = candidate
        else:
            # Sentence-level split inside this oversized part
            sentences = re.split(r"(?<=[\.\!\?])\s+", part.strip())
            for s in sentences:
                cand2 = (buf + " " + s).strip() if buf else s.strip()
                if len(cand2) <= target_chars:
                    buf = cand2
                else:
                    commit()
                    # Hard-wrap mega-long “sentence”
                    while len(s) > target_chars:
                        chunks.append(s[:target_chars])
                        s = s[target_chars:]
                    buf = s.strip()
    commit()
    return chunks

def ensure_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        raise RuntimeError("ffmpeg not found. Install it (e.g., `brew install ffmpeg` or `apt-get install ffmpeg`).")

def tts_chunk_to_mp3(client: OpenAI, text: str, out_path: Path):
    """
    OpenAI tts-1 call. Uses streaming writer to file.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Prefer streaming to file for reliability
    try:
        with client.audio.speech.with_streaming_response.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            format="mp3"
        ) as resp:
            resp.stream_to_file(out_path)
    except AttributeError:
        # Fallback for older client versions
        audio = client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            format="mp3"
        )
        # Some SDKs return bytes; others a .to_file helper
        content = getattr(audio, "content", None) or getattr(audio, "audio", None)
        if hasattr(audio, "to_file"):
            audio.to_file(out_path)
        elif isinstance(content, (bytes, bytearray)):
            with open(out_path, "wb") as f:
                f.write(content)
        else:
            # Last resort: try .data[0].b64_json
            b64 = None
            try:
                b64 = audio.data[0].b64_json
            except Exception:
                pass
            if not b64:
                raise RuntimeError("Unexpected TTS response format; please update the OpenAI SDK.")
            import base64
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(b64))

def combine_segments_to_single_mp3(segment_paths, out_path: Path):
    """
    Decode segments to WAV → concat → loudness normalize → encode to MP3.
    Produces smooth joins and consistent volume.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="tts_join_"))
    try:
        wavs = []
        for i, seg in enumerate(segment_paths):
            wav = tmpdir / f"{i:03d}.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-i", str(seg), "-ar", "44100", "-ac", "2", str(wav)],
                check=True
            )
            wavs.append(wav)

        listfile = tmpdir / "list.txt"
        with open(listfile, "w", encoding="utf-8") as f:
            for w in wavs:
                f.write(f"file '{w.as_posix()}'\n")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(listfile),
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-c:a", "libmp3lame", "-b:a", "192k", str(out_path)],
            check=True
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def tts_chunk_to_mp3(client, text, out_path):
    # Streaming version (fast, low-memory)
    with client.audio.speech.with_streaming_response.create(
        model="tts-1",
        voice="ash",
        input=text,
    ) as resp:
        resp.stream_to_file(out_path)
        
def main():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    client = OpenAI(api_key=api_key)

    ensure_ffmpeg()

    with open(TOUR_PATH, "r", encoding="utf-8") as f:
        tour = json.load(f)

    stops = tour.get("stops", [])
    if not stops:
        print("No stops found.")
        return

    Path(AUDIO_DIR).mkdir(parents=True, exist_ok=True)

    for stop in stops:
        name = stop.get("name") or ""
        text = (stop.get("narration_text") or "").strip()
        if not name or not text:
            print(f"Skipping (missing name or narration_text): {name!r}")
            continue

        slug = slugify(stop.get("poi_id") or name)
        final_mp3 = Path(AUDIO_DIR) / f"{slug}.mp3"

        if final_mp3.exists() and not REGENERATE:
            print(f"✓ Exists, skipping: {final_mp3.name}")
            # Write the URL (or filename) into the tour JSON
            stop["narration_audio"] = f"{AUDIO_URL_PREFIX}/{final_mp3.name}" if AUDIO_URL_PREFIX else final_mp3.name
            continue

        print(f"→ Generating: {final_mp3.name}")
        cleaned = clean_text(text)
        chunks = split_into_chunks(cleaned, CHUNK_TARGET_CHARS)

        seg_dir = Path(AUDIO_DIR) / "_segments" / slug
        seg_dir.mkdir(parents=True, exist_ok=True)
        seg_paths = []

        for i, chunk in enumerate(chunks, start=1):
            seg_mp3 = seg_dir / f"{slug}_{i:02d}.mp3"
            if seg_mp3.exists() and not REGENERATE:
                print(f"  - chunk {i:02d}: exists")
            else:
                print(f"  - chunk {i:02d}: synth")
                tts_chunk_to_mp3(client, chunk, seg_mp3)
            seg_paths.append(seg_mp3)

        combine_segments_to_single_mp3([str(p) for p in seg_paths], final_mp3)

        # Write the URL (or filename) into the tour JSON
        stop["narration_audio"] = f"{AUDIO_URL_PREFIX}/{final_mp3.name}" if AUDIO_URL_PREFIX else final_mp3.name
        print(f"  ✓ done: {final_mp3.name}")

    # Save tour JSON with narration_audio fields filled
    with open(TOUR_PATH, "w", encoding="utf-8") as f:
        json.dump(tour, f, ensure_ascii=False, indent=2)

    print("\nAll set. Audio paths written into tour JSON.")

if __name__ == "__main__":
    main()
