"""Merge chapter audio into one MP3 with a short pause between chapters.

Usage: python merge.py <workdir> <output.mp3> [--title "..."] [--author "..."] [--gap 1.5]
Inserts the pause only when the 3-digit chapter prefix changes (so 004_01.mp3 + 004_02.mp3 play seamlessly).
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise SystemExit("ffmpeg not found: pip install imageio-ffmpeg")
        return exe


def natural_sort_key(p: pathlib.Path):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", p.name)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("output")
    ap.add_argument("--title", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--gap", type=float, default=1.5, help="pause in seconds between chapters (default 1.5s)")
    ap.add_argument("--intro", type=float, default=0.0, help="additional silence break in seconds before audiobook starts (default 0.0s, chapters include 3.0s intro)")
    ap.add_argument("--cleanup", action="store_true", default=False, help="delete intermediate working directory after successful merge")
    args = ap.parse_args()

    ff = ffmpeg_exe()
    work = pathlib.Path(args.workdir).resolve()
    files = sorted((work / "audio").glob("[0-9]*.mp3"), key=natural_sort_key)
    if not files:
        raise SystemExit("no audio files in audio/")

    # Silence as raw CBR frames in edge-tts's exact format (24 kHz mono 48 kbps, no headers),
    # so every piece can be byte-joined into one valid stream, then remuxed once for tags.
    silence = work / "audio" / "_silence.mp3"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", str(args.gap), "-c:a", "libmp3lame", "-b:a", "48k", "-write_xing", "0",
                    "-id3v2_version", "0", "-write_id3v1", "0", str(silence)], check=True)
    gap = silence.read_bytes()

    intro_bytes = b""
    if args.intro > 0:
        intro_file = work / "audio" / "_intro.mp3"
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                        "-t", str(args.intro), "-c:a", "libmp3lame", "-b:a", "48k", "-write_xing", "0",
                        "-id3v2_version", "0", "-write_id3v1", "0", str(intro_file)], check=True)
        intro_bytes = intro_file.read_bytes()
        intro_file.unlink(missing_ok=True)

    joined = work / "audio" / "_joined.mp3"
    prev = None
    with open(joined, "wb") as fh:
        if intro_bytes:
            fh.write(intro_bytes)
        for f in files:
            chapter = f.stem[:3]
            if prev is not None and chapter != prev:
                fh.write(gap)
            fh.write(f.read_bytes())
            prev = chapter


    out = pathlib.Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(joined),
                    "-c", "copy", "-id3v2_version", "3",
                    "-metadata", f"title={args.title}", "-metadata", f"artist={args.author}",
                    "-metadata", "genre=Audiobook", "-metadata", "language=ben", str(out)], check=True)
    silence.unlink(missing_ok=True)
    joined.unlink(missing_ok=True)
    print(f"merged {len(files)} files -> {out} ({out.stat().st_size / 1e6:.1f} MB)")

    if args.cleanup and out.exists() and out.stat().st_size > 0:
        import time
        # Ensure workdir is cleaned up completely
        for _ in range(3):
            shutil.rmtree(work, ignore_errors=True)
            if not work.exists():
                break
            time.sleep(0.5)
        print(f"Cleaned up all intermediate files in {work}")


if __name__ == "__main__":
    main()
