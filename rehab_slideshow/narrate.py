"""Voice synthesis via edge-tts (Microsoft neural voices, no API key needed)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import edge_tts

VOICES = {
    "andrew": "en-US-AndrewNeural",
    "steffan": "en-US-SteffanNeural",
    "thomas": "en-GB-ThomasNeural",
    "eric": "en-US-EricNeural",
}
DEFAULT_VOICE = "andrew"
DEFAULT_RATE = "-8%"  # slower than default: easier to follow while moving


def _probe_duration(path: Path) -> float:
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def cues_from_storyboard(storyboard: dict) -> list[dict]:
    cues = []
    for frame in storyboard["frames"]:
        cues.append(
            {
                "id": f"cue-{frame['id']}",
                "frame": frame["id"],
                "text": frame["narration"].strip(),
            }
        )
    return cues


def _fingerprint(text: str, voice: str, rate: str) -> str:
    return hashlib.sha256(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]


async def _synth_all(jobs: list[tuple[dict, Path, str, str]]) -> None:
    async def one(cue, path, voice, rate):
        communicate = edge_tts.Communicate(cue["text"], voice, rate=rate)
        await communicate.save(str(path))

    await asyncio.gather(*(one(c, p, v, r) for c, p, v, r in jobs))


def narrate(
    cues: list[dict],
    out_dir: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    force: bool = False,
) -> dict:
    if voice not in VOICES:
        raise ValueError(f"unknown voice '{voice}' (choose from {', '.join(VOICES)})")
    voice_name = VOICES[voice]
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "narration.json"

    previous: dict[str, dict] = {}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text())
            previous = {c["id"]: c for c in old.get("cues", [])}
        except (json.JSONDecodeError, KeyError):
            previous = {}

    jobs, results = [], []
    for cue in cues:
        path = out_dir / f"{cue['id']}.mp3"
        fp = _fingerprint(cue["text"], voice_name, rate)
        cached = previous.get(cue["id"])
        reusable = (
            not force
            and path.exists()
            and cached
            and cached.get("fingerprint") == fp
            and cached.get("file") == path.name
        )
        if reusable:
            results.append({**cue, "file": path.name, "duration": cached["duration"],
                            "fingerprint": fp})
        else:
            jobs.append((cue, path, voice_name, rate))
            results.append(None)  # type: ignore[arg-type]

    if jobs:
        asyncio.run(_synth_all(jobs))

    final = []
    for cue, result in zip(cues, results):
        if result is None:
            path = out_dir / f"{cue['id']}.mp3"
            if not path.exists() or path.stat().st_size == 0:
                raise RuntimeError(f"voice synthesis produced no audio for {cue['id']}")
            result = {
                **cue,
                "file": path.name,
                "duration": round(_probe_duration(path), 3),
                "fingerprint": _fingerprint(cue["text"], voice_name, rate),
            }
        final.append(result)

    manifest = {
        "voice": {"key": voice, "name": voice_name, "rate": rate},
        "cue_count": len(final),
        "total_speech_seconds": round(sum(c["duration"] for c in final), 3),
        "cues": final,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
