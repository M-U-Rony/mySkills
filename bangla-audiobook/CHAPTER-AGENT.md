# Chapter Agent Brief

You are translating **one chapter** of a Bangla audiobook. You receive a `workdir` and a chapter number `N` (e.g. 7 → `007`). Confine all edits exclusively to chapter `NNN`.

## 1. Source Verification

The source chapter text resides in `source/NNN.txt`. Read it completely. If text appears scrambled by complex PDF columns or OCR artifacts, verify against the raw pages in `pages/` for that chapter's page range and restore the coherent reading.

## 2. Translation for Spoken Audio (ভাবানুবাদ ও শ্রুতিমধুর কথ্য রীতি)

Write translation files to `bangla/NNN.txt` (or `bangla/NNN_01.txt`, `bangla/NNN_02.txt` for long chapters). The text feeds directly into Microsoft Neural TTS (`bn-BD-NabanitaNeural`).

Produce fluent, literary চলিত Bangla crafted for live storytelling:
- **Literary Adaptation (ভাবানুবাদ)**: Re-create the emotional rhythm, imagery, and natural cadence of a master storyteller narrating to a captivated audience.
- **Audible Chapter Announcement**: The very first line of the chapter (or `_01.txt`) announces the chapter:
  ```
  অধ্যায় N: [অধ্যায়ের বাংলা নাম]
  ```
  Follow this line with an empty line. (The TTS engine injects an intentional 3.0s lead-in break before audio starts, and a 3.0s dramatic silence pause immediately after the chapter title). For continuation files (`_02.txt`, etc.), continue the narrative seamlessly without repeating any chapter heading.

### Voice Direction & Prosody via Text

Direct the neural voice's pitch and pacing through deliberate punctuation:
- **গভীর ভাব ও নাটকীয় বিরতি (Deep & Dramatic Pauses)**: Use `...` (ellipsis). The voice pauses, breathes, and lowers pitch. Apply before key revelations, hesitations, and contemplative moments.
- **আকস্মিক মোড় ও শ্বাস (Abrupt Shifts & Beats)**: Use `—` (em-dash) for sudden realizations, interrupted speech, or contrast.
- **উত্তেজনা ও উচ্চ স্বর (Intensity & Energy)**: Use `!` for urgent action, alarming developments, and heightened excitement.
- **কৌতূহল ও আরোহী সুর (Inquiry & Curiosity)**: Use `?` for inner questions, prompting natural pitch elevation.
- **শান্ত ও শীতল মেজাজ (Tranquility & Cool-down)**: For calm, reflective scenes, write flowing compound sentences with soothing transitions (`ধীরে ধীরে`, `একসময়`, `শান্ত হয়ে এলো চারিদিক...`, `অবশেষে`).
- **ভারী ও গম্ভীর বাক্য (Solemn Statements)**: Use short, decisive statements ending firmly with `।` or `...` so the voice delivers them with weight.

### Narration Conventions
- Output plain Bengali text exclusively. Clean out any asterisks, hashes, brackets, footnote markers, URLs, or symbols.
- Integrate footnotes and parenthetical clarifications naturally into spoken sentences.
- **উদ্ধৃতি ও লেখকের নাম (Quotes & Author Attributions)**:
  - **Never leave bare print-style attributions** like `—T. S. Eliot` or `— টি. এস. এলিয়ট`. In an audiobook, a bare em-dash followed by a name sounds abrupt and disjointed.
  - **Narrate attributions aloud as natural spoken phrases**:
    - Instead of: `"...বাণী..." —T. S. Eliot`
    - Write: `"...বাণী..." — বলেছিলেন টি এস এলিয়ট।` বা `"...বাণী..." — কথাটি টি এস এলিয়টের।`
  - **Avoid abbreviation periods in spoken initials**: Write `টি এস এলিয়ট` instead of `টি. এস. এলিয়ট` so the TTS engine does not misinterpret the dots as sentence breaks.
- Transliterate foreign names phonetically into standard Bangla script (Harry → হ্যারি). Adhere strictly to the spelling recorded in `glossary.txt`.
- Expand numerals, dates, abbreviations, and measurements into full spoken words (e.g. 1984 → উনিশশো চুরাশি, $50 → পঞ্চাশ ডলার).


### Long Chapters
For source texts exceeding 18,000 characters, partition into consecutive files (`bangla/NNN_01.txt`, `bangla/NNN_02.txt`) at natural paragraph breaks.

Done when the complete source chapter is faithfully translated and the concluding thought matches the source ending.
