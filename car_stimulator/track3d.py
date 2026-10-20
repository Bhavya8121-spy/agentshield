"""
track3d.py — bridges boulevard_racer.py's pseudo-3D simulation (segment
index + curve-per-segment + lane fraction x) into real 3D world transforms
for the Ursina/Panda3D scene in car.py.

This does NOT reimplement driving physics. It reads the same `segments`
list and the same `PlayerCar` state boulevard_racer.py already produces,
and answers one question: "given position=P and lane x=X right now, where
is that in 3D world space, and which way is the car facing?"

Two parts:
  1. build_centerline()  — pure math, no Ursina/Panda3D dependency.
     Walks the segment list once, turning each segment's `curve` value
     into a heading change, and lays down a polyline + heading array.
     Testable with plain python (see __main__ at the bottom).

  2. TrackView            — Ursina-dependent. Keeps GLB road/building
     entities instantiated only for segments near the player and
     destroys/recycles ones that fall out of range, instead of ever
     trying to place all TOTAL_SEGMENTS worth of geometry in the world
     at once (300 segments x ~2 roadside props each = way too many
     live Entities, and it wouldn't even loop visually since the
     pseudo-3D version "loops" by modulo-indexing into a track that's
     never actually built as a closed 3D loop).
"""

import math

from boulevard_racer import (
    SEGMENT_LENGTH, ROAD_WIDTH, TOTAL_SEGMENTS, build_world_segments,
    SPRITE_KIND_BUILDING,
)

# --- Tunables: these map pseudo-3D "world units" onto real Ursina/Panda3D
# scene units (meters, matching the Kenney kit's native scale). Nothing in
# boulevard_racer.py's own units (SEGMENT_LENGTH=200, ROAD_WIDTH=1600) is
# metric - they're pseudo-3D projection units. Pick these so one segment
# lines up with the length of a Kenney road-straight.glb tile, and so the
# road half-width lines up with that tile's actual half-width, then adjust
# by eye once models are in-scene.
WORLD_UNITS_PER_SEGMENT = 2.0     # length of one Kenney road tile, in scene units
ROAD_WORLD_HALF_WIDTH = 3.0       # half-width of the road, in scene units

# How strongly a segment's `curve` value (from ChunkBuilder, see
# boulevard_racer.py CURVE_EASY/MEDIUM/HARD) bends the world-space heading
# per segment. This has no "correct" value - boulevard_racer.py's curve is
# tuned for a screen-space projection trick, not a turn radius. Start here,
# then tune by driving through one curve_left/curve_right chunk and
# checking the bend looks like the pseudo-3D version's, not tighter/looser.
CURVE_TO_HEADING_RADIANS = 0.010


def build_centerline(segments):
    """Walk `segments` once and return (points, headings):
      points   - list of (x, z) world-space centerline positions, one
                 per segment boundary, len(segments)+1 entries
      headings - matching list of heading angles in radians (0 = +z)
    Straight segments (curve=0) just go straight; every non-zero curve
    rotates the heading a little before stepping forward, so curved
    chunks come out as an actual bend in world space instead of the
    screen-space-only bend the pseudo-3D renderer draws.
    """
    x, z = 0.0, 0.0
    heading = 0.0
    points = [(x, z)]
    headings = [heading]

    for seg in segments:
        heading += seg["curve"] * CURVE_TO_HEADING_RADIANS
        x += math.sin(heading) * WORLD_UNITS_PER_SEGMENT
        z += math.cos(heading) * WORLD_UNITS_PER_SEGMENT
        points.append((x, z))
        headings.append(heading)

    return points, headings


def sample_track(points, headings, position, lane_x):
    """Given the player's boulevard_racer.py `position` (float, world
    units along the track) and `lane_x` (float, -1..1 on-road, up to
    HARD_WALL_X near the shoulder), return (world_x, world_z, heading_rad)
    for placing an Entity in the 3D scene.

    Segment index wraps via modulo, same as boulevard_racer.py's own
    Game.segment_at() - so this stays correct even once `position` has
    gone past TOTAL_SEGMENTS worth of track (the pseudo-3D version treats
    the track as an endless loop of the same TOTAL_SEGMENTS segments).
    """
    seg_float = position / SEGMENT_LENGTH
    idx = int(seg_float) % TOTAL_SEGMENTS
    frac = seg_float - int(seg_float)

    idx_next = (idx + 1) % TOTAL_SEGMENTS
    # points/headings are indexed 0..TOTAL_SEGMENTS (closed by wrap in the
    # caller's segment list, so idx_next indexing into `points` is safe as
    # long as points has TOTAL_SEGMENTS+1 entries built from the full loop)
    x0, z0 = points[idx]
    x1, z1 = points[idx_next] if idx_next != 0 else points[idx + 1]
    h0 = headings[idx]
    h1 = headings[idx_next] if idx_next != 0 else headings[idx + 1]

    world_x = x0 + (x1 - x0) * frac
    world_z = z0 + (z1 - z0) * frac
    heading = h0 + (h1 - h0) * frac

    # lane_x is measured as a fraction of ROAD_WIDTH in boulevard_racer.py
    # (OFFROAD_X_LIMIT=1.0 is the road edge, HARD_WALL_X=2.35 is the
    # building line) - apply it in the SAME fraction against our own
    # ROAD_WORLD_HALF_WIDTH so a car hugging the shoulder in the 2D game
    # hugs the shoulder in the 3D scene too.
    right_x = math.cos(heading)
    right_z = -math.sin(heading)
    lateral = lane_x * ROAD_WORLD_HALF_WIDTH
    world_x += right_x * lateral
    world_z += right_z * lateral

    return world_x, world_z, heading


