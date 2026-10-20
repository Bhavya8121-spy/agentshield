"""
Boulevard Racer - Minimal 3D Scene
"""
import math, os, re
from panda3d.core import load_prc_file_data

# 1. Force macOS Core Profile to enable modern rendering
load_prc_file_data('', 'gl-version 3 2')

from ursina import *
import simplepbr
from ursina.shader import Shader as _UrsinaShader

# 2. Patch Ursina's internal UI shaders (like the FPS counter) to GLSL 330 so they don't crash
_orig_compile = _UrsinaShader.compile
def _compile_fix(self, shader_includes=True):
    for attr in ('vertex', 'fragment', 'geometry'):
        src = getattr(self, attr, None)
        if src: setattr(self, attr, re.sub(r'#version\s+1[34]0\b', '#version 330', src))
    return _orig_compile(self, shader_includes=shader_includes)
_UrsinaShader.compile = _compile_fix

# Start Application
app = Ursina(development_mode=False)
window.size = (1280, 720)
window.color = color.rgb(150, 195, 235)

# 3. Use simplepbr for GLSL 330 3D lighting
simplepbr.init(use_330=True, msaa_samples=0, enable_shadows=False)

from boulevard_racer import PlayerCar, build_world_segments, SEGMENT_LENGTH, TOTAL_SEGMENTS
from track3d import build_centerline, sample_track, TrackView

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')

def model_path(f):
    p = os.path.join(MODEL_DIR, f)
    return os.path.join('models', f) if os.path.isfile(p) else None

def make_car():
    p = model_path('car-kit/sedan-sports.glb')
    if p: return Entity(model=p, rotation=(0,0,0))
    # Primitive fallback if GLB is missing
    c = Entity()
    Entity(parent=c, model='cube', color=color.red, scale=(1.0, 0.35, 2.2), position=(0, 0.35, 0))
    return c

player = PlayerCar()
segments = build_world_segments(seed=1)
pts, headings = build_centerline(segments)

track_view = TrackView(
    segments, pts, headings, model_path,
    road_models={'straight': 'city-kit-roads/road-straight.glb', 'intersection': 'city-kit-roads/road-crossroad.glb'},
    building_models=['city-kit-suburban/building-type-e.glb'],
    make_tree_fn=lambda: Entity(model='cube', scale=(1, 4, 1), color=color.green)
)

player_car = make_car()
ground = Entity(model='plane', scale=(400, 1, 400), color=color.rgb(90, 160, 90))

# 4. THE FIX: Aggressively strip incompatible shaders injected by the glTF models
# `scene` targets the 3D world only, so UI elements (FPS counter) safely keep their patched shaders.
for np in scene.findAllMatches('**'): 
    np.clearShader()

def update():
    # Input
    player.steer_input = (held_keys['d'] or held_keys['right arrow']) - (held_keys['a'] or held_keys['left arrow'])
    player.throttle = bool(held_keys['w'] or held_keys['up arrow'])
    player.brake = bool(held_keys['s'] or held_keys['down arrow'] or held_keys['space'])

    # Physics
    cur_seg = segments[int(player.position // SEGMENT_LENGTH) % TOTAL_SEGMENTS]
    player.update(time.dt, cur_seg["curve"])

    # Sync Visuals
    wx, wz, hdg = sample_track(pts, headings, player.position, player.x)
    player_car.position = (wx, 0, wz)
    player_car.rotation_y = math.degrees(hdg)

    camera.position = player_car.position - player_car.forward * 8 + Vec3(0, 4, 0)
    camera.look_at(player_car)
    
    track_view.update(player.position)

    # Brute-force strip GLSL 130 shaders from any new track chunks loaded this frame
    for np in scene.findAllMatches('**'): 
        np.clearShader()

app.run()