"""Translate all chapters concurrently using parallel agy CLI subagent workers.

Usage: python translate_chapters.py <workdir> [--workers 4] [--model MODEL] [--effort EFFORT]
The model and effort default to whatever the local CLI is already configured to use.
Reads <workdir>/source/NNN.txt and <workdir>/glossary.txt,
spawns agy subagents for all chapter chunks in parallel,
and writes <workdir>/bangla/NNN.txt (or NNN_01.txt, etc.).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import pathlib
import random
import re
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")


def get_agy_exe() -> str:
    import shutil
    exe = shutil.which("agy")
    if not exe:
        candidates = [
            pathlib.Path.home() / "AppData/Local/agy/bin/agy.exe",
            pathlib.Path.home() / ".local/bin/agy",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        raise SystemExit("agy CLI not found on PATH or in AppData/Local/agy/bin")
    return exe


def split_text_into_chunks(text: str, max_chars: int = 18000) -> list[str]:
    """Split source text at paragraph boundaries. 
    18,000 characters safely fits within the LLM's 8k completion token limit
    while preventing micro-fragmentation and excessive process spawn overhead.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text]

    chunks = []
    current = []
    curr_len = 0
    for p in paragraphs:
        # If an individual paragraph is abnormally long, break it by sentences
        if len(p) > max_chars:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]
            for s in sentences:
                if curr_len + len(s) > max_chars and current:
                    chunks.append("\n\n".join(current))
                    current = [s]
                    curr_len = len(s)
                else:
                    current.append(s)
                    curr_len += len(s)
            continue

        if curr_len + len(p) > max_chars and current:
            chunks.append("\n\n".join(current))
            current = [p]
            curr_len = len(p)
        else:
            current.append(p)
            curr_len += len(p)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def run_subagent_translation(
    prompt: str,
    agy_exe: str,
    model: str = "",
    effort: str = "",
    timeout: float = 900,
) -> str:
    """Execute non-interactive prompt with agy CLI with exponential backoff and jitter.

    No model/effort is passed unless explicitly requested, so the CLI uses whatever
    model the user already has configured. ``timeout`` (seconds) caps each attempt so
    a hung CLI can never block a worker forever.
    """
    cmd = [
        agy_exe,
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
    ]
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    cmd += ["-p", prompt, "--output-format", "text"]
    last_err = ""
    for attempt in range(1, 6):
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            last_err = f"timed out after {timeout:.0f}s"
            res = None

        if res is not None and res.returncode == 0 and res.stdout.strip():
            translated = res.stdout.strip()
            # Strip markdown code block fences if present
            if translated.startswith("```"):
                lines = translated.splitlines()
                if len(lines) > 2 and lines[-1].startswith("```"):
                    translated = "\n".join(lines[1:-1]).strip()
            return translated

        if res is not None:
            last_err = res.stderr.strip() if res.stderr.strip() else f"exit code {res.returncode}"
        # Exponential backoff with jitter
        sleep_sec = (2 ** attempt) + random.uniform(0.5, 2.0)
        print(f"    [Retry {attempt}/5] Translation failed ({last_err[:120]}). Retrying in {sleep_sec:.1f}s...", file=sys.stderr)
        time.sleep(sleep_sec)

    raise RuntimeError(f"Subagent returned empty or failed translation after 5 attempts. Stderr: {last_err}")