# ---------------------------------------------------------------------------
# Ursina-dependent streaming instancer. Import ursina lazily so
# build_centerline()/sample_track() above stay testable without a display.
# ---------------------------------------------------------------------------
class TrackView:
    """Keeps GLB road/building Entities live only for segments near the
    player's current position, and tears down ones that scroll out of
    the visible window. Call `.update(position)` once per frame.
    """

    VISIBLE_AHEAD = 40   # segments in front of the player to keep built
    VISIBLE_BEHIND = 5    # segments behind to keep built (rear-view mirror etc)

    def __init__(self, segments, points, headings, model_path_fn,
                 road_models, building_models, make_tree_fn):
        from ursina import Entity  # local import, see module docstring
        self._Entity = Entity
        self.segments = segments
        self.points = points
        self.headings = headings
        self.model_path_fn = model_path_fn
        self.road_models = road_models          # e.g. ['city-kit-roads/road-straight.glb', ...]
        self.building_models = building_models   # e.g. ['city-kit-suburban/building-type-e.glb', ...]
        self.make_tree_fn = make_tree_fn
        self.live = {}       # segment index -> list[Entity]
        self._last_center_idx = None

    def _spawn_segment(self, idx):
        Entity = self._Entity
        seg = self.segments[idx]
        x0, z0 = self.points[idx]
        h0 = self.headings[idx]
        heading_deg = math.degrees(h0)
        entities = []

        # Road tile: pick straight vs intersection piece from the flags
        # boulevard_racer.py already computed (is_intersection/has_light),
        # instead of re-deriving track shape a second time.
        road_file = self.road_models["intersection"] if seg["is_intersection"] \
            else self.road_models["straight"]
        path = self.model_path_fn(road_file)
        if path:
            e = Entity(model=path, position=(x0, 0, z0), rotation=(0, heading_deg, 0))
            entities.append(e)

        # Roadside sprites (buildings/trees) - reuse boulevard_racer.py's
        # own placement data (offset/scale/kind) instead of re-rolling
        # random placement, so the 3D city matches the 2D one's layout.
        for i, sprite in enumerate(seg["sprites"]):
            lane_x = sprite["offset"]  # already in "fraction of road half-width" units
            wx, wz, heading = sample_track(
                self.points, self.headings, idx * SEGMENT_LENGTH, lane_x)
            if sprite["kind"] == SPRITE_KIND_BUILDING:
                model_file = self.building_models[
                    (idx + i) % len(self.building_models)]
                path = self.model_path_fn(model_file)
                if path:
                    e = Entity(model=path, position=(wx, 0, wz),
                               rotation=(0, math.degrees(heading), 0),
                               scale=sprite.get("scale", 1.0))
                    entities.append(e)
            else:  # tree
                t = self.make_tree_fn()
                t.position = (wx, 0, wz)
                entities.append(t)

        self.live[idx] = entities

    def _despawn_segment(self, idx):
        for e in self.live.pop(idx, []):
            e.disable()  # Ursina: cheaper than destroy() if you'll reuse soon;
            # swap for destroy(e) if memory matters more than churn.

    def update(self, position):
        center_idx = int(position / SEGMENT_LENGTH) % TOTAL_SEGMENTS
        if center_idx == self._last_center_idx:
            return  # haven't crossed a segment boundary yet, nothing to do
        self._last_center_idx = center_idx

        wanted = {
            (center_idx + o) % TOTAL_SEGMENTS
            for o in range(-self.VISIBLE_BEHIND, self.VISIBLE_AHEAD)
        }
        for idx in list(self.live.keys()):
            if idx not in wanted:
                self._despawn_segment(idx)
        for idx in wanted:
            if idx not in self.live:
                self._spawn_segment(idx)


if __name__ == "__main__":
    # Pure-math smoke test - no Ursina needed. Confirms a straight chunk
    # goes dead-ahead (x stays ~0) and a curve chunk actually bends x away
    # from 0, before you ever wire this into the 3D scene.
    segs = build_world_segments(seed=1)
    pts, heads = build_centerline(segs)

    straight_run = [p for p, s in zip(pts[:15], segs[:15])]
    print("first 5 points (should be a straight line down +z):")
    for p in pts[:5]:
        print("  ", p)

    # find the first curved chunk and confirm x actually deviates
    for i, s in enumerate(segs):
        if abs(s["curve"]) > 0.5:
            print(f"\nfirst curved segment at index {i}, curve={s['curve']}")
            print("points around it:")
            for j in range(i, i + 10):
                print("  ", pts[j])
            break

    wx, wz, heading = sample_track(pts, heads, position=350.0, lane_x=0.5)
    print(f"\nsample_track(position=350.0, lane_x=0.5) -> "
          f"x={wx:.2f} z={wz:.2f} heading_deg={math.degrees(heading):.2f}")
