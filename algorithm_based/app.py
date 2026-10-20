import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
GAMES_DIR = TEMPLATES_DIR / "games"
ALGORITHMS_JSON_PATH = BASE_DIR / "algorithms.json"

sys.path.insert(0, str(TEMPLATES_DIR))

from engine import (  # noqa: E402
    run_pipeline,
    PACMAN_ALGORITHMS,
    simulate_tetris_best_fit,
    dispatch_live,
    LIVE_EVALUATORS,
)

load_dotenv()

app = Flask(__name__)

# ==========================================================
# Gemini client for the chatbot's language understanding and
# for authoring new algorithms.json entries on the fly.
# Reuses the same GEMINI_API_KEY / SDK already used by
# generate_frontend.py, so no new credentials are required.
# ==========================================================
try:
    from google import genai
    _genai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
except Exception:  # pragma: no cover - SDK/key optional until chat-generate is used
    _genai_client = None

CHAT_MODEL = "gemini-3.6-flash"


# ==========================================================
# algorithms.json helpers
#
# PACMAN_ALGORITHMS (imported from engine) is assumed to be
# the same dict engine.py loaded from algorithms.json at
# import time. We mutate that dict in place (rather than
# rebinding it) so engine.run_pipeline() sees new entries
# immediately, and we also persist every change to disk so
# the catalog survives a server restart.
# ==========================================================

def save_algorithms_to_disk():
    with open(ALGORITHMS_JSON_PATH, "w") as f:
        json.dump({"algorithms": PACMAN_ALGORITHMS}, f, indent=2)


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "custom_game"


def unique_algo_key(base_slug):
    if base_slug not in PACMAN_ALGORITHMS:
        return base_slug
    i = 2
    while f"{base_slug}_{i}" in PACMAN_ALGORITHMS:
        i += 1
    return f"{base_slug}_{i}"


def available_templates():
    """One example entry per distinct template already on disk, used as
    few-shot schema examples so the model's `inputs` stay structurally
    valid for whichever template it picks."""
    seen = {}
    for algo in PACMAN_ALGORITHMS.values():
        tmpl = algo.get("template")
        if tmpl and tmpl not in seen and (GAMES_DIR / tmpl).exists():
            seen[tmpl] = algo
    return seen


def game_catalog_for_chat():
    games = []
    for key, algo in PACMAN_ALGORITHMS.items():
        games.append({
            "key": key,
            "name": algo.get("name", key),
            "family": algo.get("family", ""),
            "strategy": algo.get("strategy", ""),
            "play_url": f"/play/{key}",
            "live_play_available": algo.get("strategy") in LIVE_EVALUATORS,
        })
    return games


# ==========================================================
# Chat intent handling
# ==========================================================

GREETING_RE = re.compile(r"^\s*(hi|hey|hello|yo|sup|menu|help|start)\s*[!.]?\s*$", re.I)
LIST_GAMES_RE = re.compile(r"\b(all games|list games|show games|see games|what games|which games|games list)\b", re.I)
PLAY_RE = re.compile(r"^\s*(play|open|launch|start)\s+(.+)$", re.I)


def handle_chat_message(message, history):
    text = (message or "").strip()

    if not text or GREETING_RE.match(text):
        return {
            "type": "menu",
            "reply": (
                "Hey! I'm the Algorithm Arcade bot. Tell me a concept or algorithm "
                "you want to learn (e.g. \"Dijkstra's algorithm\" or \"Q-learning\") "
                "and I'll build you an interactive puzzle for it. Or ask to see all "
                "the games already available."
            ),
        }

    if LIST_GAMES_RE.search(text):
        games = game_catalog_for_chat()
        return {
            "type": "game_list",
            "reply": f"Here's everything in the arcade right now ({len(games)} puzzles):",
            "games": games,
        }

    play_match = PLAY_RE.match(text)
    if play_match:
        query = play_match.group(2).strip().lower()
        match = find_game_by_query(query)
        if match:
            return {
                "type": "play",
                "reply": f"Loading up \u201c{match['name']}\u201d \u2014 good luck!",
                "play_url": match["play_url"],
                "game": match,
            }
        return {
            "type": "text",
            "reply": (
                f"I don't have a puzzle called \u201c{play_match.group(2).strip()}\u201d yet. "
                "Want me to generate one? Just tell me the concept."
            ),
        }

    # Also allow "play <name>" to be caught even without the explicit verb,
    # if the free text matches an existing game closely.
    direct_match = find_game_by_query(text.lower())
    if direct_match and len(text) < 60:
        return {
            "type": "play",
            "reply": f"That's already in the arcade \u2014 launching \u201c{direct_match['name']}\u201d.",
            "play_url": direct_match["play_url"],
            "game": direct_match,
        }

    # Otherwise: treat the message as a concept to generate a new puzzle for.
    return generate_new_game(text)


