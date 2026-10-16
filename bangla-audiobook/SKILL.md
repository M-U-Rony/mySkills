---
name: bangla-audiobook
description: Create a narrated Bangla audiobook MP3 from a PDF. Use when the user requests converting a book, PDF, or text into a spoken Bangla audiobook.
---

Produces a polished, single-file Bangla MP3 audiobook from an input PDF. You act as the **orchestrator**: you inspect the book structure, plan chapters and phonetic glossary, launch concurrent chapter translation and streaming TTS narration, and merge the final audio.

The scripts reside in the `scripts/` directory alongside this `SKILL.md` (abbreviated below as `SCRIPTS`). Run all commands from the skill directory, or substitute an absolute path to `scripts/` if you run them from elsewhere.

Required dependencies:
```bash
python -m pip install pymupdf edge-tts imageio-ffmpeg
```
*(ffmpeg is provided automatically by `imageio-ffmpeg`)*

### Workdir Convention
Work lives in `<workdir>`, defaulting to `E:\audiobook\<book>_audiobook` (or `<pdf_parent>/<book>_audiobook` if `E:\audiobook` does not exist). The final audiobook MP3 is placed in the parent directory (`E:\audiobook` or `<pdf_parent>`).

```
<workdir>/
  pages/page_0001.txt   raw text per PDF page
  toc.json              extracted outline
  chapters.json         orchestrator chapter plan
  glossary.txt          consistent English -> Bangla character/place spellings
  source/001.txt        chapter text in original language
  bangla/001.txt        idiomatic Bangla translation (or 001_01.txt for long chapters)
  audio/001.mp3         chapter audio with 3.0s intro break and 3.0s post-title pause
```

Every stage checks existing files and skips completed items, ensuring instant, deterministic resume.

---

## 1. Extract PDF Structure

Run text and outline extraction:
```bash
python SCRIPTS/extract_pdf.py "<book.pdf>" ["<workdir>"]
```

The script outputs page counts, table-of-contents entries, and chapter-heading candidates. If over 50% of pages are empty, notify the user that the document is a scanned image requiring OCR.

**Completion Criterion**: `pages/` directory and `toc.json` exist in `<workdir>`, and candidate headings have been reviewed.

---

## 2. Plan Chapters & Glossary

### A. Chapters Plan (`chapters.json`)
Create `<workdir>/chapters.json` with 1-based, inclusive page ranges:
```json
[
  {"title": "Chapter 1: The Boy Who Lived", "start": 7, "end": 21},
  {"title": "Chapter 2: The Vanishing Glass", "start": 22, "end": 35}
]
```
- Compare `toc.json` against `pages/` to verify exact chapter boundaries (compensating for PDF page offsets).
- Focus on narrative content: include preface, prologue, all story chapters, and epilogue. Omit copyright notices, tables of contents, indices, and publisher advertisements.

### B. Consistent Glossary (`glossary.txt`)
Create `<workdir>/glossary.txt` containing one `English = বাংলা` transliteration per line for recurring character names, settings, and terminology:
```
Harry = হ্যারি
Hogwarts = হগওয়ার্টস
Dumbledore = ডাম্বলডোর
```

### C. Phonetic Pronunciation Tuning (`pronunciation.txt`, Optional)
By default, `tts.py` automatically normalizes common Bengali words that neural TTS mispronounces (e.g. `অভ্যাস` -> `অবভাশ`, `ব্যক্তি` -> `বেকতি`, `বিজ্ঞান` -> `বিগ্গ্যান`). To add book-specific pronunciation overrides, create `<workdir>/pronunciation.txt`:
```
ক্যালকুলাস = কেলকুলাস
আইনস্টাইন = আইনস্টাইন
```

**Completion Criterion**: `chapters.json` and `glossary.txt` are written with verified page boundaries and uniform name mappings.

---

## 3. Streaming Production: Translation & Background TTS

Execute production with real-time pipelining:

1. **Assemble Chapter Sources**:
   ```bash
   python SCRIPTS/split_chapters.py "<workdir>"
   ```
   Generates `source/001.txt`, `source/002.txt`, etc.

2. **Launch Background TTS Worker**:
   Start the streaming audio synthesizer in the background (as a background task):
   ```bash
   python SCRIPTS/tts.py "<workdir>" --watch --workers 4
   ```
   This worker monitors `bangla/`, synthesizes audio via `bn-BD-NabanitaNeural` as files arrive, inserts a 3.0-second break before chapter audio starts and a 3.0-second pause after each chapter announcement, and exits automatically when all chapters finish.

3. **Run Concurrent Chapter Translation**:
   ```bash
   python SCRIPTS/translate_chapters.py "<workdir>" --workers 4
   ```
   Translates all chapters simultaneously in parallel:
   - Employs evocative চলিত Bangla tailored for audio storytelling (ভাবানুবাদ).
   - Segments chapters exceeding 18,000 characters into consecutive files (`001_01.txt`, `001_02.txt`), maximizing token throughput while eliminating process-spawn bloat.
   - Runs the local agent CLI non-interactively (`--dangerously-skip-permissions`), using the model you already have configured. Pass `--model`/`--effort` only to override it.
   - Places the chapter announcement heading (`অধ্যায় N: [নাম]`) at the top of part 1.
   - Regulates voice pacing with punctuation (`...` for suspenseful pauses, `—` for sudden beats, `!` for intensity).
   - Writes completion status to `translation_status.json`.

**Completion Criterion**: All chapters in `chapters.json` have corresponding `.mp3` files in `audio/`, and the background TTS worker process exits cleanly.

---

## 4. Enrich & Update Phonetics from Translation

Phonetic enrichment runs **automatically by default** whenever TTS finishes synthesizing all chapters. It enriches both `<workdir>/pronunciation.txt` and the skill's master `phonetics.txt`.

You can also run it manually at any time to re-scan or inspect newly discovered phonetic rules:
```bash
python SCRIPTS/enrich_phonetics.py "<workdir>" [--both]
```
- Scans `bangla/*.txt` for words with phonetic ambiguity (য-ফলা, ব-ফলা, ম-ফলা, ক্ষ, জ্ঞ, হ-যুক্তবর্ণ, বিসর্গ, সংবৃত ও-কারন্ত অতীত ক্রিয়াপদ).
- Derives 100% accurate morphological inflections of known phonetics (e.g. `ব্যক্তিত্বের = বেকতিত্ত্বের`, `মনোবিজ্ঞানীদের = মনোবিগ্গানিদের`).
- Analyzes candidate vocabulary via the local agent CLI (`agy`), using your configured model, with standard Bengali pronunciation rules (বাংলা একাডেমি উচ্চারণ অভিধান ও এইচএসসি উচ্চারণ নীতি).
- Updates `<workdir>/pronunciation.txt` and the master `phonetics.txt` for all future audiobooks. (Pass `--no-enrich` to `tts.py` only if you wish to bypass this).

---

## 5. Audio Merge & Delivery

Combine chapter files into the final audiobook:
```bash
python SCRIPTS/merge.py "<workdir>" "<output_path>.mp3" --title "<Bangla Title>" --author "<Author>"
```

- Joins chapters with a 1.5-second silence interval and embeds ID3 metadata (Title, Artist, Genre: Audiobook, Language: ben).
- Leaves intermediate working files intact in `<workdir>` by default so any chapter can be re-voiced or edited without starting over. (Pass `--cleanup` only if intermediate deletion is explicitly requested).

**Completion Criterion**: The final merged MP3 exists, has a non-zero byte size, and its duration and file size are reported to the user.
