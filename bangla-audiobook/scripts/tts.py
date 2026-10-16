"""Narrate every Bangla text file with edge-tts using parallel workers. Resumable: existing audio is skipped.

Usage: python tts.py <workdir> [--workers 4] [--voice bn-BD-NabanitaNeural] [--rate -4%] [--pitch +0Hz]
Reads <workdir>/bangla/*.txt, writes <workdir>/audio/<same stem>.mp3
"""
import argparse
import asyncio
import json
import pathlib
import re
import shutil
import subprocess
import sys

import edge_tts

sys.stdout.reconfigure(encoding="utf-8")

MAX_CHARS = 2500


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise SystemExit("ffmpeg not found: pip install imageio-ffmpeg")
        return exe


def load_pronunciation_map(workdir: pathlib.Path) -> dict[str, str]:
    """Load custom pronunciation overrides from pronunciation.txt or phonetics.txt."""
    m: dict[str, str] = {}
    candidates = [
        pathlib.Path(__file__).parent.parent / "phonetics.txt",
        pathlib.Path(__file__).parent / "phonetics.txt",
        workdir / "pronunciation.txt",
        workdir / "phonetics.txt",
    ]
    for f in candidates:
        if f.exists():
            for line in f.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k:
                        m[k] = v.strip()
    return m


def build_phonetic_replacer(rules: dict[str, str]):
    """
    Compiles phonetic rules into a single-pass O(L) regex substitution engine,
    replacing N individual full-text regex passes with one unified matcher.
    """
    sorted_words = sorted((w for w in rules if w), key=len, reverse=True)
    if not sorted_words:
        return lambda text: text
    pat = re.compile(
        rf"(?<![\u0980-\u09ff])({'|'.join(re.escape(w) for w in sorted_words)})(?![\u0980-\u09ff])"
    )

    def replacer(text: str) -> str:
        return pat.sub(lambda m: rules[m.group(0)], text)

    return replacer


def normalize_spoken_text(text: str) -> str:
    """Pre-processes text to clean up awkward book print artifacts before TTS synthesis."""
    # 1. Expand single Latin initials with dots e.g. T. S. Eliot -> টি এস Eliot
    latin_initials = {
        "A": "এ", "B": "বি", "C": "সি", "D": "ডি", "E": "ই", "F": "এফ",
        "G": "জি", "H": "এইচ", "I": "আই", "J": "জে", "K": "কে", "L": "এল",
        "M": "এম", "N": "এন", "O": "ও", "P": "পি", "Q": "কিউ", "R": "আর",
        "S": "এস", "T": "টি", "U": "ইউ", "V": "ভি", "W": "ডব্লিউ", "X": "এক্স",
        "Y": "ওয়াই", "Z": "জেড",
    }
    text = re.sub(
        r"\b([A-Za-z])\.\s*",
        lambda m: latin_initials.get(m.group(1).upper(), m.group(1)) + " ",
        text,
    )

    # 2. Transliterate common famous names if left in English
    name_map = {
        "Eliot": "এলিয়ট",
        "Shakespeare": "শেক্সপিয়র",
        "Tolstoy": "তলস্তয়",
        "Dostoevsky": "দস্তয়েভস্কি",
        "Kafka": "কাফকা",
        "Hemingway": "হেমিংওয়ে",
        "Orwell": "অরওয়েল",
    }
    for eng, bng in name_map.items():
        text = re.sub(rf"\b{eng}\b", bng, text, flags=re.I)

    # 3. Strip abbreviation dots in Bengali script so TTS doesn't chop names (e.g. টি. এস. -> টি এস).
    #    The (?!\.) lookahead keeps ellipses such as "হ্যাঁ..." intact so the dramatic pause survives.
    text = re.sub(r"([\u0980-\u09ff])\.(?!\.)\s*", r"\1 ", text)

    # 4. Convert bare print-style em-dash attributions into natural spoken narration.
    #    Only a short line that directly follows a closing quotation is treated as an
    #    attribution; ordinary dialogue lines beginning with '—' are left untouched.
    narration_verbs = ("বলেছেন", "বলেছিলেন", "উক্তিটি", "উক্তি", "কথাটি", "লিখেছেন")
    closing_quotes = ("”", '"', "’", "'", "»", "」", "』")
    # Lines that open with these are dialogue, not attributions, even after a quotation.
    dialogue_openers = frozenset((
        "আমি", "আমাকে", "আমার", "তুমি", "তোমাকে", "তোমার", "আপনি", "আপনার",
        "সে", "তার", "তারা", "আমরা", "আমাদের", "এই", "এটা", "ওটা", "ওরা",
        "কি", "কী", "কেন", "কোথায়", "কেমন", "কত", "কে", "কবে", "কখন",
        "হ্যাঁ", "না", "চলো", "চল", "এসো", "যাও", "যাব", "দাও", "বলো", "শোনো",
    ))

    def fix_attribution(author: str) -> str:
        if any(author.startswith(w) for w in narration_verbs):
            return f"— {author}"
        return f"— বলেছিলেন {author}।"

    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.fullmatch(r"\s*[—–-]\s*([^।!?…]+?)\s*", line)
        if not m:
            continue
        author = m.group(1).strip()
        if not author or "..." in author or "…" in author or author.endswith("."):
            continue
        if len(author) > 45 or len(author.split()) > 6:
            continue
        if author.split()[0] in dialogue_openers:
            continue
        prev = next((lines[j].rstrip() for j in range(i - 1, -1, -1) if lines[j].strip()), "")
        if prev.endswith(closing_quotes):
            lines[i] = fix_attribution(author)
    return "\n".join(lines)



