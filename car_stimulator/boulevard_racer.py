"""
Boulevard Racer - Pseudo-3D City Driving Game
==============================================
Rewritten from spec (Car_stimulator.txt) as a classic "sprite-scaling"
pseudo-3D racer (the OutRun technique): a chase camera follows the
player down a road built from short segments that are projected with
a simple perspective transform. Roadside sprites (buildings, trees) and
traffic cars are billboards that scale with distance.

Why this engine (instead of a true-3D pipeline): the assets that were
actually supplied are flat 2D sprites (buildings.png, driver_car.png,
side_car.png, trees.png) shot from a fixed camera angle, not 3D models.
A pure Pygame pseudo-3D renderer is the right tool for those assets,
needs no GPU/physics-engine dependencies, and is exactly the style the
spec describes (it even calls the target "pseudo-3D game" at the end).

Controls: Arrow keys / WASD to drive, SPACE = extra brake, ESC to quit.
"""

import os
import sys
import math
import random

import pygame

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SCREEN_W, SCREEN_H = 1000, 700
FPS = 60

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# --- Pseudo-3D projection constants (classic sprite-scaling racer) ---
FIELD_OF_VIEW = 100                # degrees
CAMERA_HEIGHT = 1100.0
CAMERA_DEPTH = 1.0 / math.tan((FIELD_OF_VIEW / 2.0) * math.pi / 180.0)

SEGMENT_LENGTH = 200.0             # world length of one road segment
RUMBLE_LENGTH = 3                  # segments per rumble/color stripe band
DRAW_DISTANCE = 180                # segments rendered ahead of camera
FOG_DENSITY = 5.0

LANES = 3
ROAD_WIDTH = 1600.0                # half-width of the road, world units

# --- "Var map": chunk based infinite city, per Car_stimulator.txt ---
# "Generate map chunks random. If map_chunks = 5, stop generate map
#  chunks, use the generated map chunks to make the map infinite."
# We generate exactly NUM_MAP_CHUNKS chunk templates once, then the
# renderer indexes into them with modulo arithmetic forever - i.e. the
# same 5 chunks are looped to build an endless road, with no unbounded
# memory growth. "If chunks not visible in person pov, extend chunks"
# is satisfied for free: only DRAW_DISTANCE segments around the player
# are ever looked up/rendered per frame.
CHUNK_LENGTH = 60                  # segments per chunk
NUM_MAP_CHUNKS = 5
TOTAL_SEGMENTS = CHUNK_LENGTH * NUM_MAP_CHUNKS
TRACK_LENGTH = TOTAL_SEGMENTS * SEGMENT_LENGTH

# --- Car spec, transcribed from Car_stimulator.txt's stat sheet ---
# 2.0L Turbo I4, 250HP/350Nm, 6-speed auto, FWD, 1400kg, low CG,
# 32 degree max steering, ~5.2m turning radius, 210 km/h top speed,
# 0-60mph in ~6.0s, 4-wheel disc+ABS, traction/stability control on.
TOP_SPEED_KMH = 210.0
TOP_SPEED = TOP_SPEED_KMH * 1000.0 / 3600.0 * (SEGMENT_LENGTH / 10.0)  # world units / sec (tuned to track scale)
ACCEL = TOP_SPEED / 6.0            # "0-60 in ~6.0 sec" feel
BRAKING = -ACCEL * 3.4             # 4-wheel disc + ABS -> strong, controlled stopping
REVERSE_ACCEL = -ACCEL * 0.55
OFFROAD_DECEL = -ACCEL * 1.5
OFFROAD_MAX_SPEED = TOP_SPEED * 0.4
MAX_STEER_DEG = 32.0               # spec: "Max steering angle 32 degrees"
CITY_SPEED_LIMIT_KMH = 90.0        # "certain speed limit which makes it possible to drive in a city"
COLLISION_DECEL = -ACCEL * 6.0

# Colors
SKY_TOP = (94, 165, 226)
SKY_HORIZON = (183, 219, 240)
COLORS = {
    "LIGHT": dict(road=(105, 105, 108), grass=(34, 140, 60), rumble=(210, 60, 60), lane=None),
    "DARK": dict(road=(96, 96, 100), grass=(28, 122, 52), rumble=(230, 230, 230), lane=(230, 230, 230)),
}

SPRITE_KIND_BUILDING = "building"
SPRITE_KIND_TREE = "tree"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def percent_remaining(n, total):
    return (n % total) / total


def make_point(x=0.0, y=0.0, z=0.0):
    return {
        "world": {"x": x, "y": y, "z": z},
        "camera": {"x": 0.0, "y": 0.0, "z": 0.0},
        "screen": {"x": 0.0, "y": 0.0, "w": 0.0, "scale": 0.0},
    }


def project(p, camera_x, camera_y, camera_z, width, height, road_width):
    p["camera"]["x"] = p["world"]["x"] - camera_x
    p["camera"]["y"] = p["world"]["y"] - camera_y
    p["camera"]["z"] = p["world"]["z"] - camera_z
    cz = p["camera"]["z"]
    if cz < 1.0:
        cz = 1.0
    scale = CAMERA_DEPTH / cz
    p["screen"]["scale"] = scale
    p["screen"]["x"] = (width / 2) + (scale * p["camera"]["x"] * width / 2)
    p["screen"]["y"] = (height / 2) - (scale * p["camera"]["y"] * height / 2)
    p["screen"]["w"] = scale * road_width * width / 2


