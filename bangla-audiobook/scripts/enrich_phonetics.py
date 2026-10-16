"""Enrich and update Bengali TTS phonetic pronunciation rules from translated chapters.

Extracts vocabulary from <workdir>/bangla/*.txt, discovers words with phonetic ambiguity
(য-ফলা, ব-ফলা, ম-ফলা, ক্ষ, জ্ঞ, হ-যুক্তবর্ণ, বিসর্গ, সংবৃত ও-কারন্ত অতীত ক্রিয়াপদ),
and enriches the book's pronunciation.txt and/or master phonetics.txt.

Usage:
  python enrich_phonetics.py <workdir> [--global] [--both] [--target <path>] [--no-llm] [--model MODEL]
"""
import argparse
from collections import Counter
from datetime import datetime
import pathlib
import re
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")


def get_agy_exe() -> str | None:
    """Find the agy CLI executable on PATH or user directory."""
    exe = shutil.which("agy")
    if exe:
        return exe
    candidates = [
        pathlib.Path.home() / "AppData/Local/agy/bin/agy.exe",
        pathlib.Path.home() / "AppData/Local/agy/bin/agy.cmd",
        pathlib.Path.home() / ".local/bin/agy",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def get_global_phonetics_path() -> pathlib.Path:
    """Locate the master phonetics.txt in the skill root."""
    return pathlib.Path(__file__).resolve().parent.parent / "phonetics.txt"


def load_existing_map(workdir: pathlib.Path) -> dict[str, str]:
    """Load all currently active phonetic mappings across global and local files."""
    m = {}
    candidates = [
        get_global_phonetics_path(),
        pathlib.Path(__file__).resolve().parent / "phonetics.txt",
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
                    m[k.strip()] = v.strip()
    return m


def extract_words_from_translations(workdir: pathlib.Path) -> tuple[Counter, list[pathlib.Path]]:
    """Scan all translated chapter files and return word frequency counter."""
    bangla_dir = workdir / "bangla"
    files = []
    if bangla_dir.exists():
        files = sorted(bangla_dir.glob("*.txt"))
    if not files:
        # Fallback to source/ or workdir itself if bangla/ is empty or workdir is a single file
        if workdir.is_file() and workdir.suffix == ".txt":
            files = [workdir]
        elif (workdir / "source").exists():
            files = sorted((workdir / "source").glob("*.txt"))

    counter = Counter()
    for f in files:
        try:
            text = f.read_text(encoding="utf-8-sig")
            # Extract Bengali words exclusively
            words = re.findall(r"[\u0980-\u09ff]+", text)
            counter.update(words)
        except Exception as exc:
            print(f"Warning: could not read {f.name}: {exc}", file=sys.stderr)

    return counter, files


def derive_morphological_rules(word_freqs: Counter, existing_map: dict[str, str]) -> dict[str, str]:
    """
    Derives 100% deterministic phonetic rules for inflected forms of words
    that already exist in the master phonetic map.
    Example: If 'ব্যতিক্রম' -> 'বেতিক্ক্রম', then 'ব্যতিক্রমী' -> 'বেতিক্ক্রমি', 'ব্যতিক্রমের' -> 'বেতিক্ক্রমের'.
    """
    derived = {}
    # Common Bengali case endings, plurals, and suffixes
    suffixes = [
        ("ের", "ের"),
        ("র", "র"),
        ("কে", "কে"),
        ("তে", "তে"),
        ("য়ে", "য়ে"),
        ("য়ে", "য়ে"),
        ("এ", "এ"),
        ("রা", "রা"),
        ("দের", "দের"),
        ("গুলো", "গুলো"),
        ("গুলোর", "গুলোর"),
        ("গুলোয়", "গুলোয়"),
        ("গুলি", "গুলি"),
        ("গুলির", "গুলির"),
        ("হীন", "হীন"),
        ("যুক্ত", "যুক্ত"),
        ("ময়", "ময়"),
        ("ময়", "ময়"),
        ("ভিত্তিক", "ভিত্তিক"),
        ("জনিত", "জনিত"),
        ("শীল", "শীল"),
        ("গ্রস্ত", "গ্রস্ত"),
        ("তা", "তা"),
        ("মূলক", "মূলক"),
    ]

    for word in word_freqs:
        if word in existing_map:
            continue
        for suf_word, suf_phon in suffixes:
            if word.endswith(suf_word) and len(word) > len(suf_word) + 1:
                base = word[:-len(suf_word)]
                if base in existing_map:
                    base_phon = existing_map[base]
                    derived[word] = base_phon + suf_phon
                    break

    return derived


def derive_verb_colloquial_rules(word_freqs: Counter, existing_map: dict[str, str]) -> dict[str, str]:
    """
    Detects past tense Bengali verbs with flat consonant endings (e.g. বলল, করল, শুনল, গেল, পেল)
    and converts them to rounded spoken o-karant forms (বললো, করলো, শুনলো, গেলো, পেলো)
    for natural audio storytelling narration.
    """
    derived = {}
    verb_irregulars = {
        "দিল": "দিলো", "দিত": "দিতো",
        "নিল": "নিলো", "নিত": "নিতো",
        "গেল": "গেলো", "যেত": "যেতো",
        "পেল": "পেলো", "পেত": "পেতো",
        "হল": "হলো", "হত": "হতো",
        "খেল": "খেলো", "খেত": "খেতো",
        "আসল": "আসলো", "আসত": "আসতো",
    }
    for k, v in verb_irregulars.items():
        if k in word_freqs and k not in existing_map:
            derived[k] = v

    # Common verb roots that take -ল (past 3rd person) and -ত (habitual past)
    stems = [
        "বল", "কর", "চল", "দেখ", "শুন", "পড়", "পড়", "উঠ", "লাগ", "বস",
        "ভাব", "ফির", "থাক", "মান", "জান", "রাখ", "ডাক", "ছুট", "মার", "ধর",
        "হাস", "কাঁপ", "হার", "পৌঁছ", "বুঝ", "লিখ", "কাট", "মর", "টল", "সর",
        "লড়", "লড়", "চিন", "গড়", "গড়", "জিত", "জ্বল", "বাঁচ", "ছুঁ", "ছুট"
    ]
    for stem in stems:
        for suffix, target in [("ল", "লো"), ("ত", "তো")]:
            word = stem + suffix
            if word in word_freqs and word not in existing_map and word not in derived:
                derived[word] = stem + target

    return derived


def filter_phonetic_candidates(
    word_freqs: Counter,
    existing_map: dict[str, str],
    already_derived: dict[str, str],
    min_freq: int = 1,
    max_candidates: int = 150,
) -> list[tuple[str, int]]:
    """
    Finds words in translation containing phonetic ambiguity markers:
    য-ফলা, ব-ফলা, ম-ফলা, ক্ষ, জ্ঞ, হ-যুক্তবর্ণ, বিসর্গ, ত্ত্ব, etc.
    """
    # Pattern matching phonetically sensitive Bengali conjuncts
    sensitive_pat = re.compile(
        r"(?:[\u09cd][\u09af\u09ac\u09ae]|ক্ষ|জ্ঞ|হ[\u09cd\u09c3]|ঃ|ত্ব|ৎ|[ঋৃ])"
    )

    candidates = []
    for word, freq in word_freqs.most_common():
        if freq < min_freq or len(word) < 2:
            continue
        if word in existing_map or word in already_derived:
            continue
        if sensitive_pat.search(word):
            candidates.append((word, freq))
            if len(candidates) >= max_candidates:
                break

    return candidates


def query_llm_phonetics(
    candidates: list[str],
    agy_exe: str,
    model: str = "",
    effort: str = "",
) -> dict[str, str]:
    """
    Queries agy CLI using standard Bengali phonology principles (HSC & Bangla Academy Pronunciation Dictionary).
    Returns mapping of {original_word: phonetic_pronunciation}.
    """
    if not candidates:
        return {}

    prompt = (
        "You are an expert Bengali phonologist and standard Bangla pronunciation specialist "
        "(বাংলা একাডেমি উচ্চারণ অভিধান ও এইচএসসি উচ্চারণ নীতি).\n"
        "We are preparing text for Microsoft Neural Text-to-Speech (bn-BD-NabanitaNeural).\n"
        "Neural TTS mispronounces certain Bengali words containing:\n"
        "- য-ফলা (pronounced 'অ্যা' or 'এ' initially, or geminated medially)\n"
        "- ব-ফলা (silent or geminated)\n"
        "- ম-ফলা (silent, nasalized, or geminated)\n"
        "- ক্ষ (pronounced 'খ' initially, 'ক্খ' medially)\n"
        "- জ্ঞ (pronounced 'গ্যা' initially, 'গ্গ' medially)\n"
        "- হ-যুক্তবর্ণ (হ্ব, হ্ন, হ্ণ, হ্ম, হৃ)\n"
        "- বিসর্গ (ঃ) and gemination\n"
        "- সংবৃত 'অ' / ও-কারান্ত কথ্য রূপ\n\n"
        "Here are candidate words from our translated audiobook:\n"
        f"{', '.join(candidates)}\n\n"
        "Task:\n"
        "For words whose spoken pronunciation DIFFERS from the literal spelling in neural TTS, "
        "provide the phonetic respelling in Bengali script.\n\n"
        "STRICT OUTPUT RULES:\n"
        "1. Output ONLY lines in the exact format: শব্দ = উচ্চারণ\n"
        "2. Do NOT output regular words where pronunciation is identical to spelling (do NOT return X = X).\n"
        "3. Use standard Bengali script for the pronunciation.\n"
        "4. No markdown, no numbers, no explanations."
    )

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

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if res.returncode != 0:
            print(f"Warning: agy CLI error: {res.stderr.strip()}", file=sys.stderr)
            return {}

        results = {}
        candidate_set = set(candidates)
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            # Clean possible markdown bolding
            k = re.sub(r"^[\*\-_#\s]+|[\*\-_#\s]+$", "", k)
            v = re.sub(r"^[\*\-_#\s]+|[\*\-_#\s]+$", "", v)
            if k in candidate_set and k != v and re.match(r"^[\u0980-\u09ff\s\-]+$", v):
                results[k] = v

        return results
    except Exception as exc:
        print(f"Warning: LLM phonetic query failed: {exc}", file=sys.stderr)
        return {}


def append_to_file(filepath: pathlib.Path, new_rules: dict[str, str], header_label: str) -> int:
    """Appends new phonetic rules to target file avoiding duplicates."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    existing_keys = set()
    if filepath.exists():
        for line in filepath.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _ = line.split("=", 1)
                existing_keys.add(k.strip())

    to_add = [(k, v) for k, v in new_rules.items() if k not in existing_keys]
    if not to_add:
        return 0

    lines_to_write = []
    if filepath.exists() and filepath.stat().st_size > 0:
        lines_to_write.append("\n")

    lines_to_write.append(f"# === {header_label} ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
    for k, v in sorted(to_add, key=lambda x: len(x[0]), reverse=True):
        lines_to_write.append(f"{k} = {v}\n")

    with open(filepath, "a", encoding="utf-8") as fh:
        fh.writelines(lines_to_write)

    return len(to_add)


def main():
    parser = argparse.ArgumentParser(
        description="Enrich and update Bengali TTS phonetic rules from translated chapter text."
    )
    parser.add_argument("workdir", help="Path to audiobook working directory containing bangla/*.txt")
    parser.add_argument(
        "--global", "-g", dest="update_global", action="store_true",
        help="Update the master phonetics.txt in the skill root (affects all audiobooks)"
    )
    parser.add_argument(
        "--both", "-b", action="store_true",
        help="Update BOTH <workdir>/pronunciation.txt AND the skill's master phonetics.txt"
    )
    parser.add_argument(
        "--target", type=str, default="",
        help="Explicit file path to write phonetic overrides to (overrides defaults)"
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM analysis; use high-precision morphological & phonological rules only"
    )
    parser.add_argument(
        "--model", default="",
        help="Model to use with the CLI (default: the CLI's configured model)"
    )
    parser.add_argument(
        "--effort", default="",
        help="Reasoning effort for the CLI (default: the CLI's configured effort)"
    )
    parser.add_argument(
        "--max-candidates", type=int, default=120,
        help="Max candidate words to evaluate with LLM (default 120)"
    )
    parser.add_argument(
        "--min-freq", type=int, default=1,
        help="Minimum word frequency in translation to consider (default 1)"
    )
    args = parser.parse_args()

    work = pathlib.Path(args.workdir).resolve()
    if not work.exists():
        sys.exit(f"Error: workdir does not exist: {work}")

    print("=" * 60)
    print("  Bangla Audiobook Phonetic Enrichment Engine")
    print("=" * 60)

    # 1. Load active phonetics
    existing_map = load_existing_map(work)
    print(f"Loaded {len(existing_map)} existing phonetic pronunciation rules.")

    # 2. Extract words from translations
    word_freqs, files = extract_words_from_translations(work)
    if not files:
        sys.exit(f"No translation text files found in {work / 'bangla'}. Translate chapters first.")
    total_words = sum(word_freqs.values())
    unique_words = len(word_freqs)
    print(f"Scanned {len(files)} translation files: {total_words:,} total words ({unique_words:,} unique).")

    # 3. Derive Morphological Rules
    morph_rules = derive_morphological_rules(word_freqs, existing_map)
    print(f"Derived {len(morph_rules)} morphological inflection rules from existing phonetics.")

    # 4. Derive Past Tense Verb Colloquial Rules
    verb_rules = derive_verb_colloquial_rules(word_freqs, existing_map)
    print(f"Derived {len(verb_rules)} colloquial past tense verb rules (সংবৃত ও-কারন্ত কথ্য রূপ).")

    combined_derived = dict(morph_rules)
    combined_derived.update(verb_rules)

    # 5. Extract Candidate Words for LLM Phonetics
    llm_rules = {}
    if not args.no_llm:
        candidates = filter_phonetic_candidates(
            word_freqs,
            existing_map,
            combined_derived,
            min_freq=args.min_freq,
            max_candidates=args.max_candidates,
        )
        print(f"Identified {len(candidates)} high-priority phonetic candidates (য-ফলা, ব-ফলা, ক্ষ, জ্ঞ, etc.).")
        if candidates:
            agy_exe = get_agy_exe()
            if agy_exe:
                # Query in batches of 40 for optimal speed and accuracy
                batch_size = 40
                cand_words = [c[0] for c in candidates]
                for i in range(0, len(cand_words), batch_size):
                    batch = cand_words[i:i + batch_size]
                    print(f"  Analyzing batch {i // batch_size + 1}/{(len(cand_words) + batch_size - 1) // batch_size} ({len(batch)} words) via {args.model or 'default'}...")
                    b_rules = query_llm_phonetics(batch, agy_exe, model=args.model, effort=args.effort)
                    llm_rules.update(b_rules)
                print(f"LLM identified {len(llm_rules)} phonetic pronunciation respellings.")
            else:
                print("Note: agy CLI not found; skipping LLM stage. (Morphological and verb rules still apply).")

    # Combine all newly discovered rules
    all_new_rules = {}
    all_new_rules.update(combined_derived)
    all_new_rules.update(llm_rules)

    if not all_new_rules:
        print("\nAll translation vocabulary is already fully covered by active phonetics! No updates needed.")
        return

    print(f"\nDiscovered {len(all_new_rules)} new phonetic pronunciation rules:")
    sample = list(all_new_rules.items())[:10]
    for k, v in sample:
        print(f"  • {k} -> {v}")
    if len(all_new_rules) > 10:
        print(f"  ... and {len(all_new_rules) - 10} more.")

    # Determine targets
    targets = []
    if args.target:
        targets.append(pathlib.Path(args.target).resolve())
    elif args.both:
        targets.append(work / "pronunciation.txt")
        targets.append(get_global_phonetics_path())
    elif args.update_global:
        targets.append(get_global_phonetics_path())
    else:
        # Default: book-specific pronunciation file
        targets.append(work / "pronunciation.txt")

    header_label = f"Enriched from Translation: {work.name}"
    print("\nWriting rules to target destination(s):")
    for target in targets:
        added_count = append_to_file(target, all_new_rules, header_label)
        print(f"  ✓ Added {added_count} rules to {target}")

    if not (args.update_global or args.both):
        print(f"\n[Tip] To also merge these into the global master phonetics for all future books, run:")
        print(f"  python scripts/enrich_phonetics.py \"{work}\" --global")
    print("=" * 60)


if __name__ == "__main__":
    main()
