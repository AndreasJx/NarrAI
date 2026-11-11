import argparse
import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from video_ai_contracts import Artifact, RenderRequest, SceneSpec, ShotSpec

from .tts import load_voice

WIDTH, HEIGHT, FPS = 1080, 1920, 30
# Stills are upscaled before zoompan so the slow zoom does not show pixel stepping.
KB_WIDTH, KB_HEIGHT, KB_ZOOM = 1620, 2880, 0.15
XFADE = 0.3
CLIP_VOLUME = 0.25
PALETTE = ["0x1d1b2e", "0x22314a", "0x2b2140", "0x173b35", "0x3a2431", "0x1f2a44"]
ProgressCallback = Callable[[int], None]
logger = logging.getLogger("narra.worker")


def scenes_from(request: RenderRequest) -> list[SceneSpec]:
    if request.scenes:
        return sorted(request.scenes, key=lambda scene: scene.position)
    lines = [line.strip() for line in request.script.split("\n") if line.strip()]
    return [SceneSpec(position=index, narration=line) for index, line in enumerate(lines, 1)]


def _ass_time(seconds: float) -> str:
    centis = int(round(seconds * 100))
    hours, rest = divmod(centis, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, centis = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_subtitles(path: Path, narration: str, duration: float, words_per_chunk: int = 5) -> None:
    words = narration.split()
    chunks = [words[i : i + words_per_chunk] for i in range(0, len(words), words_per_chunk)] or [[""]]
    total = sum(len(chunk) for chunk in chunks) or 1
    events, cursor = [], 0.0
    for chunk in chunks:
        span = duration * len(chunk) / total
        events.append(
            f"Dialogue: 0,{_ass_time(cursor)},{_ass_time(min(duration, cursor + span))},Caption,,0,0,0,,"
            f"{_ass_escape(' '.join(chunk))}"
        )
        cursor += span
    path.write_text(
        "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                f"PlayResX: {WIDTH}",
                f"PlayResY: {HEIGHT}",
                "WrapStyle: 0",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
                "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding",
                "Style: Caption,DejaVu Sans,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,1,"
                "2,90,90,420,1",
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                *events,
                "",
            ]
        ),
        encoding="utf-8",
    )


def media_decodes(path: str) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False
    dims = result.stdout.strip().split(",")
    return result.returncode == 0 and len(dims) >= 2 and all(value.strip().isdigit() and int(value) > 0 for value in dims[:2])


def has_audio(path: str) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _kenburns(effect: str, frames: int) -> str:
    if effect == "zoom_out":
        zoom = f"'{1 + KB_ZOOM}-{KB_ZOOM}*on/{frames}'"
    elif effect in {"pan_left", "pan_right"}:
        zoom = f"'{1 + KB_ZOOM * 0.8}'"
    else:
        zoom = f"'1+{KB_ZOOM}*on/{frames}'"
    if effect == "pan_left":
        x = f"'(iw-iw/zoom)*on/{frames}'"
    elif effect == "pan_right":
        x = f"'(iw-iw/zoom)*(1-on/{frames})'"
    else:
        x = "'iw/2-(iw/zoom/2)'"
    return f"zoompan=z={zoom}:x={x}:y='ih/2-(ih/zoom/2)':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"