def translate_task(
    task: dict,
    agy_exe: str,
    glossary_section: str,
    model: str,
    effort: str,
    timeout: float,
) -> tuple[dict, str]:
    ch_idx = task["ch_idx"]
    part_idx = task["part_idx"]
    total_parts = task["total_parts"]
    title = task["title"]
    chunk = task["chunk"]
    out_file = task["out_file"]
    is_multi = task["is_multi"]

    if out_file.exists() and out_file.stat().st_size > 0:
        return task, "skipped"

    part_label = f" (Part {part_idx}/{total_parts})" if is_multi else ""

    if part_idx == 1:
        header_instruction = (
            f"1. First line MUST be the chapter announcement heading:\n"
            f"   অধ্যায় {ch_idx}: [অধ্যায়ের বাংলা নাম]\n"
            f"   Followed by a blank line."
        )
    else:
        header_instruction = (
            "1. Seamlessly continue the narration from the preceding part. "
            "Do NOT include any chapter title or announcement heading."
        )

    prompt = f"""You are an expert literary translator and audiobook narrator.
Translate Chapter {ch_idx} ({title}){part_label} into fluent, natural spoken চলিত Bengali for audiobook narration.

CORE PRINCIPLES:
- Translate the narrative flow, character emotion, and dramatic atmosphere as a master Bengali storyteller narrating aloud (ভাবানুবাদ).
{header_instruction}
- Direct voice prosody and pauses with punctuation:
  * '...' for solemn contemplation, dramatic suspense, and deep breathing pauses.
  * '—' for sudden beats, contrasting thoughts, or interrupted dialogue.
  * '!' for high energy, panic, or urgent action.
  * '?' for curiosity and rising pitch.
  * Smooth, flowing compound sentences for calm and serene passages.
- Quotes & Author Attributions: Never leave bare print-style attributions like '—T. S. Eliot' or '— টি. এস. এলিয়ট'. Turn them into natural spoken narration (e.g. '— বলেছিলেন টি এস এলিয়ট।' or '— কথাটি টি এস এলিয়টের।'). Transliterate all foreign names into Bengali script, and omit abbreviation dots in names (write 'টি এস এলিয়ট', not 'টি. এস.').
- Spell out abbreviations, numbers, and dates into full spoken Bengali words (e.g. ১৯০৫ -> উনিশশো পাঁচ).
- Output plain Bengali text exclusively without markdown markup, asterisks, brackets, or meta-comments.
{glossary_section}
SOURCE PASSAGE TO TRANSLATE:
{chunk}
"""
    print(f"Translating Chapter {ch_idx:03d}{part_label}: {title} ({len(chunk)} chars)...")
    translated = run_subagent_translation(prompt, agy_exe, model=model, effort=effort, timeout=timeout)
    out_file.write_text(translated, encoding="utf-8")
    print(f"✓ Saved Chapter {ch_idx:03d}{part_label} -> {out_file.name} ({len(translated)} chars)")
    return task, "done"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--workers", type=int, default=4, help="number of parallel translation workers (default 4)")
    ap.add_argument("--model", default="", help="model for translation (default: the CLI's configured model)")
    ap.add_argument("--effort", default="", help="reasoning effort (default: the CLI's configured effort)")
    ap.add_argument("--chunk-size", type=int, default=18000, help="max chars per translation chunk (default 18000)")
    ap.add_argument("--timeout", type=float, default=900, help="per-attempt timeout in seconds for the LLM CLI (default 900)")
    args = ap.parse_args()

    work = pathlib.Path(args.workdir).resolve()
    chapters_file = work / "chapters.json"
    if not chapters_file.exists():
        raise SystemExit(f"chapters.json not found in {work}")

    chapters = json.loads(chapters_file.read_text(encoding="utf-8-sig"))
    total_chapters = len(chapters)
    agy_exe = get_agy_exe()

    bangla_dir = work / "bangla"
    bangla_dir.mkdir(exist_ok=True)

    glossary_file = work / "glossary.txt"
    glossary_content = glossary_file.read_text(encoding="utf-8-sig").strip() if glossary_file.exists() else ""
    glossary_section = f"\nGLOSSARY OF NAMES & TERMS (use exact Bengali spellings):\n{glossary_content}\n" if glossary_content else ""

    # Build all translation tasks
    tasks = []
    for ch_idx, ch in enumerate(chapters, 1):
        src_file = work / "source" / f"{ch_idx:03d}.txt"
        if not src_file.exists():
            continue
        src_text = src_file.read_text(encoding="utf-8-sig")
        title = ch.get("title", f"Chapter {ch_idx}")
        chunks = split_text_into_chunks(src_text, max_chars=args.chunk_size)
        is_multi = len(chunks) > 1

        for part_idx, chunk in enumerate(chunks, 1):
            if is_multi:
                out_file = bangla_dir / f"{ch_idx:03d}_{part_idx:02d}.txt"
            else:
                out_file = bangla_dir / f"{ch_idx:03d}.txt"

            tasks.append({
                "ch_idx": ch_idx,
                "part_idx": part_idx,
                "total_parts": len(chunks),
                "title": title,
                "chunk": chunk,
                "out_file": out_file,
                "is_multi": is_multi,
            })

    total_tasks = len(tasks)
    pending_tasks = [t for t in tasks if not (t["out_file"].exists() and t["out_file"].stat().st_size > 0)]
    already_done = total_tasks - len(pending_tasks)

    print(f"Translation plan: {total_chapters} chapters partitioned into {total_tasks} chunks.")
    if already_done:
        print(f"Found {already_done}/{total_tasks} chunks already completed.")

    if not pending_tasks:
        print("All chunks are already translated!")
        status = {
            "status": "completed",
            "total_chapters": total_chapters,
            "total_chunks": total_tasks,
            "succeeded_count": total_tasks,
            "failed": [],
        }
        (work / "translation_status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
        return

    print(f"Starting parallel translation for {len(pending_tasks)} pending chunks with {args.workers} workers (model: {args.model or 'default'}, effort: {args.effort or 'default'})...")

    failed = []
    succeeded = already_done
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(translate_task, t, agy_exe, glossary_section, args.model, args.effort, args.timeout): t
            for t in pending_tasks
        }
        for future in as_completed(futures):
            t = futures[future]
            try:
                _, state = future.result()
                succeeded += 1
                print(f"  [{succeeded}/{total_tasks} chunks complete]")
            except Exception as e:
                err_msg = f"Chapter {t['ch_idx']:03d} Part {t['part_idx']}/{t['total_parts']}: {e}"
                print(f"Error in {err_msg}", file=sys.stderr)
                failed.append({
                    "chapter": t["ch_idx"],
                    "part": t["part_idx"],
                    "file": t["out_file"].name,
                    "error": str(e),
                })

    status = {
        "status": "completed" if not failed else "partial",
        "total_chapters": total_chapters,
        "total_chunks": total_tasks,
        "succeeded_count": succeeded,
        "failed": failed,
    }
    status_file = work / "translation_status.json"
    status_file.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Translation run finished: {succeeded}/{total_tasks} succeeded. Status written to {status_file.name}")


if __name__ == "__main__":
    main()
