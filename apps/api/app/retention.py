from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Asset, Scene, SceneShot

IMAGE_EFFECTS = ("zoom_in", "pan_left", "zoom_out", "pan_right")
MIN_SHOT, MAX_SHOT = 2.0, 4.0


@dataclass
class ShotPlan:
    shots: list[SceneShot] = field(default_factory=list)
    total_seconds: float = 0
    fair_use_seconds: float = 0
    dropped_clips: int = 0


def _score(asset: Asset) -> float:
    return float((asset.metadata_json or {}).get("score") or 0)


def plan_shots(
    db: Session,
    scenes: list[Scene],
    by_scene: dict[int, list[Asset]],
    clips: dict[int, Asset] | None = None,
    params: dict[str, Any] | None = None,
    max_clip_seconds: float = 8,
    max_fair_use_ratio: float = 0.2,
) -> ShotPlan:
    """Retention rules: strongest image in the first seconds, a visual change every 2-4s,
    a clip on script turns and the main reveal near 60% of the runtime."""
    params = params or {}
    clips = clips or {}
    shot_seconds = min(MAX_SHOT, max(MIN_SHOT, float(params.get("shot_seconds", 3))))
    reveal_ratio = float(params.get("reveal_ratio", 0.6))
    scene_ids = [scene.id for scene in scenes]
    if scene_ids:
        db.execute(delete(SceneShot).where(SceneShot.scene_id.in_(scene_ids)))

    manual = {scene.id: db.get(Asset, scene.media_asset_id) for scene in scenes if scene.media_asset_id}
    pools: dict[int, list[Asset]] = {}
    for scene in scenes:
        pool = sorted(by_scene.get(scene.id, []), key=_score, reverse=True)
        if manual.get(scene.id):
            pool = [manual[scene.id], *[asset for asset in pool if asset.id != manual[scene.id].id]]
        pools[scene.id] = pool
    everything = sorted({asset.id: asset for pool in pools.values() for asset in pool}.values(), key=_score, reverse=True)
    hook_asset = everything[0] if everything else None
    reveal_asset = everything[1] if len(everything) > 1 else hook_asset

    total = sum(scene.duration_seconds for scene in scenes) or 1
    plan = ShotPlan(total_seconds=total)
    elapsed = 0.0
    reveal_done = False
    previous_pool: list[Asset] = []
    for scene_index, scene in enumerate(scenes):
        pool = pools[scene.id] or previous_pool
        duration = scene.duration_seconds
        slots: list[tuple[Asset | None, str, float]] = []
        clip = clips.get(scene.id)
        if clip is not None:
            clip_length = min(max_clip_seconds, float((clip.metadata_json or {}).get("duration") or max_clip_seconds), duration)
            if plan.fair_use_seconds + clip_length <= max_fair_use_ratio * total:
                slots.append((clip, "clip", clip_length))
                plan.fair_use_seconds += clip_length
            else:
                plan.dropped_clips += 1
        remaining = duration - sum(slot[2] for slot in slots)
        count = max(1, round(remaining / shot_seconds)) if remaining > 0.5 else 0
        if scene_index == 0 and remaining > 3:
            count = max(count, 2)  # the hook shot stays short, so the opening scene always has a follow-up
        is_reveal = not reveal_done and (elapsed + duration) / total >= reveal_ratio
        for index in range(count):
            asset = pool[index % len(pool)] if pool else None
            role = "broll"
            if scene_index == 0 and index == 0 and hook_asset is not None:
                asset, role = hook_asset, "hook"
            elif is_reveal and index == 0 and reveal_asset is not None:
                asset, role = reveal_asset, "reveal"
                reveal_done = True
            slots.append((asset, role, remaining / count))
        if scene_index == 0 and slots and slots[0][1] == "hook" and len(slots) > 1:
            hook_length = min(2.5, slots[0][2])
            spare = slots[0][2] - hook_length
            slots[0] = (slots[0][0], "hook", hook_length)
            slots[1] = (slots[1][0], slots[1][1], slots[1][2] + spare)

        start = 0.0
        for position, (asset, role, length) in enumerate(slots, 1):
            effect = "none" if asset is not None and asset.kind == "video" else IMAGE_EFFECTS[(scene_index + position) % len(IMAGE_EFFECTS)]
            if role in {"hook", "reveal"} and effect != "none":
                effect = "zoom_in"
            shot = SceneShot(
                scene_id=scene.id,
                position=position,
                asset_id=asset.id if asset is not None else None,
                start=round(start, 2),
                duration=round(length, 2),
                effect=effect,
                clip_start=float((asset.metadata_json or {}).get("clip_start") or 0) if asset is not None else 0,
                role=role,
            )
            db.add(shot)
            plan.shots.append(shot)
            start += length
        elapsed += duration
        previous_pool = pool or previous_pool
    db.flush()
    return plan


def shots_for(db: Session, scene_ids: list[int]) -> dict[int, list[SceneShot]]:
    grouped: dict[int, list[SceneShot]] = {scene_id: [] for scene_id in scene_ids}
    if not scene_ids:
        return grouped
    for shot in db.scalars(select(SceneShot).where(SceneShot.scene_id.in_(scene_ids)).order_by(SceneShot.scene_id, SceneShot.position)):
        grouped[shot.scene_id].append(shot)
    return grouped


def credits_for(db: Session, script_version_id: int) -> list[str]:
    scenes = list(db.scalars(select(Scene).where(Scene.script_version_id == script_version_id)))
    asset_ids = {scene.media_asset_id for scene in scenes if scene.media_asset_id}
    for shots in shots_for(db, [scene.id for scene in scenes]).values():
        asset_ids |= {shot.asset_id for shot in shots if shot.asset_id}
    credits: list[str] = []
    for asset_id in sorted(asset_ids):
        attribution = ((db.get(Asset, asset_id).metadata_json or {}).get("attribution") or "").strip()
        if attribution and attribution not in credits:
            credits.append(attribution)
    return credits


def with_credits(description: str, credits: list[str]) -> str:
    if not credits or "Créditos:" in description:
        return description
    block = "Créditos:\n" + "\n".join(f"- {credit}" for credit in credits)
    return f"{description.rstrip()}\n\n{block}".strip()[:5000]