# ---------------------------------------------------------------------------
# TRACK / CHUNK GENERATION
# ---------------------------------------------------------------------------
# "Var trees: Generate trees in middle of two lane road"
# "Generate buildings on the side of the roads to make it look like city.
#  If one style of building provided place a small size and then long and
#  then randomly to make it look real"
# "Var road_type: If hit traffic light then the road must be two lane and
#  four sides with crossroads..."
#
# Each element of `segments` is a lightweight dict. Curves are RELATIVE
# (added up fresh every frame starting at the camera), so we never need to
# store absolute world-x for the whole track - only a small curve value,
# a color band, and a list of roadside sprites per segment index.

CURVE_NONE = 0.0
CURVE_EASY = 0.55
CURVE_MEDIUM = 1.1
CURVE_HARD = 1.8

BUILDING_SCALE_PATTERN = [0.62, 1.5, None]  # small, long/tall, then random - cycles

# How wide a building sprite is actually drawn, in units of the road's
# projected half-width, before the per-instance `scale` multiplier is
# applied (must match base_frac used in Game._draw_roadside_sprite).
BUILDING_DRAW_FRAC = 1.55
# Minimum gap (in the same half-road-width units) between the road edge
# and the near face of a building/tree, i.e. the sidewalk. Sprite offsets
# are derived from this + the sprite's own half-width so bigger buildings
# get pushed back instead of hanging over the road.
ROAD_SHOULDER_CLEARANCE = 1.05


