"""
Stage 4: Video Assembly

Renders each section using the Pillow frame renderer (Ken Burns + particles +
captions), concatenates with FFmpeg crossfades, mixes audio, and exports
final_video.mp4.

Adapted for Dev Life with Uche listicle format (variable point sections).
"""

import json
import random
import subprocess
import sys
from pathlib import Path

import config
from pipeline.frame_renderer import (
    render_section, CaptionRenderer, ParticleSystem, _load_font, WIDTH, HEIGHT,
)

from PIL import Image

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FPS = 30
CROSSFADE_DUR = 0.5
MUSIC_VOLUME = 0.12
MUSIC_FADEOUT = 10.0
ENDSCREEN_DUR = 20.0
ENDSCREEN_FADEIN = 1.0
ENDSCREEN_MUSIC_VOL = 0.20
INTRO_FADEIN = 1.5       # fade from black at start
INTRO_HOLD = 1.0         # silent hold after fade-in
INTRO_DUR = INTRO_FADEIN + INTRO_HOLD  # 2.5s total silent opening
VIDEO_BITRATE = "8M"
AUDIO_BITRATE = "192k"

MOTION_CYCLE = [
    ("zoom_in",        "falling"),
    ("pan_left_right", "suspended"),
    ("zoom_out",       "falling"),
    ("zoom_out_in",    "suspended"),
    ("still",          "falling"),
]


def _get_section_motion(sid: str, clip_index: int, point_index: int = 0) -> tuple[str, str]:
    """Assign motion and particle direction for a sub-scene clip."""
    if sid in ("hook", "intro"):
        p_dir = "falling"
    elif sid.startswith("point_"):
        p_dir = MOTION_CYCLE[point_index % len(MOTION_CYCLE)][1]
    elif sid in ("conclusion", "cta"):
        p_dir = "rising"
    else:
        p_dir = "suspended"
    all_motions = [m for m, _ in MOTION_CYCLE]
    motion = all_motions[clip_index % len(all_motions)]
    return (motion, p_dir)


# ---------------------------------------------------------------------------
# Caption overlay (post-concat, 1:1 narration sync)
# ---------------------------------------------------------------------------

def _overlay_captions(video_path: Path, output_path: Path, words: list[dict]) -> Path:
    """
    Decode video frame-by-frame, overlay karaoke captions, re-encode.

    frame_num / FPS = narration_time — perfect 1:1 sync because the
    narration audio plays continuously in the final video.
    """
    frame_size = WIDTH * HEIGHT * 3  # RGB24

    font = _load_font()
    captions = CaptionRenderer(words, font)

    # Probe total frames
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True,
    )
    vid_dur = float(probe.stdout.strip())
    total_frames = int(vid_dur * FPS)

    # Decoder
    decode_cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-v", "error",
        "pipe:1",
    ]

    # Encoder
    encode_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-v", "error",
        str(output_path),
    ]

    decoder = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    frame_num = 0
    last_pct = -1

    try:
        while True:
            raw = decoder.stdout.read(frame_size)
            if len(raw) < frame_size:
                break

            t = frame_num / FPS
            c_overlay = captions.render(t)

            if c_overlay.getbbox() is not None:
                frame = Image.frombytes("RGB", (WIDTH, HEIGHT), raw)
                frame = frame.convert("RGBA")
                frame = Image.alpha_composite(frame, c_overlay)
                raw = frame.convert("RGB").tobytes()

            encoder.stdin.write(raw)
            frame_num += 1

            pct = int(frame_num / total_frames * 100)
            if pct != last_pct and pct % 10 == 0:
                print(f"{pct}%", end=" ", flush=True)
                last_pct = pct

    finally:
        decoder.stdout.close()
        decoder.wait()
        encoder.stdin.close()
        encoder.wait()

    if encoder.returncode != 0:
        err = encoder.stderr.read().decode() if encoder.stderr else ""
        raise RuntimeError(f"Caption overlay encode failed: {err[-300:]}")

    return output_path


# ---------------------------------------------------------------------------
# Main assembly
# ---------------------------------------------------------------------------

