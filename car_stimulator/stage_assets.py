"""
stage_assets.py — unpack only the Kenney GLB models Boulevard Racer needs,
into the folder layout car.py expects, with each kit's texture atlas
correctly co-located next to its own models.

Why not just unzip everything? Two reasons:
1. Each Kenney kit's colormap.png is DIFFERENT (car-kit's colormap is not
   the same file as city-kit-roads' or city-kit-suburban's). If you dump
   buildings and roads into one shared folder, one of them ends up with
   the wrong texture atlas silently.
2. Each kit has 30-100 models; you only need a handful. Staging just what
   you use keeps the repo from filling up with unused debris/kart/fence
   assets nobody asked for.

Run this from the folder containing the four kenney_*.zip files:
    python stage_assets.py
It creates a `models/` folder next to itself, ready to sit beside car.py.
"""

import os
import zipfile

# (source zip, [wanted model filenames], destination subfolder under models/)
KITS = [
    ("kenney_car-kit.zip",
     ["sedan-sports.glb", "taxi.glb"],
     "car-kit"),
    ("kenney_city-kit-roads.zip",
     ["road-straight.glb", "road-crossroad.glb"],
     "city-kit-roads"),
    ("kenney_city-kit-suburban_20.zip",
     ["building-type-e.glb", "building-type-f.glb", "building-type-g.glb",
      "building-type-h.glb", "building-type-i.glb"],
     "city-kit-suburban"),
]

# kenney_racing-kit.zip is intentionally NOT staged here — it's an
# isometric 2D sprite kit (PNG billboards shot from 4 fixed angles), a
# different art pipeline entirely from the GLB models above. Wire it in
# separately (e.g. for a minimap or a menu-screen mockup) rather than
# mixing it into the 3D model folders, or it'll just sit there unused.

DEST_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def stage_kit(zip_name, wanted_models, dest_subfolder):
    if not os.path.isfile(zip_name):
        print(f"[skip] {zip_name} not found in this folder")
        return

    dest = os.path.join(DEST_ROOT, dest_subfolder)
    os.makedirs(dest, exist_ok=True)
    os.makedirs(os.path.join(dest, "Textures"), exist_ok=True)

    with zipfile.ZipFile(zip_name) as z:
        missing = []
        for model in wanted_models:
            src = f"Models/GLB format/{model}"
            try:
                data = z.read(src)
            except KeyError:
                missing.append(model)
                continue
            with open(os.path.join(dest, model), "wb") as f:
                f.write(data)

        tex_src = "Models/GLB format/Textures/colormap.png"
        tex_data = z.read(tex_src)
        with open(os.path.join(dest, "Textures", "colormap.png"), "wb") as f:
            f.write(tex_data)

    staged = sorted(os.listdir(dest))
    print(f"[ok] {dest_subfolder}: {staged}")
    if missing:
        print(f"     !! not found in {zip_name}: {missing}")


if __name__ == "__main__":
    print(f"Staging into: {DEST_ROOT}\n")
    for zip_name, models, subfolder in KITS:
        stage_kit(zip_name, models, subfolder)
    print("\nDone. Now update car.py's model_file strings to match "
          "(see chat) — 'city-kit/...' needs to split into "
          "'city-kit-roads/...' and 'city-kit-suburban/...'.")