def _shots_command(
    ffmpeg: str,
    shots: list[ShotSpec],
    index: int,
    audio: Path | None,
    duration: float,
    output: Path,
    clip_audio: set[int],
) -> tuple[list[str], list[dict]]:
    """One scene from several shots: Ken Burns on stills, trimmed clips, crossfades and ducked clip audio."""
    scale = duration / (sum(shot.duration for shot in shots) or duration)
    count = len(shots)
    lengths = [shot.duration * scale + (XFADE if position < count - 1 else 0) for position, shot in enumerate(shots)]
    inputs: list[str] = []
    filters: list[str] = []
    for position, (shot, length) in enumerate(zip(shots, lengths)):
        frames = max(1, round(length * FPS))
        # xfade needs every input at a constant frame rate and a common timebase.
        cut = f"trim=duration={length:.3f},setpts=PTS-STARTPTS,fps={FPS},settb=AVTB[v{position}]"
        if shot.media_path and shot.media_kind == "image":
            inputs += ["-i", shot.media_path]
            filters.append(
                f"[{position}:v]scale={KB_WIDTH}:{KB_HEIGHT}:force_original_aspect_ratio=increase,crop={KB_WIDTH}:{KB_HEIGHT},"
                f"setsar=1,{_kenburns(shot.effect, frames)},format=yuv420p,{cut}"
            )
        elif shot.media_path and shot.media_kind == "video":
            inputs += ["-stream_loop", "-1", "-ss", f"{shot.clip_start:.2f}", "-t", f"{length:.3f}", "-i", shot.media_path]
            filters.append(
                f"[{position}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
                f"setsar=1,fps={FPS},format=yuv420p,{cut}"
            )
        else:
            color = PALETTE[(index + position) % len(PALETTE)]
            inputs += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", f"color=c={color}:s={WIDTH}x{HEIGHT}:r={FPS}"]
            filters.append(f"[{position}:v]setsar=1,format=yuv420p,{cut}")
    last, offset = "v0", 0.0
    for position in range(1, count):
        offset += lengths[position - 1] - XFADE
        filters.append(f"[{last}][v{position}]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}[x{position}]")
        last = f"x{position}"
    filters.append(f"[{last}]subtitles=scene-{index}.ass[v]")

    inputs += ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    narration = count
    mix = [f"[{narration}:a]aresample=44100,aformat=channel_layouts=stereo,apad[narr]"]
    labels = ["[narr]"]
    timeline, start = [], 0.0
    for position, (shot, length) in enumerate(zip(shots, lengths)):
        if position in clip_audio:
            delay = round(start * 1000)
            mix.append(
                f"[{position}:a]atrim=duration={length:.3f},asetpts=PTS-STARTPTS,aresample=44100,"
                f"aformat=channel_layouts=stereo,volume={CLIP_VOLUME},adelay={delay}|{delay}[c{position}]"
            )
            labels.append(f"[c{position}]")
        visible = length - (XFADE if position < count - 1 else 0)
        timeline.append(
            {"shot": position + 1, "start": round(start, 2), "end": round(start + visible, 2), "asset_id": shot.asset_id,
             "kind": shot.media_kind or "generated", "role": shot.role, "effect": shot.effect}
        )
        start += visible
    if len(labels) > 1:
        mix.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0[a]")
    else:
        mix[0] = mix[0].replace("[narr]", "[a]")
    command = [
        ffmpeg, "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters + mix),
        "-map", "[v]", "-map", "[a]", "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(output),
    ]
    return command, timeline


def _scene_command(ffmpeg: str, scene: SceneSpec, index: int, audio: Path | None, duration: float, output: Path) -> list[str]:
    if scene.media_path and scene.media_kind == "image":
        visual = ["-loop", "1", "-framerate", str(FPS), "-i", scene.media_path]
    elif scene.media_path and scene.media_kind == "video":
        visual = ["-stream_loop", "-1", "-i", scene.media_path]
    else:
        color = PALETTE[index % len(PALETTE)]
        visual = ["-f", "lavfi", "-i", f"color=c={color}:s={WIDTH}x{HEIGHT}:r={FPS}"]
    sound = ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    video_filter = (
        f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},setsar=1,"
        f"fps={FPS},format=yuv420p,subtitles=scene-{index}.ass[v]"
    )
    audio_filter = "[1:a]aresample=44100,aformat=channel_layouts=stereo,apad[a]"
    return [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        *visual,
        *sound,
        "-filter_complex",
        f"{video_filter};{audio_filter}",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        f"{duration:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(output),
    ]