def find_game_by_query(query):
    if not query:
        return None
    for key, algo in PACMAN_ALGORITHMS.items():
        name = algo.get("name", "").lower()
        if query == key.lower() or query in name or name in query:
            return {"key": key, "name": algo.get("name", key), "play_url": f"/play/{key}"}
    return None


# ==========================================================
# AI-assisted generation of a NEW algorithms.json entry
#
# Scope note: this picks the closest-matching EXISTING game
# template (crossy_road, pac_man, pong, robot_grid, tetris,
# dice_roll_simulator_amortized_rerender, ...) and asks the
# model to author a fresh `name` / `rules` / `inputs` for the
# requested concept, then runs it through the same
# engine.run_pipeline() the rest of the app already uses.
# It does not invent brand-new canvas templates from scratch
# (that needs new script_bridged.js + engine simulate_*
# support, which lives outside algorithms.json).
# ==========================================================

def generate_new_game(concept_text):
    if _genai_client is None:
        return {
            "type": "error",
            "reply": (
                "I can't reach the game generator right now \u2014 GEMINI_API_KEY isn't "
                "configured on the server. Add it to your .env file and restart the app."
            ),
        }

    templates = available_templates()
    if not templates:
        return {"type": "error", "reply": "No game templates are available to build from yet."}

    catalog_text = "\n\n".join(
        f'Template: "{tmpl}"\nExample entry: {json.dumps(example, indent=2)}'
        for tmpl, example in templates.items()
    )

    prompt = f"""You are choosing and configuring a new entry for an "algorithms.json" \
catalog that powers interactive teaching puzzles. Each entry picks one EXISTING \
template and supplies inputs matching that template's schema.

Available templates, each with a real example entry showing its exact "inputs" shape:

{catalog_text}

The learner wants a puzzle about: "{concept_text}"

Pick the template whose mechanic best teaches this concept (they don't have to match \
perfectly \u2014 pick the closest fit and adapt the "rules" text to explain the real \
concept through that template's mechanic). Then output ONLY a single JSON object \
(no markdown, no commentary) with exactly these keys:
  "name": short display name for this puzzle, referencing the real concept,
  "template": one of the template names above, exactly as written,
  "family": short category string,
  "strategy": short slug for the technique,
  "rules": 1-3 sentences explaining the concept as it applies in this puzzle,
  "inputs": an object matching the chosen template's example "inputs" shape exactly \
(same keys, same value types/shapes), with values adapted to make an interesting puzzle.
"""

    try:
        response = _genai_client.models.generate_content(model=CHAT_MODEL, contents=prompt)
        raw = (response.text or "").strip()
    except Exception as e:
        return {"type": "error", "reply": f"The game generator failed to respond: {e}"}

    cleaned = raw
    for fence in ("```json", "```javascript", "```"):
        if cleaned.startswith(fence):
            cleaned = cleaned[len(fence):]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -3]
    cleaned = cleaned.strip()

    try:
        entry = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "type": "error",
            "reply": "I generated something, but couldn't parse it into a valid puzzle. Mind rephrasing the concept?",
        }

    required_keys = {"name", "template", "family", "strategy", "rules", "inputs"}
    if not required_keys.issubset(entry.keys()):
        return {"type": "error", "reply": "The generated puzzle was missing required fields \u2014 try rephrasing."}

    if entry["template"] not in templates:
        return {
            "type": "error",
            "reply": f"I picked an unknown template (\u201c{entry['template']}\u201d) \u2014 try a different concept or phrasing.",
        }

    algo_key = unique_algo_key(slugify(entry["name"]))
    PACMAN_ALGORITHMS[algo_key] = entry

    try:
        run_pipeline(algo_key)
    except Exception as e:
        del PACMAN_ALGORITHMS[algo_key]
        return {
            "type": "error",
            "reply": f"I built a puzzle definition but the simulator couldn't run it ({e}). Try rephrasing the concept.",
        }

    save_algorithms_to_disk()

    return {
        "type": "generated",
        "reply": f"\U0001f3ae \u201c{entry['name']}\u201d is ready! It's also been added to All Games.",
        "play_url": f"/play/{algo_key}",
        "game": {
            "key": algo_key,
            "name": entry["name"],
            "family": entry.get("family", ""),
            "strategy": entry.get("strategy", ""),
            "play_url": f"/play/{algo_key}",
        },
    }


# ==========================================================
# Routes
# ==========================================================

@app.route("/")
def chatbot_home():
    return render_template("chatbot.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", algorithms=PACMAN_ALGORITHMS)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    history = data.get("history", [])
    result = handle_chat_message(message, history)
    return jsonify(result)