def chunk_text(raw_text: str) -> tuple[bool, list[str]]:
    """
    Parses Bangla text into chunks for TTS.
    If the first line is a chapter heading (starts with 'অধ্যায়' etc.), it is isolated
    so that an intentional 3-second post-title silence pause can follow it.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]
    if not paras:
        return False, []

    # Check if the very first line is a chapter title announcement
    # Handles markdown headers (# অধ্যায়), bolding, or standard text
    first_lines = [ln.strip() for ln in paras[0].splitlines() if ln.strip()]
    has_title_header = False
    start_idx = 0
    chunks = []

    if first_lines and re.match(r"^[#*_\s]*(?:অধ্যায়|অধ্যায়|ভূমিকা|মুখবন্ধ|সূচনা|উপসংহার|পরিশিষ্ট|প্রস্তাবনা|Chapter)", first_lines[0], re.IGNORECASE):
        has_title_header = True
        # Chunk 0 is the isolated chapter title line for the 3.0s post-title pause
        chunks.append(first_lines[0])
        # If paragraph 0 had subsequent lines, include them in the body paragraphs
        remaining_in_first = "\n".join(first_lines[1:]).strip()
        body_paras = ([remaining_in_first] if remaining_in_first else []) + paras[1:]
    else:
        body_paras = paras

    sentences = []
    for para in body_paras:
        # Split sentences by Dari, Exclamation, or Question, avoiding splitting inside ellipses '...'
        parts = [s for s in re.split(r"(?<!\.)(?<=[।!?])\s+", para.strip()) if s]
        if parts:
            parts[-1] += "\n"  # Keep breathing pause at end of paragraph
        sentences.extend(parts)

    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) > MAX_CHARS:
            chunks.append(buf.strip())
            buf = ""
        buf += s + " "
    if buf.strip():
        chunks.append(buf.strip())

    return has_title_header, chunks


async def synth(text: str, voice: str, rate: str, pitch: str, out: pathlib.Path) -> None:
    """Synthesize text via edge-tts with atomic file write and exponential backoff."""
    tmp = out.with_suffix(".tmp_synth")
    for attempt in range(1, 6):
        try:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(tmp))
            if tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(out)
                return
        except Exception as exc:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            if attempt == 5:
                raise RuntimeError(f"edge-tts failed for {out.name} after 5 attempts: {exc}")
            sleep_sec = 1.5 ** attempt
            await asyncio.sleep(sleep_sec)

    raise RuntimeError(f"edge-tts failed for {out.name}")


async def narrate_chapter(
    txt: pathlib.Path,
    audio_dir: pathlib.Path,
    intro_gap_file: pathlib.Path | None,
    title_gap_file: pathlib.Path | None,
    sem: asyncio.Semaphore,
    args,
    replacer,
) -> None:
    out = audio_dir / f"{txt.stem}.mp3"
    if out.exists() and out.stat().st_size > 0:
        return

    raw_text = txt.read_text(encoding="utf-8-sig")
    spoken_text = replacer(normalize_spoken_text(raw_text))
    has_title, parts = chunk_text(spoken_text)
    if not parts:
        return

    tmp = audio_dir / f"_{txt.stem}"
    tmp.mkdir(exist_ok=True)

    async def one(i: int, part: str) -> None:
        piece = tmp / f"{i:04d}.mp3"
        if piece.exists() and piece.stat().st_size > 0:
            return
        async with sem:  # up to --workers requests in flight concurrently
            await synth(part, args.voice, args.rate, args.pitch, piece)

    # Download pieces for this chapter concurrently
    await asyncio.gather(*(one(i, p) for i, p in enumerate(parts)))

    # Concatenate pieces cleanly into final chapter mp3
    partial = out.with_suffix(".part")
    is_chapter_start = has_title or txt.stem.endswith("_01") or ("_" not in txt.stem)
    with open(partial, "wb") as fh:
        # Insert 3.0s silence break before audio narration starts
        if is_chapter_start and intro_gap_file and intro_gap_file.exists():
            fh.write(intro_gap_file.read_bytes())
        for i in range(len(parts)):
            fh.write((tmp / f"{i:04d}.mp3").read_bytes())
            # If chunk 0 was the chapter title, insert the post-title pause right after it
            if i == 0 and has_title and title_gap_file and title_gap_file.exists():
                fh.write(title_gap_file.read_bytes())

    partial.replace(out)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  ✓ {out.name} ({len(parts)} chunks, intro={'yes' if is_chapter_start else 'no'}, title_pause={'yes' if has_title else 'no'})", flush=True)



async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--workers", type=int, default=4, help="number of parallel TTS synthesis workers (default 4)")
    ap.add_argument("--voice", default="bn-BD-NabanitaNeural")
    ap.add_argument("--rate", default="-4%")
    ap.add_argument("--pitch", default="+0Hz")
    ap.add_argument("--intro-pause", type=float, default=3.0, help="silence break in seconds before chapter audio narration starts (default 3.0s)")
    ap.add_argument("--title-pause", type=float, default=3.0, help="silence pause in seconds after reading chapter title announcement (default 3.0s)")
    ap.add_argument("--watch", action="store_true", help="watch bangla/ continuously and synthesize as files arrive")
    ap.add_argument("--no-enrich", dest="enrich_phonetics", action="store_false", default=True, help="disable automatic phonetic enrichment on completion (enabled by default)")
    ap.add_argument("--enrich-target", choices=["local", "global", "both"], default="both", help="target file for phonetic enrichment: 'local' (<workdir>/pronunciation.txt), 'global' (master phonetics.txt), or 'both' (default 'both')")
    args = ap.parse_args()

    work = pathlib.Path(args.workdir).resolve()
    audio_dir = work / "audio"
    audio_dir.mkdir(exist_ok=True)
    bangla_dir = work / "bangla"
    bangla_dir.mkdir(exist_ok=True)

    ff = ffmpeg_exe()
    # Generate 3.0-second intro silence in exact CBR MP3 format (24kHz mono 48k) before audio starts
    intro_gap_file = audio_dir / "_intro_gap.mp3"
    if args.intro_pause > 0:
        subprocess.run(
            [
                ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", str(args.intro_pause), "-c:a", "libmp3lame", "-b:a", "48k", "-write_xing", "0",
                "-id3v2_version", "0", "-write_id3v1", "0", str(intro_gap_file)
            ],
            check=True,
        )

    # Generate 3.0-second silence in exact CBR MP3 format (24kHz mono 48k) for post-title pause
    title_gap_file = audio_dir / "_title_gap.mp3"
    if args.title_pause > 0:
        subprocess.run(
            [
                ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", str(args.title_pause), "-c:a", "libmp3lame", "-b:a", "48k", "-write_xing", "0",
                "-id3v2_version", "0", "-write_id3v1", "0", str(title_gap_file)
            ],
            check=True,
        )


    phonetic_map = load_pronunciation_map(work)
    replacer = build_phonetic_replacer(phonetic_map)
    sem = asyncio.Semaphore(args.workers)
    print(f"TTS service started with {args.workers} workers, voice {args.voice} (watch={args.watch}, phonetic_rules={len(phonetic_map)})")

    def natural_sort_key(p: pathlib.Path):
        # Sort naturally by embedded numbers (e.g. 002_01.txt, 002_02.txt)
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", p.name)]

    try:
        while True:
            # Process pending chapters sequentially in numerical order
            # (intra-chapter chunks are downloaded in parallel by the 4 workers)
            all_txt = sorted(bangla_dir.glob("*.txt"), key=natural_sort_key)
            pending = [t for t in all_txt if not (audio_dir / f"{t.stem}.mp3").exists()]

            if pending:
                for t in pending:
                    try:
                        await narrate_chapter(t, audio_dir, intro_gap_file, title_gap_file, sem, args, replacer)
                    except Exception as exc:
                        print(f"Error narrating {t.name}: {exc}", file=sys.stderr)

            if not args.watch:
                break

            # In watch mode, check if translation is completed or partial and all work is done
            status_file = work / "translation_status.json"
            trans_done = False
            if status_file.exists():
                try:
                    s = json.loads(status_file.read_text(encoding="utf-8-sig"))
                    if s.get("status") in ("completed", "finished", "failed", "partial"):
                        trans_done = True
                except Exception:
                    pass

            # Check if any new pending files arrived
            new_pending = [t for t in bangla_dir.glob("*.txt") if not (audio_dir / f"{t.stem}.mp3").exists()]
            if trans_done and not new_pending:
                total_mp3 = len(list(audio_dir.glob("[0-9]*.mp3")))
                print(f"All available chapters synthesized ({total_mp3} audio files ready). TTS service finished.")
                break

            await asyncio.sleep(2)

        if args.enrich_phonetics:
            enrich_script = pathlib.Path(__file__).parent / "enrich_phonetics.py"
            if enrich_script.exists():
                print("\n[Phonetics] Automatically enriching phonetics from translations...")
                try:
                    cmd = [sys.executable, str(enrich_script), str(work)]
                    if args.enrich_target == "both":
                        cmd.append("--both")
                    elif args.enrich_target == "global":
                        cmd.append("--global")
                    subprocess.run(cmd, check=True)
                except Exception as exc:
                    print(f"[Phonetics] Enrichment notice: {exc}", file=sys.stderr)
    finally:
        if intro_gap_file and intro_gap_file.exists():
            intro_gap_file.unlink(missing_ok=True)
        if title_gap_file and title_gap_file.exists():
            title_gap_file.unlink(missing_ok=True)



if __name__ == "__main__":
    asyncio.run(main())
