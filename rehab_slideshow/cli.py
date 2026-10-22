"""Command line interface for the narrated rehabilitation slideshow pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import audio, captions, illustrations, narrate, review, storyboard, video
from .exercises import list_exercises, load_exercise

ROOT = Path(__file__).resolve().parent.parent


def _fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def cmd_list(args) -> None:
    root = Path(args.root)
    files = list_exercises(root)
    if not files:
        print(f"no exercises in {root / 'exercises'}")
        return
    print(f"{'id':28} {'title':26} {'phase':14} storyboard")
    for path in files:
        ex = load_exercise(root, path.stem)
        has_sb = (root / "storyboards" / f"{path.stem}.json").exists()
        print(
            f"{ex.id:28} {ex.title:26} {ex.get('recovery_phase', ''):14} "
            f"{'yes' if has_sb else 'no'}"
        )


def cmd_validate(args) -> None:
    root = Path(args.root)
    ex = load_exercise(root, args.exercise)
    sb = storyboard.load_storyboard(root, ex.id)
    errors, warnings = storyboard.validate_storyboard(sb, ex)
    for warning in [*ex.warnings, *warnings]:
        print(f"warning: {warning}")
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"{ex.id}: {len(sb['frames'])} frames, metadata and storyboard are valid")


def cmd_build(args) -> None:
    root = Path(args.root)
    work = Path(args.work) / args.exercise
    out = Path(args.out) / args.exercise
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[1/8] loading exercise metadata")
    ex = load_exercise(root, args.exercise)
    for warning in ex.warnings:
        print(f"  warning: {warning}")

    print("[2/8] validating storyboard")
    sb = storyboard.load_storyboard(root, ex.id)
    errors, warnings = storyboard.validate_storyboard(sb, ex)
    for warning in warnings:
        print(f"  warning: {warning}")
    if errors:
        _fail("storyboard rejected:\n  - " + "\n  - ".join(errors))

    shutil.copyfile(ex.path, work / "exercise.yaml")
    (work / "storyboard.json").write_text(json.dumps(sb, indent=2) + "\n")
    (work / "cues.txt").write_text(
        "".join(f"# {c['id']}\n{c['text']}\n\n" for c in narrate.cues_from_storyboard(sb))
    )

    total = len(sb["frames"])
    print(f"[3/8] preparing {total} illustrations")
    (work / "overlays").mkdir(parents=True, exist_ok=True)
    frame_paths = []
    overlay_paths: list[Path] = []
    external = Path(args.frames_dir) if args.frames_dir else None
    persons = Path(args.person_dir) if getattr(args, "person_dir", None) else None
    for i, frame in enumerate(sb["frames"], start=1):
        frame["_index"] = i
        frame["_total"] = total
        name = f"frame-{frame['id']}.png"
        path = work / "frames" / name
        if external:
            source = external / name
            if not source.exists():
                _fail(f"missing pre-rendered frame {source}")
            from PIL import Image

            with Image.open(source) as img:
                if img.width < 1280 or img.height < 720:
                    _fail(f"{source} is {img.width}x{img.height}; minimum is 1280x720")
            if source.resolve() != path.resolve():
                shutil.copyfile(source, path)
        elif persons:
            from PIL import Image

            source = persons / f"canvas-{frame['id']}.png"
            if not source.exists():
                _fail(f"missing generated figure {source}")
            with Image.open(source) as img:
                person = img.convert("RGBA")
            illustrations.render_frame(ex.raw, frame, path, hi_res=True, person=person,
                                       with_overlay=False)
            overlay_path = work / "overlays" / name
            illustrations.render_overlay(ex.raw, frame).save(overlay_path)
            overlay_paths.append(overlay_path)
        else:
            illustrations.render_frame(ex.raw, frame, path, hi_res=True, with_overlay=False)
            overlay_path = work / "overlays" / name
            illustrations.render_overlay(ex.raw, frame).save(overlay_path)
            overlay_paths.append(overlay_path)
        frame_paths.append(path)
        print(f"  {name}  {frame['heading']}")

    print("[4/8] synthesising narration")
    cues = narrate.cues_from_storyboard(sb)
    manifest = narrate.narrate(
        cues, work / "narration", voice=args.voice, rate=args.rate, force=args.force_tts
    )
    print(f"  {manifest['voice']['name']} at {manifest['voice']['rate']}, "
          f"{manifest['total_speech_seconds']:.1f} s of speech")

    print("[5/8] building timeline and captions")
    timeline = captions.build_timeline(manifest["cues"], work / "narration")
    captions.quantize(timeline, video.FPS)
    total_seconds = captions.video_duration(timeline)
    srt = captions.write_srt(timeline, work / "captions.srt")
    ass = captions.write_ass(timeline, work / "captions.ass")

    print("[6/8] assembling audio master")
    built = audio.build_master(timeline, work / "master.wav", total_seconds, work / "audio")
    audio_info = audio.check_master(work / "master.wav", total_seconds)
    audio_info.update({k: v for k, v in built.items() if k not in audio_info})
    print(f"  master.wav {audio_info['duration']:.2f} s, peak "
          f"{audio_info['peak_after_normalise']:.2f} FS, clipped samples "
          f"{audio_info['clipped_samples']}")

    print("[7/8] rendering video track")
    track_info = video.build_track(
        frame_paths, timeline, work / "video-track.mp4", work,
        overlays=overlay_paths or None,
    )
    print(f"  video-track.mp4 {track_info['duration']:.2f} s, {track_info['segments']} segments")

    print("[8/8] burning captions and muxing final MP4")
    final = out / "final.mp4"
    video_info = video.finish(work / "video-track.mp4", work / "master.wav", ass, srt,
                              final, total_seconds)
    if abs(video_info["duration"] - total_seconds) > 0.25:
        _fail(
            f"final.mp4 is {video_info['duration']:.2f}s but the timeline is "
            f"{total_seconds:.2f}s; export rejected"
        )

    checks = review.run_checks(ex, sb, timeline, audio_info, video_info)
    if persons:
        backend = "SDXL + OpenPose ControlNet + IPAdapter; figures reviewed frame by frame"
    elif external:
        backend = f"pre-rendered frames from {external}"
    else:
        backend = "built-in deterministic vector renderer"
    status = review.write_review(out / "review.md", ex, sb, timeline, checks,
                                 audio_info, video_info, illustration=backend)

    print("\n" + "=" * 72)
    for name, ok, detail in checks:
        mark = review.CHECK if ok else review.CROSS
        print(f" {mark} {name}")
        if not ok:
            print(f"     {detail}")
    print("=" * 72)
    print(f"final: {final}  ({video_info['duration']:.1f} s, "
          f"{video_info['size_bytes'] / 1e6:.1f} MB)")
    print(f"review: {out / 'review.md'}")
    print(f"status: {status}")
    if not all(ok for _, ok, _ in checks):
        _fail("automatic safety review failed; the video must not be published")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rehab-slideshow",
        description="Build a narrated rehabilitation slideshow from a storyboard.",
    )
    parser.add_argument("--root", default=str(ROOT), help="repository root (default: project)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list exercises and their storyboard status")
    p_list.set_defaults(func=cmd_list)

    p_val = sub.add_parser("validate", help="validate exercise metadata and storyboard")
    p_val.add_argument("--exercise", required=True)
    p_val.set_defaults(func=cmd_validate)

    p_build = sub.add_parser("build", help="build the narrated MP4 end to end")
    p_build.add_argument("--exercise", required=True)
    p_build.add_argument("--voice", default=narrate.DEFAULT_VOICE, choices=list(narrate.VOICES))
    p_build.add_argument("--rate", default=narrate.DEFAULT_RATE)
    p_build.add_argument("--work", default="build", help="intermediate assets directory")
    p_build.add_argument("--out", default="out", help="deliverables directory")
    p_build.add_argument("--force-tts", action="store_true", help="re-synthesise every cue")
    p_build.add_argument(
        "--person-dir",
        help="use generated figure cut-outs (canvas-XX.png, RGBA 2560x1440) on top of the "
             "built-in room and text layout",
    )
    p_build.add_argument(
        "--frames-dir",
        help="use pre-rendered frame-XX.png illustrations (e.g. from a diffusion backend) "
             "instead of the built-in vector renderer",
    )
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