@app.route("/play/<algo_key>")
def play(algo_key):
    if algo_key not in PACMAN_ALGORITHMS:
        return f"Unknown algorithm: {algo_key}", 404

    algo_data = PACMAN_ALGORITHMS[algo_key]
    template_type = algo_data.get("template")

    # Target folder: templates/games/<template_type>/
    game_dir = GAMES_DIR / template_type
    if not game_dir.exists():
        return f"Game folder 'templates/games/{template_type}' not found.", 404

    # Live-arcade games (mode: "live_arcade" in algorithms.json) have no
    # trace file at all -- they're endless and generated client-side each
    # round via /api/evaluate/<algo_key>. Route straight to index.html with
    # the algorithm key so the arcade driver knows which live evaluator to
    # call. Everything else keeps the existing trace-based flow unchanged.
    if algo_data.get("mode") == "live_arcade":
        return redirect(f"/games/{template_type}/index.html?algo={algo_key}")

    # Determine trace path dynamically inside that game's directory
    trace_filename = f"{algo_key}_trace.json"
    trace_path = game_dir / trace_filename

    if not trace_path.exists():
        print(f"[*] Generating trace for '{algo_key}'...")
        run_pipeline(algo_key)

    return redirect(f"/games/{template_type}/index.html?trace={trace_filename}")


@app.route("/regenerate/<algo_key>")
def regenerate(algo_key):
    if algo_key not in PACMAN_ALGORITHMS:
        return f"Unknown algorithm: {algo_key}", 404
    run_pipeline(algo_key)
    return redirect(f"/play/{algo_key}")


@app.route("/games/<path:filepath>")
def serve_game_files(filepath):
    return send_from_directory(GAMES_DIR, filepath)


@app.route("/api/evaluate/<algo_key>", methods=["POST"])
def evaluate_live(algo_key):
    """
    Generic live-play endpoint for ANY algorithm that has a registered
    LIVE_EVALUATORS entry -- the generalized form of /api/evaluate_placement
    below (which is tetris-only and kept as-is for backward compatibility).

    Never touches algorithms.json or any _trace.json: like tetris's
    evaluator, the live state passed in each call IS the ground truth,
    recomputed fresh every request. This is what makes a game "actually
    playable" rather than a quiz against a frozen recording.

    Request body:
      {
        "live_state": {...},       # shape defined by that strategy's evaluator
        "proposed_action": ...     # optional -- omit to just ask "what's best?"
      }
    """
    if algo_key not in PACMAN_ALGORITHMS:
        return jsonify({"error": f"Unknown algorithm: {algo_key}"}), 404

    algo_data = PACMAN_ALGORITHMS[algo_key]
    strategy = algo_data.get("strategy")

    if strategy not in LIVE_EVALUATORS:
        return jsonify({
            "error": (
                f"'{algo_data.get('name', algo_key)}' doesn't have live play "
                f"yet -- only the guided tutorial trace. Add "
                f"generated_strategies/evaluate_{strategy}.py to enable it."
            ),
            "live_play_available": False,
        }), 501

    data = request.get_json(silent=True) or {}
    live_state = data.get("live_state")
    proposed_action = data.get("proposed_action")

    if live_state is None:
        return jsonify({"error": "live_state is required."}), 400

    try:
        result = dispatch_live(algo_key, algo_data, live_state, proposed_action)
    except Exception as e:
        return jsonify({"error": f"Live evaluation failed: {type(e).__name__}: {e}"}), 500

    return jsonify(result)


@app.route("/api/evaluate_placement", methods=["POST"])
def evaluate_placement():
    """
    Live evaluator, not a stored trace. Called fresh every time with the
    game's ACTUAL current board and the current piece's rotation variants.
    Returns every valid placement, ranked best-first (max rows cleared,
    then min fragmentation). This intentionally never touches
    algorithms.json or _trace.json -- the board changes every drop, so
    there is no fixed "correct" trace to cache; it has to be recomputed
    against the real board each time.
    """
    data = request.get_json(silent=True) or {}
    board = data.get("board")
    rotations = data.get("rotations")

    if not isinstance(board, list) or len(board) != 220:
        return jsonify({"error": "board must be a flat list of 220 cells (10x22)."}), 400
    if not isinstance(rotations, list) or not rotations:
        return jsonify({"error": "rotations must be a non-empty list of [dx,dy] variant arrays."}), 400

    try:
        candidates = simulate_tetris_best_fit({"board": board, "rotations": rotations})
    except Exception as e:
        return jsonify({"error": f"Evaluation failed: {type(e).__name__}: {e}"}), 500

    return jsonify({
        "best": candidates[0] if candidates else None,
        "all": candidates,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001)