def segment_color(index):
    return COLORS["DARK"] if (index // RUMBLE_LENGTH) % 2 else COLORS["LIGHT"]


class ChunkBuilder:
    """Builds one chunk (CHUNK_LENGTH segments) of road: a curve profile,
    roadside buildings/trees, and at most one traffic-light intersection."""

    def __init__(self, rng, chunk_id, allow_intersection):
        self.rng = rng
        self.chunk_id = chunk_id
        self.allow_intersection = allow_intersection
        self.building_cycle = 0  # shared small/long/random cycle counter

    def build(self):
        rng = self.rng
        segs = []

        # Pick an overall curve shape for the chunk. First/last few segments
        # of every chunk are kept straight so chunks always join seamlessly
        # (including the wrap-around from the last chunk back to the first).
        pattern = rng.choice(["straight", "curve_left", "curve_right", "s_curve"])
        curve_strength = rng.choice([CURVE_EASY, CURVE_MEDIUM, CURVE_HARD])
        transition = 8

        intersection_at = None
        if self.allow_intersection and rng.random() < 0.7:
            intersection_at = rng.randint(CHUNK_LENGTH // 2 - 6, CHUNK_LENGTH // 2 + 6)

        for i in range(CHUNK_LENGTH):
            curve = 0.0
            if i < transition or i > CHUNK_LENGTH - transition:
                curve = 0.0
            elif pattern == "curve_left":
                curve = -curve_strength
            elif pattern == "curve_right":
                curve = curve_strength
            elif pattern == "s_curve":
                half = (CHUNK_LENGTH - 2 * transition) / 2.0
                pos = i - transition
                curve = -curve_strength if pos < half else curve_strength

            seg = {
                "curve": curve,
                "sprites": [],       # list of dicts: kind, offset, scale, flip
                "is_intersection": False,
                "has_light": False,
                "light_phase": 0.0,
            }
            segs.append(seg)

        # Roadside buildings & filler trees, skipping the intersection band.
        skip_lo, skip_hi = -1, -1
        if intersection_at is not None:
            skip_lo, skip_hi = intersection_at - 4, intersection_at + 4

        i = transition
        while i < CHUNK_LENGTH - transition:
            if skip_lo <= i <= skip_hi:
                i += 1
                continue
            self._place_roadside_pair(segs, i, rng)
            i += rng.choice([3, 4, 5])

        if intersection_at is not None:
            self._place_intersection(segs, intersection_at, rng)

        return segs

    def _next_building_scale(self):
        pattern = BUILDING_SCALE_PATTERN[self.building_cycle % len(BUILDING_SCALE_PATTERN)]
        self.building_cycle += 1
        if pattern is None:
            return random.uniform(0.75, 1.35)
        return pattern

    @staticmethod
    def _building_offset_for_scale(scale, rng):
        # A building is drawn BUILDING_DRAW_FRAC * scale wide (in units of
        # the road's projected half-width), centered on its offset. For the
        # sprite's inner edge to clear the road surface - instead of
        # visually intruding onto/over the lanes, which is what made
        # buildings look like they were crowding or touching the road -
        # the offset has to grow with scale, not be a fixed small range.
        half_draw_width = (BUILDING_DRAW_FRAC * scale) / 2.0
        min_offset = ROAD_SHOULDER_CLEARANCE + half_draw_width
        return min_offset + rng.uniform(0.0, 0.35)

    def _place_roadside_pair(self, segs, i, rng):
        # Left side
        if rng.random() < 0.85:
            scale = self._next_building_scale()
            offset = self._building_offset_for_scale(scale, rng)
            segs[i]["sprites"].append({
                "kind": SPRITE_KIND_BUILDING, "offset": -offset,
                "scale": scale, "flip": False,
            })
        else:
            segs[i]["sprites"].append({
                "kind": SPRITE_KIND_TREE, "offset": -rng.uniform(1.15, 1.3),
                "scale": rng.uniform(0.8, 1.1), "flip": False,
            })

        # Right side
        if rng.random() < 0.85:
            scale = self._next_building_scale()
            offset = self._building_offset_for_scale(scale, rng)
            segs[i]["sprites"].append({
                "kind": SPRITE_KIND_BUILDING, "offset": offset,
                "scale": scale, "flip": True,
            })
        else:
            segs[i]["sprites"].append({
                "kind": SPRITE_KIND_TREE, "offset": rng.uniform(1.15, 1.3),
                "scale": rng.uniform(0.8, 1.1), "flip": True,
            })

    def _place_intersection(self, segs, center, rng):
        for i in range(center - 1, center + 2):
            if 0 <= i < CHUNK_LENGTH:
                segs[i]["is_intersection"] = True
        segs[center]["has_light"] = True
        # phase offset so not every intersection in the world is synced
        segs[center]["light_phase"] = rng.uniform(0, 9.0)
        # "Generate trees in middle of two lane road" -> median trees on
        # the crossing street, drawn as part of the intersection band.
        segs[center]["median_trees"] = True


def build_world_segments(seed=None):
    rng = random.Random(seed)
    segments = []
    for c in range(NUM_MAP_CHUNKS):
        # keep the very first chunk intersection-free so the player gets a
        # few clean seconds to learn the controls before any crossroad
        builder = ChunkBuilder(rng, c, allow_intersection=(c != 0))
        segments.extend(builder.build())
    assert len(segments) == TOTAL_SEGMENTS
    return segments


# ---------------------------------------------------------------------------
# ASSET LOADING
# ---------------------------------------------------------------------------
def load_image_safe(path, fallback_size=(200, 200), fallback_color=(200, 60, 60)):
    try:
        img = pygame.image.load(path).convert_alpha()
        return img
    except Exception as e:
        print(f"[assets] could not load {path}: {e}")
        surf = pygame.Surface(fallback_size, flags=pygame.SRCALPHA)
        surf.fill(fallback_color)
        return surf


class ScaledCache:
    """Caches pygame.transform.scale() results keyed by (id, w, h) so the
    same roadside sprite at a similar apparent distance isn't rescaled
    from scratch every single frame."""

    def __init__(self, max_items=256):
        self.cache = {}
        self.order = []
        self.max_items = max_items

    def get(self, image, key, w, h):
        if w < 1 or h < 1:
            return None
        w = int(w)
        h = int(h)
        cache_key = (key, w, h)
        hit = self.cache.get(cache_key)
        if hit is not None:
            return hit
        try:
            scaled = pygame.transform.scale(image, (w, h))
        except Exception:
            return None
        self.cache[cache_key] = scaled
        self.order.append(cache_key)
        if len(self.order) > self.max_items:
            old = self.order.pop(0)
            self.cache.pop(old, None)
        return scaled


class Assets:
    def __init__(self):
        self.building = load_image_safe(os.path.join(ASSET_DIR, "buildings.png"),
                                          fallback_color=(180, 140, 110))
        self.tree = load_image_safe(os.path.join(ASSET_DIR, "trees.png"),
                                     fallback_color=(40, 120, 40))
        self.player_car = load_image_safe(os.path.join(ASSET_DIR, "driver_car.png"),
                                           fallback_color=(210, 30, 30))
        self.traffic_car = load_image_safe(os.path.join(ASSET_DIR, "side_car.png"),
                                            fallback_color=(30, 60, 210))
        self.building_flipped = pygame.transform.flip(self.building, True, False)
        self.tree_flipped = pygame.transform.flip(self.tree, True, False)
        self.cache = ScaledCache()


# ---------------------------------------------------------------------------
# TRAFFIC LIGHTS & PEDESTRIANS
# "Var traffic_light: shows a rod with extended metal that shows the red,
#  yellow, green light."
# "If people are crossing the road: traffic light red"
# ---------------------------------------------------------------------------
LIGHT_CYCLE = 9.0   # seconds: 4 green, 1 yellow, 4 red
LIGHT_GREEN_END = 4.0
LIGHT_YELLOW_END = 5.0


def traffic_light_state(total_time, phase):
    t = (total_time + phase) % LIGHT_CYCLE
    if t < LIGHT_GREEN_END:
        return "green", (t / LIGHT_GREEN_END)
    elif t < LIGHT_YELLOW_END:
        return "yellow", (t - LIGHT_GREEN_END) / (LIGHT_YELLOW_END - LIGHT_GREEN_END)
    else:
        return "red", (t - LIGHT_YELLOW_END) / (LIGHT_CYCLE - LIGHT_YELLOW_END)


def draw_traffic_light(surface, x, y, scale, state):
    scale = clamp(scale, 0.05, 4.0)
    pole_w = max(2, int(3 * scale))
    pole_h = int(70 * scale)
    pygame.draw.rect(surface, (55, 55, 58), (int(x - pole_w / 2), int(y - pole_h), pole_w, pole_h))
    # horizontal arm extending over the road, per spec "a rod with extended metal"
    arm_len = int(34 * scale)
    pygame.draw.rect(surface, (55, 55, 58), (int(x - arm_len), int(y - pole_h), arm_len, max(2, int(2.4 * scale))))

    box_w, box_h = max(6, int(15 * scale)), max(14, int(36 * scale))
    box_x = int(x - arm_len - box_w * 0.6)
    box_y = int(y - pole_h - box_h * 0.5)
    pygame.draw.rect(surface, (20, 20, 22), (box_x, box_y, box_w, box_h), border_radius=max(1, int(3 * scale)))

    r = max(2, int(4.2 * scale))
    base = (55, 55, 55)
    lit = {"red": (235, 45, 45), "yellow": (245, 205, 35), "green": (55, 215, 95)}[state]
    order = ["red", "yellow", "green"]
    for i, name in enumerate(order):
        cy = box_y + r + 2 + i * (r * 2 + max(2, int(2 * scale)))
        color = lit if name == state else base
        pygame.draw.circle(surface, color, (int(x - arm_len - box_w * 0.6 + box_w / 2), int(cy)), r)


def draw_pedestrian(surface, x, y, scale, walk_phase, color=(60, 60, 70)):
    scale = clamp(scale, 0.05, 3.0)
    r = max(2, int(3.4 * scale))
    bob = math.sin(walk_phase * 10.0) * 1.5 * scale
    head_y = y - int(12 * scale) + bob
    pygame.draw.circle(surface, (235, 200, 170), (int(x), int(head_y)), r)
    pygame.draw.line(surface, color, (x, head_y + r), (x, y), max(1, int(2.2 * scale)))
    leg_spread = int(4 * scale)
    pygame.draw.line(surface, color, (x, y), (x - leg_spread, y + int(8 * scale)), max(1, int(2 * scale)))
    pygame.draw.line(surface, color, (x, y), (x + leg_spread, y + int(8 * scale)), max(1, int(2 * scale)))


class Pedestrian:
    """A single pedestrian instance that walks across an intersection's
    crosswalk while the light is red for cars."""

    def __init__(self, side, speed_bias):
        self.side = side  # -1 start left, +1 start right
        self.speed_bias = speed_bias
        self.color = random.choice([(50, 50, 60), (90, 60, 40), (40, 70, 90), (80, 40, 70)])


# ---------------------------------------------------------------------------
# TRAFFIC / AI CARS
# ---------------------------------------------------------------------------
def lane_offset(lane, lanes=LANES):
    # returns x offset in fraction-of-half-road-width units, centered lanes
    return -1.0 + (2.0 * lane + 1.0) / lanes


class TrafficCar:
    def __init__(self, z, lane, speed):
        self.z = z
        self.lane = lane
        self.x = lane_offset(lane)
        self.speed = speed

    def update(self, dt):
        self.z += self.speed * dt


# ---------------------------------------------------------------------------
# PLAYER CAR PHYSICS
# Arcade handling tuned to feel like the spec sheet: FWD, 250HP turbo,
# 32-degree quick steering, 4-wheel disc+ABS, traction/stability control
# on (forgiving, hard to spin out), can stop and reverse, top speed 210
# km/h, gentle city-friendly acceleration curve.
# ---------------------------------------------------------------------------
STEER_SENSITIVITY = 2.6      # x-units/sec of full lateral travel at top speed
CENTRIFUGAL_CONST = 0.32     # how hard curves pull the car sideways
OFFROAD_X_LIMIT = 1.0        # |x| beyond this is grass/sidewalk
HARD_WALL_X = 2.35           # buildings start blocking around here


class PlayerCar:
    def __init__(self):
        self.position = 0.0     # world z, always >= 0, grows as you drive
        self.x = 0.0            # lane position, fraction of half road width
        self.speed = 0.0        # world units / sec (can be negative = reverse)
        self.steer_input = 0.0
        self.throttle = False
        self.brake = False

        self.crash_timer = 0.0
        self.crash_spin = 0.0
        self.crash_count = 0
        self.scrape_flash = 0.0

    @property
    def crashed(self):
        return self.crash_timer > 0.0

    @property
    def speed_kmh(self):
        return abs(self.speed) / (SEGMENT_LENGTH / 10.0) * 3.6

    @property
    def gear(self):
        # purely cosmetic 6-speed automatic indicator
        frac = clamp(abs(self.speed) / TOP_SPEED, 0.0, 1.0)
        return 1 if self.speed <= 0.5 and not self.throttle and frac < 0.02 else max(1, min(6, int(frac * 6) + 1))

    def trigger_crash(self):
        if self.crash_timer <= 0:
            self.crash_timer = 1.3
            self.crash_spin = 0.0
            self.crash_count += 1

    def update(self, dt, segment_curve, get_max_speed_kmh=None):
        if self.crash_timer > 0:
            self.crash_timer -= dt
            self.crash_spin += dt * 16.0
            self.speed = lerp(self.speed, 0.0, min(1.0, dt * 3.0))
            self.position = max(0.0, self.position + self.speed * dt)
            return

        offroad = abs(self.x) > OFFROAD_X_LIMIT

        # --- longitudinal physics: throttle / brake / reverse / coasting ---
        if self.brake:
            if self.speed > 0.02:
                self.speed = max(0.0, self.speed + BRAKING * dt)
            else:
                self.speed = max(REVERSE_ACCEL * 1.0 * 1.0, self.speed + REVERSE_ACCEL * dt)
        elif self.throttle:
            top = TOP_SPEED if not offroad else OFFROAD_MAX_SPEED
            if self.speed >= 0:
                self.speed = min(top, self.speed + ACCEL * dt)
            else:
                # braking out of reverse
                self.speed = min(0.0, self.speed - REVERSE_ACCEL * dt)
        else:
            # engine braking / natural coast to a stop
            coast = -ACCEL * 0.35
            if self.speed > 0:
                self.speed = max(0.0, self.speed + coast * dt)
            elif self.speed < 0:
                self.speed = min(0.0, self.speed - coast * dt)

        if offroad and self.speed > OFFROAD_MAX_SPEED:
            self.speed = max(OFFROAD_MAX_SPEED, self.speed + OFFROAD_DECEL * dt)

        # --- lateral physics: speed-sensitive steering + centrifugal pull ---
        speed_frac = clamp(abs(self.speed) / TOP_SPEED, 0.18, 1.0)
        direction = 1.0 if self.speed >= 0 else -1.0
        self.x += self.steer_input * STEER_SENSITIVITY * speed_frac * direction * dt
        self.x -= segment_curve * clamp(self.speed / TOP_SPEED, 0.0, 1.0) * CENTRIFUGAL_CONST * dt

        if abs(self.x) > HARD_WALL_X:
            self.x = clamp(self.x, -HARD_WALL_X, HARD_WALL_X)
            if abs(self.speed) > TOP_SPEED * 0.15:
                self.scrape_flash = 0.15
            self.speed *= 0.92

        self.scrape_flash = max(0.0, self.scrape_flash - dt)

        self.position = max(0.0, self.position + self.speed * dt)


# ---------------------------------------------------------------------------
# LOW-LEVEL DRAW HELPERS
# ---------------------------------------------------------------------------
def poly(surface, color, pts):
    try:
        pygame.draw.polygon(surface, color, pts)
    except (ValueError, TypeError):
        pass


def fog_blend_color(color_dict, factor, fog_color=SKY_HORIZON):
    """Fades a segment's palette toward the horizon color with distance -
    hides the alternating-stripe moire banding far away and gives the
    skyline a soft, natural fade instead of a hard draw-distance cutoff."""
    if factor <= 0.001:
        return color_dict
    factor = clamp(factor, 0.0, 1.0)

    def blend(c):
        if c is None:
            return None
        return (
            int(lerp(c[0], fog_color[0], factor)),
            int(lerp(c[1], fog_color[1], factor)),
            int(lerp(c[2], fog_color[2], factor)),
        )

    return {k: blend(v) for k, v in color_dict.items()}


def draw_road_segment(surface, x1, y1, w1, x2, y2, w2, color, lanes=LANES):
    r1 = w1 / max(6, 2 * lanes)
    r2 = w2 / max(6, 2 * lanes)
    l1 = w1 / max(32, 8 * lanes)
    l2 = w2 / max(32, 8 * lanes)

    # --- grass first, full width; road painted on top of it next so the
    # road always wins where the two would overlap ("If road overlaps
    # grass: Show road, avoid rendering grass on road") ---
    top = max(0, min(y1, y2))
    bottom = min(SCREEN_H, max(y1, y2))
    if bottom > top:
        pygame.draw.rect(surface, color["grass"], (0, top, SCREEN_W, bottom - top))

    poly(surface, color["rumble"], [(x1 - w1 - r1, y1), (x1 - w1, y1), (x2 - w2, y2), (x2 - w2 - r2, y2)])
    poly(surface, color["rumble"], [(x1 + w1, y1), (x1 + w1 + r1, y1), (x2 + w2 + r2, y2), (x2 + w2, y2)])
    poly(surface, color["road"], [(x1 - w1, y1), (x1 + w1, y1), (x2 + w2, y2), (x2 - w2, y2)])

    if color.get("lane"):
        lanew1 = w1 * 2 / lanes
        lanew2 = w2 * 2 / lanes
        lanex1 = x1 - w1 + lanew1
        lanex2 = x2 - w2 + lanew2
        for _ in range(1, lanes):
            poly(surface, color["lane"], [(lanex1 - l1 / 2, y1), (lanex1 + l1 / 2, y1),
                                            (lanex2 + l2 / 2, y2), (lanex2 - l2 / 2, y2)])
            lanex1 += lanew1
            lanex2 += lanew2


def draw_billboard(surface, assets, image_key, image, dest_x, dest_y_bottom, draw_w, draw_h):
    if draw_w < 1 or draw_h < 1:
        return
    if dest_x + draw_w < 0 or dest_x > SCREEN_W or dest_y_bottom < 0 or dest_y_bottom - draw_h > SCREEN_H:
        return
    scaled = assets.cache.get(image, image_key, draw_w, draw_h)
    if scaled is None:
        return
    surface.blit(scaled, (dest_x, dest_y_bottom - draw_h))


# World half-length of the cross street, expressed in the same units as
# ROAD_WIDTH so it can be projected with the identical camera/scale math
# the main road uses (see draw_intersection_band).
CROSS_STREET_HALF_WORLD = ROAD_WIDTH * 2.7


def draw_intersection_band(surface, p1, p2, has_light, light_st, median_trees, assets, total_time):
    """Perpendicular crossroad, projected with the SAME camera/scale/
    ground-plane math as the main road (draw_road_segment) instead of a
    flat, constant-width rectangle. p1/p2 are this segment's own near/far
    projected points, so the crossroad's near and far edges sit exactly
    on the road's existing vanishing-point geometry: it recedes into the
    distance like everything else instead of looking pasted on a
    different plane."""
    if p1["scale"] <= 0.00001 or p2["scale"] <= 0.00001:
        return
    y_near, y_far = p1["y"], p2["y"]
    if y_far >= y_near:
        return

    # Screen half-width of the cross street at the near/far edges, using
    # the exact same (scale * world_length) relationship the road trapezoid
    # uses for its own half-width - this is what makes it converge toward
    # the horizon correctly instead of staying a fixed screen width.
    cross_w_near = p1["w"] * (CROSS_STREET_HALF_WORLD / ROAD_WIDTH)
    cross_w_far = p2["w"] * (CROSS_STREET_HALF_WORLD / ROAD_WIDTH)
    cx_near, cx_far = p1["x"], p2["x"]

    # Linearly extrapolate a little fore/aft of the segment's own near/far
    # edges (along the same line) so the crossroad reads as a real street
    # rather than a hairline slice, while staying perfectly grounded to
    # the road plane at every y.
    span = y_near - y_far
    pad = span * 0.9

    def at_y(y):
        t = (y - y_far) / span  # 0 at far edge, 1 at near edge
        cx = lerp(cx_far, cx_near, t)
        hw = lerp(cross_w_far, cross_w_near, t)
        return cx, hw

    top = max(0, y_far - pad)
    bottom = min(SCREEN_H, y_near + pad)
    if bottom <= top:
        return

    cx_top, hw_top = at_y(top)
    cx_bot, hw_bot = at_y(bottom)
    poly(surface, (74, 74, 78), [
        (cx_bot - hw_bot, bottom), (cx_bot + hw_bot, bottom),
        (cx_top + hw_top, top), (cx_top - hw_top, top),
    ])

    # median strip with trees (spec: "Generate trees in middle of two lane
    # road"), drawn as its own thin trapezoid at the segment's own depth so
    # it stays grounded to the crossroad surface rather than floating at a
    # fixed screen height.
    med_half_span = span * 0.11
    med_top_y = clamp(y_near - med_half_span, top, bottom)
    med_bot_y = clamp(y_near + med_half_span, top, bottom)
    cx_mt, hw_mt = at_y(med_top_y)
    cx_mb, hw_mb = at_y(med_bot_y)
    poly(surface, (58, 120, 58), [
        (cx_mb - hw_mb, med_bot_y), (cx_mb + hw_mb, med_bot_y),
        (cx_mt + hw_mt, med_top_y), (cx_mt - hw_mt, med_top_y),
    ])

    if median_trees:
        cy_med = (med_top_y + med_bot_y) / 2
        cx_med, hw_med = at_y(cy_med)
        tree_w = max(3, p1["w"] * 0.16)
        tree_h = tree_w * (assets.tree.get_height() / assets.tree.get_width())
        spacing = max(30, tree_w * 2.6)
        tx = cx_med - hw_med + spacing * 0.5
        while tx < cx_med + hw_med:
            draw_billboard(surface, assets, ("median_tree", id(assets.tree)), assets.tree,
                            tx - tree_w / 2, cy_med + tree_h / 2, tree_w, tree_h)
            tx += spacing

    # crosswalk stripes painted across the main road (not the cross
    # street), anchored to this segment's own near-edge road width/x so
    # they sit on the same ground plane as the lane markings instead of
    # being a separate flat overlay.
    stripe_w = max(2, p1["w"] * 0.06)
    gap = stripe_w * 1.4
    xs = p1["x"] - p1["w"]
    xe = p1["x"] + p1["w"]
    x = xs
    stripe_h = max(2, span * 0.45)
    while x < xe:
        pygame.draw.rect(surface, (235, 235, 230), (x, y_near - stripe_h / 2, stripe_w, stripe_h))
        x += stripe_w + gap

    if has_light:
        # Anchored to the crossroad's own near-edge corner (not an
        # arbitrary screen offset), so the pole sits at the same ground
        # point as the crosswalk/median it's regulating.
        pole_x = cx_near + cross_w_near * 0.34
        draw_traffic_light(surface, pole_x, y_near, clamp(p1["w"] / 260.0, 0.15, 3.0), light_st)


# ---------------------------------------------------------------------------
# GAME
# ---------------------------------------------------------------------------
class Game:
    NUM_TRAFFIC_CARS = 9

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Boulevard Racer - Pseudo-3D City Drive")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.font_small = pygame.font.SysFont("arial", 16, bold=True)
        self.font_big = pygame.font.SysFont("arial", 48, bold=True)

        self.assets = Assets()
        self.segments = build_world_segments(seed=2026)

        self.player = PlayerCar()
        self.total_time = 0.0
        self.running = True
        self.paused_msg_timer = 3.0

        self.traffic = []
        rng = random.Random(7)
        for i in range(self.NUM_TRAFFIC_CARS):
            z = 1800 + i * rng.uniform(900, 1800)
            lane = rng.randrange(LANES)
            speed = TOP_SPEED * rng.uniform(0.32, 0.55)
            self.traffic.append(TrafficCar(z, lane, speed))

        # scale native player sprite once for a fixed on-screen HUD car size
        self._player_draw_w = 190
        self._player_draw_h = int(self._player_draw_w *
                                   (self.assets.player_car.get_height() / self.assets.player_car.get_width()))
        self._player_sprite_base = pygame.transform.smoothscale(
            self.assets.player_car, (self._player_draw_w, self._player_draw_h))

    # -- lookups -----------------------------------------------------
    def get_segment(self, idx):
        return self.segments[idx % TOTAL_SEGMENTS]

    def find_segment_index(self, z):
        return int(z // SEGMENT_LENGTH)

    # -- input ---------------------------------------------------------
    def handle_input(self):
        keys = pygame.key.get_pressed()
        steer = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            steer -= 1.0
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            steer += 1.0
        self.player.steer_input = steer
        self.player.throttle = bool(keys[pygame.K_UP] or keys[pygame.K_w])
        self.player.brake = bool(keys[pygame.K_DOWN] or keys[pygame.K_s] or keys[pygame.K_SPACE])

    # -- update ----------------------------------------------------------
    def update(self, dt):
        self.total_time += dt
        base_idx = self.find_segment_index(self.player.position)
        cur_seg = self.get_segment(base_idx)
        self.player.update(dt, cur_seg["curve"])

        for car in self.traffic:
            car.update(dt)
            # recycle cars that fall far behind the player, or that have
            # drifted too far ahead, back into a useful range - keeps a
            # constant amount of nearby traffic without unbounded growth
            if car.z < self.player.position - SEGMENT_LENGTH * 6:
                car.z = self.player.position + random.uniform(SEGMENT_LENGTH * 40, SEGMENT_LENGTH * 160)
                car.lane = random.randrange(LANES)
                car.x = lane_offset(car.lane)
                car.speed = TOP_SPEED * random.uniform(0.32, 0.55)
            elif car.z > self.player.position + SEGMENT_LENGTH * 220:
                car.z = self.player.position + random.uniform(SEGMENT_LENGTH * 20, SEGMENT_LENGTH * 60)
                car.lane = random.randrange(LANES)
                car.x = lane_offset(car.lane)
                car.speed = TOP_SPEED * random.uniform(0.32, 0.55)

        # collision check ("If two car hit then show animation of crashed")
        if not self.player.crashed:
            for car in self.traffic:
                dz = car.z - self.player.position
                if abs(dz) < SEGMENT_LENGTH * 0.85 and abs(car.x - self.player.x) < 0.62:
                    self.player.trigger_crash()
                    self.player.speed = min(self.player.speed, self.player.speed * 0.2)
                    break

    # -- rendering ---------------------------------------------------------
    def draw_sky(self):
        # Fill the whole canvas with the horizon color first so any
        # hairline rounding gaps between far-away road/grass trapezoids
        # show a seamless horizon tone instead of raw black.
        self.screen.fill(SKY_HORIZON)
        for i in range(0, SCREEN_H // 2, 4):
            t = i / (SCREEN_H / 2)
            col = (
                int(lerp(SKY_TOP[0], SKY_HORIZON[0], t)),
                int(lerp(SKY_TOP[1], SKY_HORIZON[1], t)),
                int(lerp(SKY_TOP[2], SKY_HORIZON[2], t)),
            )
            pygame.draw.rect(self.screen, col, (0, i, SCREEN_W, 4))
        pygame.draw.rect(self.screen, SKY_HORIZON, (0, SCREEN_H // 2 - 4, SCREEN_W, 4))

    def draw_world(self):
        self.draw_sky()

        player = self.player
        base_index = self.find_segment_index(player.position)
        base_percent = percent_remaining(player.position, SEGMENT_LENGTH)
        base_segment = self.get_segment(base_index)

        camera_x = player.x * ROAD_WIDTH
        maxy = SCREEN_H
        x = 0.0
        dx = -(base_segment["curve"] * base_percent)

        records = []
        for n in range(DRAW_DISTANCE):
            idx = base_index + n
            segment = self.get_segment(idx)

            p1 = make_point(z=idx * SEGMENT_LENGTH)
            p2 = make_point(z=(idx + 1) * SEGMENT_LENGTH)
            project(p1, camera_x - x, CAMERA_HEIGHT, player.position, SCREEN_W, SCREEN_H, ROAD_WIDTH)
            project(p2, camera_x - x - dx, CAMERA_HEIGHT, player.position, SCREEN_W, SCREEN_H, ROAD_WIDTH)

            x += dx
            dx += segment["curve"]

            if (p1["camera"]["z"] <= CAMERA_DEPTH or
                    p2["screen"]["y"] >= p1["screen"]["y"] or
                    p2["screen"]["y"] >= maxy):
                continue

            fog = clamp((n / DRAW_DISTANCE) ** 1.4, 0.0, 0.92)
            color = fog_blend_color(segment_color(idx), fog)
            draw_road_segment(self.screen,
                               p1["screen"]["x"], p1["screen"]["y"], p1["screen"]["w"],
                               p2["screen"]["x"], p2["screen"]["y"], p2["screen"]["w"],
                               color)

            records.append((idx, segment, p1["screen"], p2["screen"]))
            maxy = p1["screen"]["y"]

        # second pass: far -> near, so nearer things draw over farther ones
        for idx, segment, s1, s2 in reversed(records):
            if segment.get("is_intersection"):
                has_light = segment.get("has_light", False)
                if has_light:
                    state, _ = traffic_light_state(self.total_time, segment.get("light_phase", 0.0))
                else:
                    # neighboring intersection segments (center +/- 1) show
                    # the same crossroad surface without re-drawing their
                    # own light/pedestrians, so the crossing reads as one
                    # continuous grounded surface rather than a single
                    # one-segment-deep slice that pops in and out.
                    state = "green"
                draw_intersection_band(self.screen, s1, s2, has_light, state,
                                        segment.get("median_trees", False), self.assets, self.total_time)
                if has_light and state == "red":
                    self._draw_crossing_pedestrians(s1, segment)

            for sp in segment["sprites"]:
                self._draw_roadside_sprite(sp, s1)

            for car in self.traffic:
                car_idx = self.find_segment_index(car.z)
                if car_idx == idx:
                    self._draw_traffic_car(car, s1)

        # the player's own sprite sits at a fixed screen position (the
        # camera always trails it by the same amount), so it is drawn
        # once here rather than tied to a specific projected segment.
        self._draw_player(None)

    def _draw_roadside_sprite(self, sp, s1):
        if s1["scale"] <= 0.00001:
            return
        kind = sp["kind"]
        flip = sp["flip"]
        if kind == SPRITE_KIND_TREE:
            img = self.assets.tree_flipped if flip else self.assets.tree
            base_frac = 0.85
        else:
            img = self.assets.building_flipped if flip else self.assets.building
            base_frac = 1.55

        aspect = img.get_height() / img.get_width()
        draw_w = s1["w"] * base_frac * sp["scale"]
        draw_h = draw_w * aspect
        anchor_x = s1["x"] + sp["offset"] * s1["w"]
        dest_x = anchor_x - draw_w / 2
        draw_billboard(self.screen, self.assets, (kind, flip), img, dest_x, s1["y"], draw_w, draw_h)

    def _draw_traffic_car(self, car, s1):
        if s1["scale"] <= 0.00001:
            return
        img = self.assets.traffic_car
        aspect = img.get_height() / img.get_width()
        draw_w = s1["w"] * 0.62
        draw_h = draw_w * aspect
        anchor_x = s1["x"] + car.x * s1["w"]
        dest_x = anchor_x - draw_w / 2
        draw_billboard(self.screen, self.assets, ("traffic_car", 0), img, dest_x, s1["y"], draw_w, draw_h)

    def _draw_crossing_pedestrians(self, s1, segment):
        if s1["scale"] <= 0.00001:
            return
        band_h = clamp(s1["w"] * 0.62, 2, SCREEN_H)
        cy = s1["y"]
        seed_base = segment.get("light_phase", 0.0) * 97.0
        for k in range(3):
            phase = (self.total_time * 0.6 + k * 2.1 + seed_base) % 1.0
            side = -1 if k % 2 == 0 else 1
            px = s1["x"] + side * (s1["w"] * (1.0 - 2.0 * phase))
            py = cy + band_h * 0.05 + (k - 1) * band_h * 0.12
            scale = clamp(s1["w"] / 240.0, 0.1, 2.2)
            draw_pedestrian(self.screen, px, py, scale, self.total_time * 3 + k)

    def _draw_player(self, s1):
        p = self.player
        img = self._player_sprite_base
        w, h = self._player_draw_w, self._player_draw_h

        lean = clamp(p.steer_input * 6.0, -10, 10)
        if p.crashed:
            angle = math.degrees(p.crash_spin) % 360
        else:
            angle = lean

        rotated = pygame.transform.rotate(img, -angle) if abs(angle) > 0.4 else img
        rect = rotated.get_rect()
        cx = SCREEN_W / 2
        cy = SCREEN_H - 118
        rect.center = (cx, cy)
        self.screen.blit(rotated, rect)

        if p.scrape_flash > 0 or p.crashed:
            flash = pygame.Surface((SCREEN_W, SCREEN_H), flags=pygame.SRCALPHA)
            alpha = 120 if p.crashed else 90
            flash.fill((255, 60, 40, alpha))
            self.screen.blit(flash, (0, 0))

    # -- HUD ---------------------------------------------------------------
    def draw_hud(self):
        p = self.player
        speed_txt = self.font.render(f"{int(p.speed_kmh)} KM/H", True, (255, 255, 255))
        self.screen.blit(speed_txt, (20, 20))

        gear_txt = self.font_small.render(f"GEAR {p.gear}/6  AUTO", True, (230, 230, 230))
        self.screen.blit(gear_txt, (20, 52))

        limit_txt = self.font_small.render(f"CITY LIMIT {int(CITY_SPEED_LIMIT_KMH)} KM/H", True,
                                            (255, 210, 90) if p.speed_kmh > CITY_SPEED_LIMIT_KMH else (210, 230, 210))
        self.screen.blit(limit_txt, (20, 74))

        dist_km = p.position / (SEGMENT_LENGTH / 10.0) / 1000.0
        dist_txt = self.font_small.render(f"DISTANCE {dist_km:.2f} KM", True, (230, 230, 230))
        self.screen.blit(dist_txt, (SCREEN_W - 220, 20))

        crash_txt = self.font_small.render(f"CRASHES {p.crash_count}", True, (230, 230, 230))
        self.screen.blit(crash_txt, (SCREEN_W - 220, 42))

        if p.crashed:
            txt = self.font_big.render("CRASHED!", True, (255, 235, 235))
            rect = txt.get_rect(center=(SCREEN_W / 2, SCREEN_H / 2 - 60))
            self.screen.blit(txt, rect)

        if self.paused_msg_timer > 0:
            self.paused_msg_timer -= 1 / FPS
            hint = self.font_small.render("Arrows / WASD to drive - SPACE brake - ESC quit", True, (255, 255, 255))
            self.screen.blit(hint, (SCREEN_W / 2 - hint.get_width() / 2, SCREEN_H - 30))

    # -- main loop -----------------------------------------------------
    def run(self, max_frames=None):
        frame = 0
        while self.running:
            dt = min(0.05, self.clock.tick(FPS) / 1000.0)
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    self.running = False

            self.handle_input()
            self.update(dt)

            self.draw_world()
            self.draw_hud()
            pygame.display.flip()

            frame += 1
            if max_frames is not None and frame >= max_frames:
                self.running = False

        pygame.quit()


if __name__ == "__main__":
    Game().run()