def run_ffmpeg(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, cwd=cwd)
    if result.returncode != 0:
        detail = " | ".join(line for line in result.stderr.strip().splitlines()[-4:] if line.strip())
        raise RuntimeError(f"FFmpeg falhou ({result.returncode}): {detail[:600]}")


def write_manifest(request: RenderRequest, scenes: list[SceneSpec], reason: str) -> Artifact:
    output_dir = Path(request.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"render-{request.render_id}.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "render_id": request.render_id,
                "status": "placeholder",
                "reason": reason,
                "target": {"width": WIDTH, "height": HEIGHT, "format": "mp4"},
                "script": request.script,
                "scenes": [scene.model_dump() for scene in scenes],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return Artifact(
        uri=str(manifest_path.resolve()),
        kind="manifest",
        metadata={"width": WIDTH, "height": HEIGHT, "renderer": "manifest"},
    )


def render_video(request: RenderRequest, on_progress: ProgressCallback | None = None) -> Artifact:
    scenes = scenes_from(request)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return write_manifest(request, scenes, "ffmpeg unavailable")
    report = on_progress or (lambda _: None)
    work = Path(request.output_dir) / f"render-{request.render_id}-work"
    work.mkdir(parents=True, exist_ok=True)
    voice = load_voice()
    voice_id = request.voice or "pf_dora"
    parts: list[Path] = []
    timeline: list[dict] = []
    total_duration = 0.0
    for index, scene in enumerate(scenes):
        if scene.media_path and not media_decodes(scene.media_path):
            logger.warning("Scene %s media is not decodable; using generated background", index)
            scene = scene.model_copy(update={"media_path": None, "media_kind": None})
        shots = [
            shot if not shot.media_path or media_decodes(shot.media_path)
            else shot.model_copy(update={"media_path": None, "media_kind": None})
            for shot in scene.shots
            if shot.duration >= 0.6
        ]
        audio: Path | None = None
        duration = scene.duration_seconds
        if voice:
            audio = work / f"scene-{index}.wav"
            spoken = voice.synthesize(scene.narration, audio, voice_id)
            duration = max(duration, spoken + 0.4)
        write_subtitles(work / f"scene-{index}.ass", scene.narration, duration)
        part = work / f"scene-{index}.mp4"
        if shots:
            clip_audio = {
                position
                for position, shot in enumerate(shots)
                if shot.role == "clip" and shot.media_kind == "video" and shot.media_path and has_audio(shot.media_path)
            }
            command, scene_timeline = _shots_command(ffmpeg, shots, index, audio, duration, part, clip_audio)
        else:
            command = _scene_command(ffmpeg, scene, index, audio, duration, part)
            scene_timeline = [{"shot": 1, "start": 0.0, "end": round(duration, 2), "asset_id": None,
                               "kind": scene.media_kind or "generated", "role": "scene", "effect": "none"}]
        run_ffmpeg(command, work)
        timeline += [
            {**item, "scene": scene.position, "start": round(total_duration + item["start"], 2), "end": round(total_duration + item["end"], 2)}
            for item in scene_timeline
        ]
        parts.append(part)
        total_duration += duration
        report(5 + int(85 * (index + 1) / len(scenes)))

    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
    video_path = Path(request.output_dir) / f"render-{request.render_id}.mp4"
    run_ffmpeg(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", "-movflags", "+faststart", str(video_path.resolve())],
        work,
    )
    shutil.rmtree(work, ignore_errors=True)
    report(95)
    return Artifact(
        uri=str(video_path.resolve()),
        kind="video",
        metadata={
            "width": WIDTH,
            "height": HEIGHT,
            "renderer": "ffmpeg",
            "tts": "kokoro" if voice else "silent",
            "voice": voice_id if voice else None,
            "scenes": len(scenes),
            "duration_seconds": round(total_duration, 2),
            "timeline": timeline,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-id", type=int, required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--voice", default=None)
    args = parser.parse_args()
    artifact = render_video(RenderRequest(**vars(args)))
    print(artifact.model_dump_json())


if __name__ == "__main__":
    main()
