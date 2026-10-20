# Boulevard Racer

Two deliverables, same game design:

## 1. boulevard_racer.html  — play now, in any browser
Pure HTML5 canvas + JavaScript. Just open the file (or the link Claude gave you)
in a browser, desktop or mobile. No install needed. Controls:
- Keyboard: Arrow keys / WASD to steer, throttle, brake
- Touch: on-screen pedal/steering buttons

## 2. boulevard_racer.py — Python edition (pygame + pymunk)
The "real" Python implementation with:
- A rigid-body physics engine (pymunk / Chipmunk2D) for the car
- A per-wheel (tire) friction/slip model layered on top (bicycle model:
  front & rear cornering stiffness, friction-circle grip limit -> realistic
  understeer/oversteer and drifting when you push too hard)
- Keyboard input handling (arrows / WASD)
- A track renderer that draws the same repeating "city block" pattern
  forever (crosswalk, traffic-light gantry, street sign, buildings, palm
  trees) so the world always looks consistent
- A small live minimap in the top-left corner

Run it locally:
    pip install -r requirements.txt
    python boulevard_racer.py

### Deploying the Python version to the web
Pygame doesn't run in a browser natively, but this file is written to run
unmodified under **pygbag**, which compiles pygame apps to WebAssembly:

    pip install pygbag
    pygbag boulevard_racer.py

This starts a local dev server (and produces a `build/web/` folder) that
runs the exact same rigid-body physics + track code in-browser. Host the
`build/web/` output anywhere static (GitHub Pages, Netlify, itch.io, etc.).

If you just want something playable in a browser right now with zero build
step, use `boulevard_racer.html` instead — it mirrors the same physics
model and track pattern in JavaScript.