def run(job_dir: Path) -> Path:
    ts_path = job_dir / "timestamps.json"
    narration_path = job_dir / "narration.mp3"
    images_dir = job_dir / "images"

    if not ts_path.exists():
        raise FileNotFoundError(f"timestamps.json not found in {job_dir}")
    if not narration_path.exists():
        raise FileNotFoundError(f"narration.mp3 not found in {job_dir}")

    timestamps = json.loads(ts_path.read_text())
    sections = timestamps["sections"]
    all_words = timestamps["words"]

    # Use actual narration duration as the authoritative total
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(narration_path)],
        capture_output=True, text=True,
    )
    total_duration = float(probe.stdout.strip())

    # Discover sub-scene images for each section
    scene_plan = []
    total_scenes = 0
    for sec in sections:
        sid = sec["id"]
        sub_images = sorted(images_dir.glob(f"{sid}_*.png"))
        if not sub_images:
            raise FileNotFoundError(f"No images found for section: {sid}")
        scene_plan.append((sec, sub_images))
        total_scenes += len(sub_images)

    print(f"\n{'=' * 50}")
    print(f"Stage 4: Video Assembly")
    print(f"{'=' * 50}\n")
    print(f"  Job: {job_dir.name}")
    print(f"  Narration: {total_duration:.1f}s ({total_duration / 60:.1f}min)")
    print(f"  Intro: {INTRO_DUR:.1f}s silent opening")
    print(f"  Sections: {len(sections)} ({total_scenes} sub-scenes)\n")

    # Check FFmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except FileNotFoundError:
        raise RuntimeError("FFmpeg not installed. Run: brew install ffmpeg")

    # -----------------------------------------------------------------
    # Render intro clip (2.5s: 1.5s fade from black + 1.0s hold, silent)
    # -----------------------------------------------------------------
    hook_img_path = images_dir / "hook_0.png"
    intro_clip = job_dir / "_clip_intro.mp4"

    print(f"  [intro] {INTRO_DUR:.1f}s (fade-in {INTRO_FADEIN}s + hold {INTRO_HOLD}s)...",
          end=" ", flush=True)

    num_intro_frames = int(INTRO_DUR * FPS)
    fadein_frames = int(INTRO_FADEIN * FPS)

    hook_src = Image.open(hook_img_path).convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)
    black_frame = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    particles = ParticleSystem()

    encode_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-v", "error",
        str(intro_clip),
    ]
    encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for i in range(num_intro_frames):
            frame = hook_src.copy().convert("RGBA")

            p_overlay = particles.render(i, "falling")
            frame = Image.alpha_composite(frame, p_overlay)

            if i < fadein_frames:
                alpha = i / fadein_frames
                frame = Image.blend(black_frame, frame, alpha)

            encoder.stdin.write(frame.convert("RGB").tobytes())
    finally:
        encoder.stdin.close()
        encoder.wait()

    if encoder.returncode != 0:
        err = encoder.stderr.read().decode() if encoder.stderr else ""
        raise RuntimeError(f"Intro encode failed: {err[-300:]}")

    size_mb = intro_clip.stat().st_size / (1024 * 1024)
    print(f"OK ({size_mb:.1f}MB)")

    # -----------------------------------------------------------------
    # Render each sub-scene with Pillow frame renderer
    # -----------------------------------------------------------------
    section_clips = [intro_clip]

    last_sid = sections[-1]["id"]

    num_crossfades = total_scenes
    section_sum = INTRO_DUR + sum(s["end"] - s["start"] for s in sections)
    compressed_duration = section_sum - num_crossfades * CROSSFADE_DUR
    target_main_duration = INTRO_DUR + total_duration
    closing_extra = max(0, target_main_duration - compressed_duration)

    END_HOLD = 0.0
    END_FADE = 1.5
    END_PADDING = END_HOLD + END_FADE

    point_index = 0
    clip_index = 0

    for sec, sub_images in scene_plan:
        sid = sec["id"]
        section_duration = sec["end"] - sec["start"]
        sub_duration = section_duration / len(sub_images)

        for sub_idx, img_path in enumerate(sub_images):
            is_last = (sid == last_sid and sub_idx == len(sub_images) - 1)

            duration = sub_duration
            if is_last:
                duration += closing_extra + END_PADDING

            fade = END_FADE if is_last else 0.0

            motion, p_dir = _get_section_motion(sid, clip_index, point_index)

            clip_path = job_dir / f"_clip_{clip_index}_{sid}_{sub_idx}.mp4"

            print(f"  [{clip_index + 1}/{total_scenes}] {sid}[{sub_idx}] ({duration:.1f}s, {motion}, {p_dir})...",
                  end=" ", flush=True)

            render_section(
                image_path=img_path,
                output_path=clip_path,
                duration=duration,
                motion=motion,
                zoom_amount=0.03,
                particle_direction=p_dir,
                fade_to_black=fade,
            )

            size_mb = clip_path.stat().st_size / (1024 * 1024)
            print(f"OK ({size_mb:.1f}MB)")
            section_clips.append(clip_path)
            clip_index += 1

        if sid.startswith("point_"):
            point_index += 1

    # -----------------------------------------------------------------
    # Concatenate clips with crossfade dissolves
    # -----------------------------------------------------------------
    print(f"\n  Concatenating with {CROSSFADE_DUR}s crossfades...", end=" ", flush=True)

    if len(section_clips) == 1:
        concat_path = section_clips[0]
    else:
        clip_durations = []
        for clip in section_clips:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(clip)],
                capture_output=True, text=True,
            )
            clip_durations.append(float(probe.stdout.strip()))

        filter_parts = []
        current_label = "[0:v]"
        cumulative = clip_durations[0] - CROSSFADE_DUR

        for i in range(1, len(section_clips)):
            next_label = f"[{i}:v]"
            out_label = f"[v{i}]" if i < len(section_clips) - 1 else "[vout]"
            filter_parts.append(
                f"{current_label}{next_label}xfade=transition=fade:"
                f"duration={CROSSFADE_DUR}:offset={cumulative:.3f}{out_label}"
            )
            cumulative += clip_durations[i] - CROSSFADE_DUR
            current_label = out_label

        filter_complex = ";".join(filter_parts)

        concat_path = job_dir / "_concat.mp4"
        cmd = ["ffmpeg", "-y"]
        for clip in section_clips:
            cmd.extend(["-i", str(clip)])
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "medium",
            "-b:v", VIDEO_BITRATE,
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            "-v", "warning",
            str(concat_path),
        ])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            print(f"FAIL")
            print(f"    stderr: {result.stderr[-800:]}")
            raise RuntimeError("FFmpeg concat failed")

        size_mb = concat_path.stat().st_size / (1024 * 1024)
        print(f"OK ({size_mb:.1f}MB)")

    # -----------------------------------------------------------------
    # Overlay captions on concatenated video (1:1 narration sync)
    # -----------------------------------------------------------------
    print(f"\n  Overlaying captions (1:1 narration sync)...", end=" ", flush=True)

    offset_words = [
        {**w, "start": w["start"] + INTRO_DUR, "end": w["end"] + INTRO_DUR}
        for w in all_words
    ]

    captioned_path = job_dir / "_concat_captioned.mp4"
    _overlay_captions(concat_path, captioned_path, offset_words)

    size_mb = captioned_path.stat().st_size / (1024 * 1024)
    print(f"OK ({size_mb:.1f}MB)")

    concat_path.unlink(missing_ok=True)
    concat_path = captioned_path

    # -----------------------------------------------------------------
    # Final mix: video + narration + optional music
    # -----------------------------------------------------------------
    print(f"  Final audio mix...", end=" ", flush=True)

    final_path = job_dir / "final_video.mp4"

    music_dir = config.ASSETS_DIR / "music"
    music_files = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav"))
    music_path = random.choice(music_files) if music_files else None

    intro_delay_ms = int(INTRO_DUR * 1000)

    if music_path:
        print(f"(music: {music_path.name})...", end=" ", flush=True)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(concat_path)],
            capture_output=True, text=True,
        )
        vid_dur = float(probe.stdout.strip())
        fade_start = max(0, vid_dur - MUSIC_FADEOUT)

        audio_filter = (
            f"[1:a]adelay={intro_delay_ms}|{intro_delay_ms}[narr];"
            f"[2:a]aloop=loop=-1:size=2e+09,atrim=0:{vid_dur},"
            f"volume={MUSIC_VOLUME},"
            f"afade=t=in:d=4,afade=t=out:st={fade_start}:d={MUSIC_FADEOUT}[music];"
            f"[narr][music]amix=inputs=2:duration=longest[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(concat_path),
            "-i", str(narration_path),
            "-i", str(music_path),
            "-filter_complex", audio_filter,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-v", "warning",
            str(final_path),
        ]
    else:
        print(f"(no music)...", end=" ", flush=True)
        audio_filter = f"[1:a]adelay={intro_delay_ms}|{intro_delay_ms}[narr]"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(concat_path),
            "-i", str(narration_path),
            "-filter_complex", audio_filter,
            "-map", "0:v",
            "-map", "[narr]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-v", "warning",
            str(final_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"FAIL")
        print(f"    stderr: {result.stderr[-800:]}")
        raise RuntimeError("FFmpeg final mix failed")

    print(f"OK")

    # -----------------------------------------------------------------
    # Append end screen (20s still from assets/endscreen.png)
    # -----------------------------------------------------------------
    endscreen_img = config.ASSETS_DIR / "endscreen.png"
    if endscreen_img.exists():
        print(f"  Appending end screen ({ENDSCREEN_DUR:.0f}s)...", end=" ", flush=True)

        endscreen_clip = job_dir / "_endscreen.mp4"
        num_es_frames = int(ENDSCREEN_DUR * FPS)
        fadein_frames = int(ENDSCREEN_FADEIN * FPS)

        es_src = Image.open(endscreen_img).convert("RGB")
        es_src = es_src.resize((WIDTH, HEIGHT), Image.LANCZOS)
        black_frame = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))

        encode_cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
            "-i", "pipe:0",
            "-c:v", "libx264", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-v", "error",
            str(endscreen_clip),
        ]
        encoder = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

        try:
            for i in range(num_es_frames):
                if i < fadein_frames:
                    alpha = i / fadein_frames
                    frame = Image.blend(black_frame, es_src, alpha)
                else:
                    frame = es_src
                encoder.stdin.write(frame.tobytes())
        finally:
            encoder.stdin.close()
            encoder.wait()

        if encoder.returncode != 0:
            err = encoder.stderr.read().decode() if encoder.stderr else ""
            raise RuntimeError(f"End screen encode failed: {err[-300:]}")

        main_with_endscreen = job_dir / "_final_with_endscreen.mp4"
        endscreen_matched = job_dir / "_endscreen_matched.mp4"

        es_music_path = None
        if music_files:
            es_music_path = random.choice(music_files)

        if es_music_path:
            es_fade_start = max(0, ENDSCREEN_DUR - 3.0)
            es_audio_filter = (
                f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{ENDSCREEN_DUR},"
                f"volume={ENDSCREEN_MUSIC_VOL},"
                f"afade=t=in:d=1,afade=t=out:st={es_fade_start}:d=3[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(endscreen_clip),
                "-i", str(es_music_path),
                "-filter_complex", es_audio_filter,
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                "-v", "warning",
                str(endscreen_matched),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                "-i", str(endscreen_clip),
                "-map", "1:v", "-map", "0:a",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                "-t", str(ENDSCREEN_DUR),
                "-v", "warning",
                str(endscreen_matched),
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"End screen audio mux failed: {result.stderr[-400:]}")

        concat_list = job_dir / "_concat_list.txt"
        concat_list.write_text(
            f"file '{final_path.resolve()}'\n"
            f"file '{endscreen_matched.resolve()}'\n"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-v", "warning",
            str(main_with_endscreen),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(final_path),
                "-i", str(endscreen_matched),
                "-filter_complex",
                "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[vout][aout]",
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "medium",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                "-v", "warning",
                str(main_with_endscreen),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(f"End screen concat failed: {result.stderr[-400:]}")

        final_path.unlink()
        main_with_endscreen.rename(final_path)

        endscreen_clip.unlink(missing_ok=True)
        endscreen_matched.unlink(missing_ok=True)
        concat_list.unlink(missing_ok=True)

        print(f"OK")
    else:
        print(f"  (no endscreen.png found, skipping)")

    # -----------------------------------------------------------------
    # Cleanup temp files
    # -----------------------------------------------------------------
    for clip in section_clips:
        clip.unlink(missing_ok=True)
    if concat_path != section_clips[0]:
        concat_path.unlink(missing_ok=True)

    # -----------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------
    file_size = final_path.stat().st_size

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(final_path)],
        capture_output=True, text=True,
    )
    final_duration = float(probe.stdout.strip())

    print(f"\n  Output: {final_path.name}")
    print(f"  Size: {file_size / (1024 * 1024):.1f}MB")
    print(f"  Duration: {final_duration:.1f}s ({final_duration / 60:.1f}min)")
    if endscreen_img.exists():
        print(f"  (includes {ENDSCREEN_DUR:.0f}s end screen)")
    print(f"\n  Stage 4 complete.\n")

    return job_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dev Life with Uche — Video Assembly (Stage 4)")
    parser.add_argument("--job", required=True, help="Path to job directory")
    args = parser.parse_args()

    job_dir = Path(args.job)
    if not job_dir.is_dir():
        print(f"ERROR: {job_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    try:
        run(job_dir)
    except Exception as e:
        print(f"\n  ERROR: {e}", file=sys.stderr)
        sys.exit(1)
