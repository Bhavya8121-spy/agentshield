"""
generate_game.py

Run this on any existing browser game (index.html + style.css + script.js)
and it produces a new, validated, playable concept-teaching mode wired into
the same engine.py / algorithms.json / templates/games/ system already used
by the Pac-Man, Tetris, and Pong games.

    python generate_game.py \
        --game-name breakout \
        --html path/to/index.html --css path/to/style.css --js path/to/script.js
        [--auto-merge]

PIPELINE (each stage's output is the grounding input for the next one --
nothing after stage 1 is allowed to invent facts stage 1 didn't produce):

  1. EXTRACT GAME FACTS   - AI reads the actual html/css/js and produces a
                             GAME_FACTS dict: dimensions, speeds, entities,
                             collision/scoring rules -- ONLY what's actually
                             in the code. This is the step a human (me) did
                             by hand for Pong; it's now automated.
  2. PROPOSE A CONCEPT     - AI proposes a CS concept that maps naturally
                             onto those exact facts (not a generic pitch --
                             it has to reference the real mechanics).
  3. GENERATE + VALIDATE   - AI writes a deterministic simulate_* function +
                             its own test cases + a ui_config (question
                             template, predict options, readout fields).
                             Runs in a sandboxed exec() against a strict
                             import whitelist, checked against the AI's own
                             test cases. Retries with the failure fed back
                             on any mismatch, up to --max-retries times.
  4. GENERATE THE BRIDGE   - AI writes script_bridged.js implementing a
                             FIXED contract (setupScene / showStepMarker /
                             revealStepMarker / clearStepMarker /
                             playResolutionAnimation) against the original
                             game's rendering code. The dashboard HTML is
                             NOT AI-generated -- it's a static, reusable
                             scaffold (templates/_dashboard_scaffold.html)
                             copied byte-for-byte, driven entirely by the
                             fixed trace schema + this bridge contract +
                             ui_config.json. This is deliberate: freeform
                             AI-generated UI is the least reliable thing to
                             validate, so it's scoped out of the AI's job.
  5. STAGE                 - writes generated_strategies/<key>.py (+ tests)
                             for human review, and the new game folder
                             (index.html, script_bridged.js, ui_config.json)
                             under templates/games/<key>/.
  6. WIRE IN                - always updates algorithms.json (adding an
                             entry is additive and safe). Only patches
                             engine.py (inserting the function + registering
                             it in STRATEGIES) if --auto-merge is passed --
                             this runs AI-generated code through exec(), so
                             the default stays a human-reviewed opt-in, same
                             as the rest of this pipeline. A .bak copy of
                             engine.py is written before any patch.
"""

import argparse
import ast
import json
import os
import re
import shutil
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError

BASE_DIR = Path(__file__).resolve().parent
SCAFFOLD_PATH = BASE_DIR / "templates" / "_dashboard_scaffold.html"
STAGING_DIR = BASE_DIR / "generated_strategies"
STAGING_DIR.mkdir(exist_ok=True)

load_dotenv()
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

MAX_RETRIES_DEFAULT = 5
ALLOWED_IMPORTS = {"math", "heapq", "collections", "itertools"}


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _call_with_retry(fn, *, max_attempts: int = 5, base_delay: float = 2.0):
    """
    Retries transient Gemini API failures (server overload, rate limiting)
    with exponential backoff. Does NOT retry ClientError (4xx other than
    429) -- those mean the request itself was malformed, and retrying an
    identical malformed request just wastes time before failing anyway.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except (ServerError, APIError) as e:
            code = getattr(e, "code", None)
            if code not in RETRYABLE_STATUS_CODES or attempt == max_attempts:
                raise
            last_exc = e
            delay = base_delay * (2 ** (attempt - 1))
            print(f"[Retry] Gemini API returned {code} (attempt {attempt}/{max_attempts}), likely transient overload. Retrying in {delay:.0f}s...")
            time.sleep(delay)
    raise last_exc


# ==========================================================
# Swappable model-calling functions.
# Kept as bare module-level functions (not inlined into callers) so a test
# harness can monkeypatch generate_game.call_gemini_json /
# generate_game.call_gemini_text without touching pipeline logic.
# ==========================================================
def call_gemini_json(prompt: str) -> dict | None:
    response = _call_with_retry(lambda: client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    ))
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        return None


def call_gemini_text(prompt: str) -> str:
    response = _call_with_retry(lambda: client.models.generate_content(model="gemini-3.6-flash", contents=prompt))
    return response.text


# ==========================================================
# STAGE 1: EXTRACT GAME FACTS
# ==========================================================
FACT_EXTRACTION_PROMPT = """
You are reverse-engineering an existing browser game's mechanics from its
actual source code. Extract ONLY facts that are explicitly present in the
code below -- dimensions, speeds, entity sizes, collision rules, scoring
rules, input mappings. Do NOT infer, guess, or invent any value that isn't
directly readable from the code. If something is randomized or configurable
rather than fixed, say so explicitly instead of picking a single number.

Output ONLY a JSON object of the form:
{
  "game": "short lowercase slug for this game, e.g. 'breakout'",
  "facts": {
    "<fact_name>": "<value or short description, straight from the code>"
  },
  "key_properties_useful_for_algorithms": [
    "Any mathematical property of the mechanics (monotonicity, periodicity,
     discreteness, etc.) that a search/optimization/graph algorithm could
     exploit -- ONLY if it's actually true of this code, not aspirational."
  ]
}

HTML:
{html}

CSS:
{css}

JAVASCRIPT:
{js}
"""


def extract_game_facts(game_name: str, html: str, css: str, js: str) -> dict | None:
    prompt = (
        FACT_EXTRACTION_PROMPT
        .replace("{html}", html)
        .replace("{css}", css)
        .replace("{js}", js)
    )
    facts = call_gemini_json(prompt)
    if not facts:
        print("[Failed] Could not parse game facts as JSON.")
        return None
    facts.setdefault("game", game_name)
    print(f"\n=== Extracted Game Facts: {facts['game']} ===")
    print(json.dumps(facts.get("facts", {}), indent=2))
    return facts


# ==========================================================
# STAGE 2: PROPOSE A CONCEPT
# ==========================================================
MAPPING_PROPOSAL_PROMPT = """
You are a Computer Science educator designing an educational game mechanic.
You are given the REAL, FIXED mechanics of an already-built game, extracted
directly from its source code -- you may NOT invent mechanics, dimensions,
or speeds that contradict them.

GAME FACTS (ground truth, not negotiable):
{game_facts}

Propose ONE Computer Science concept (a search algorithm, a data structure
operation, a numerical technique, a graph algorithm, etc.) that maps
naturally onto these exact mechanics -- not a generic pitch, but something
that genuinely follows from a real property of this game (a monotonic
quantity, a discrete state space, a resource-allocation decision, etc).

Output ONLY a JSON object:
{{
  "concept": "short name, e.g. 'Binary Search on a Monotonic Predicate'",
  "why_this_fits": "1-2 sentences on why this concept maps onto these exact
    mechanics, referencing a specific real property from GAME FACTS above.",
  "mapping": {{
    "what_an_entity_represents": "...",
    "what_the_algorithm_decides_each_step": "...",
    "what_a_learner_is_asked_to_predict_at_each_step": "..."
  }},
  "simulation_description": "A precise paragraph describing exactly what
    the simulate_* function should compute and return, written so it can be
    handed directly to an engineer as a spec. Must only reference values
    that exist in GAME FACTS above -- do not introduce values that don't
    exist in the real game."
}}

Do not include markdown fences or text outside the JSON object.
"""


def propose_concept(game_facts: dict) -> dict | None:
    prompt = MAPPING_PROPOSAL_PROMPT.replace("{game_facts}", json.dumps(game_facts, indent=2))
    proposal = call_gemini_json(prompt)
    if not proposal:
        print("[Failed] Mapping proposal was not valid JSON.")
        return None
    print(f"\n=== Proposed Concept: {proposal.get('concept')} ===")
    print(proposal.get("why_this_fits", ""))
    return proposal


# ==========================================================
# STAGE 3: GENERATE + VALIDATE THE STRATEGY FUNCTION
# ==========================================================
SYSTEM_SCHEMA_PROMPT = """
You are an expert Computer Science educator and Python engineer, writing a
DETERMINISTIC simulation function that computes the mathematically correct,
step-by-step trace of an algorithm applied to a small game state, PLUS a
small UI config describing how a "predict the next step" learner interface
should question the player about each step.

Output ONLY a valid JSON object matching this exact schema:

{
  "function_name": "simulate_<game>_<short_concept_slug>",
  "concept": "the concept name",
  "game": "the game slug",
  "code": "def simulate_<game>_<slug>(inputs):\\n    ...\\n    return steps",
  "imports_used": ["math"],
  "test_cases": [
    {
      "name": "descriptive_case_name",
      "inputs": { "...": "..." },
      "expected_output": { "...": "..." }
    }
  ],
  "notes": "One paragraph explaining the algorithmic logic in your own words.",
  "ui_config": {
    "predict_question_template": "A question string with {field_name}
      placeholders that reference keys inside each checkpoint step's
      'state' dict, e.g. 'At frame {mid}, has X reached {targetValue}?'",
    "predict_options": [
      {"label": "SHORT BUTTON LABEL", "value": true},
      {"label": "SHORT BUTTON LABEL", "value": false}
    ],
    "predict_field": "the key inside 'state' that holds the ground-truth
      value each predict_option's 'value' should be compared against",
    "readout_fields": [
      {"label": "SHORT LABEL", "field": "state_key_to_display"}
    ]
  }
}

Hard rules:
- "code" must define exactly one top-level function, named exactly
  "function_name", taking a single argument called "inputs" (a dict) and
  returning a LIST of step dicts.
- Every step dict must have a "type" key set to either "checkpoint" or
  "done" (the LAST element must be "done"). Checkpoint steps must include:
  "state" (a dict -- this is what ui_config's templates and predict_field
  read from), "explanationRight" (string), "explanationWrong" (string).
  "done" steps only need "state".
- ui_config.predict_field MUST be a key that is present in the "state" dict
  of every checkpoint step, and its value must be one of the values used in
  predict_options.
- Every placeholder in predict_question_template must be a key present in
  every checkpoint step's "state" dict.
- Only use imports from this allow-list: math, heapq, collections,
  itertools. No os, sys, requests, open(), eval(), exec(), or any I/O.
- Every test_case's "inputs" must be a valid input to your function, and
  "expected_output" must be the EXACT list your function returns for that
  input -- computed by hand-tracing the algorithm, not guessed. Provide at
  least 2 test_cases, including one small edge case.
- Do not include markdown code fences or any text outside the JSON object.
"""


class UnsafeCodeError(Exception):
    pass


def static_safety_check(code: str, function_name: str):
    tree = ast.parse(code)
    top_level_funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(top_level_funcs) != 1 or top_level_funcs[0].name != function_name:
        raise UnsafeCodeError(f"Expected exactly one top-level function named '{function_name}'.")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.name for n in node.names]
            module = node.module if isinstance(node, ast.ImportFrom) else None
            for n in names + ([module] if module else []):
                base = (n or "").split(".")[0]
                if base and base not in ALLOWED_IMPORTS:
                    raise UnsafeCodeError(f"Disallowed import: {base}")
        if isinstance(node, ast.Call):
            fn = node.func
            fn_name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if fn_name in {"eval", "exec", "open", "__import__", "compile", "input"}:
                raise UnsafeCodeError(f"Disallowed call: {fn_name}")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise UnsafeCodeError("global/nonlocal is not allowed.")


def run_in_sandbox(code: str, function_name: str, test_inputs: dict):
    import heapq as _heapq, collections as _collections, math as _math, itertools as _itertools
    module_map = {"heapq": _heapq, "collections": _collections, "math": _math, "itertools": _itertools}

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        base = name.split(".")[0]
        if base not in module_map:
            raise ImportError(f"Import of '{name}' is not allowed in the sandbox.")
        return module_map[base]

    safe_builtins = {
        "len": len, "range": range, "min": min, "max": max, "sum": sum, "abs": abs,
        "sorted": sorted, "enumerate": enumerate, "list": list, "dict": dict, "set": set,
        "tuple": tuple, "zip": zip, "map": map, "filter": filter, "any": any, "all": all,
        "int": int, "float": float, "str": str, "bool": bool, "isinstance": isinstance,
        "reversed": reversed, "round": round, "__import__": _guarded_import,
    }
    sandbox_globals = {"__builtins__": safe_builtins, **module_map}
    sandbox_locals = {}
    exec(code, sandbox_globals, sandbox_locals)  # nosec - guarded by static_safety_check + restricted builtins
    return sandbox_locals[function_name](test_inputs)


def validate_generated_function(spec: dict) -> tuple[bool, str]:
    function_name = spec.get("function_name", "")
    code = spec.get("code", "")
    test_cases = spec.get("test_cases", [])
    ui_config = spec.get("ui_config", {})

    if not function_name or not re.match(r"^simulate_[a-z0-9_]+$", function_name):
        return False, "function_name must match pattern 'simulate_<lowercase_name>'."
    if len(test_cases) < 2:
        return False, "At least 2 test_cases are required."

    predict_field = ui_config.get("predict_field")
    if not predict_field:
        return False, "ui_config.predict_field is required."
    if not ui_config.get("predict_question_template"):
        return False, "ui_config.predict_question_template is required."
    if not ui_config.get("predict_options"):
        return False, "ui_config.predict_options is required (at least 2 options)."

    try:
        static_safety_check(code, function_name)
    except (UnsafeCodeError, SyntaxError) as e:
        return False, f"Static safety check failed: {e}"

    placeholders = set(re.findall(r"\{(\w+)\}", ui_config["predict_question_template"]))

    for tc in test_cases:
        name = tc.get("name", "unnamed")
        try:
            actual = run_in_sandbox(code, function_name, tc["inputs"])
        except Exception as e:
            return False, f"Test '{name}' raised an exception: {type(e).__name__}: {e}"

        if actual != tc["expected_output"]:
            return False, (
                f"Test '{name}' failed.\n"
                f"  Expected: {json.dumps(tc['expected_output'])}\n"
                f"  Actual:   {json.dumps(actual)}"
            )
        if not isinstance(actual, list) or not all(isinstance(s, dict) for s in actual):
            return False, f"Test '{name}': output must be a list of step dicts."

        for i, step in enumerate(actual):
            if step.get("type") not in ("checkpoint", "done"):
                return False, f"Test '{name}' step {i}: missing/invalid 'type' (must be checkpoint or done)."
            if step["type"] == "checkpoint":
                if "state" not in step or "explanationRight" not in step or "explanationWrong" not in step:
                    return False, f"Test '{name}' step {i}: checkpoint missing state/explanationRight/explanationWrong."
                if predict_field not in step["state"]:
                    return False, (
                        f"Test '{name}' step {i}: ui_config.predict_field "
                        f"'{predict_field}' is not present in this checkpoint's state."
                    )
                missing_ph = placeholders - set(step["state"].keys())
                if missing_ph:
                    return False, (
                        f"Test '{name}' step {i}: predict_question_template references "
                        f"{missing_ph}, not present in this checkpoint's state."
                    )
        if actual[-1]["type"] != "done":
            return False, f"Test '{name}': last step must have type 'done'."

    option_values = {opt["value"] for opt in ui_config["predict_options"]}
    if len(ui_config["predict_options"]) < 2:
        return False, "ui_config.predict_options needs at least 2 options."

    return True, "All tests passed."


def generate_validated_strategy(game_facts: dict, concept: str, description: str, max_retries: int) -> dict | None:
    game = game_facts.get("game", "game")
    base_prompt = f"""{SYSTEM_SCHEMA_PROMPT}

GAME: {game}
CONCEPT TO TEACH: {concept}
DESCRIPTION OF WHAT THIS SIMULATION SHOULD DO:
{description}

GAME FACTS (ground truth -- do not contradict):
{json.dumps(game_facts, indent=2)}
"""
    current_prompt = base_prompt

    for attempt in range(1, max_retries + 1):
        print(f"\n--- Agent Attempt {attempt}/{max_retries} ---")
        spec = call_gemini_json(current_prompt)

        if not spec:
            print("Failed to parse JSON. Retrying...")
            current_prompt = f"{base_prompt}\n\nYour last output was invalid JSON. Return ONLY the JSON object."
            continue

        is_valid, feedback = validate_generated_function(spec)
        print(feedback)

        if is_valid:
            print(f"[Success] '{spec['function_name']}' passed all tests.")
            return spec

        current_prompt = (
            f"{base_prompt}\n\nYour previous attempt failed validation with this error:\n{feedback}\n\n"
            f"Fix the code, test cases, and/or ui_config. Remember: expected_output must be "
            f"what your OWN code actually produces -- recompute it by hand-tracing the algorithm."
        )

    print("[Failed] Could not produce a validated function after max retries.")
    return None


# ==========================================================
# STAGE 4: GENERATE THE FRONTEND BRIDGE
# ==========================================================
BRIDGE_CONTRACT_PROMPT = """
You are modifying an existing browser game's JavaScript so a generic,
game-agnostic dashboard (which you do not control or need to modify) can
drive it through a FIXED bridge contract. Output ONLY the modified
JavaScript. Do not include markdown formatting or any explanations.

You are given: the ORIGINAL JAVASCRIPT for the game's rendering/physics,
and the VALIDATED PYTHON SIMULATION whose step trace this bridge will
visualize (ported to equivalent JS logic if useful, but the dashboard
itself never runs Python -- your JS just needs to draw whatever each step's
'state' object represents).

Implement exactly these five global functions (the dashboard calls these
and only these -- do not rename them):

1. window.setupScene(introStep)
   Called once at load. `introStep` is the trace's first element -- an
   object with algorithm-specific fields (whatever the simulation's
   "inputs" were). Draw the initial static scene using a canvas element
   with id="scene-canvas" (already present in the page).

2. window.showStepMarker(state)
   Called once per checkpoint, BEFORE the learner answers. `state` is that
   checkpoint's state dict. Draw whatever visual marks the candidate the
   learner is being asked to predict about (e.g. a ghost marker, a
   highlighted cell). CRITICAL: do not color-code or otherwise visually
   reveal the correct answer here -- that would let the learner see the
   answer before predicting. Use a single neutral color/style regardless of
   whether the underlying prediction is true or false.

3. window.revealStepMarker(state)
   Called immediately AFTER the learner answers, with the same state. NOW
   you may recolor/update the marker to show the algorithm's actual answer
   (e.g. green if correct-per-algorithm, red if not).

4. window.clearStepMarker()
   Clears any marker drawn by showStepMarker/revealStepMarker.

5. window.playResolutionAnimation(doneState, onComplete)
   Called once, after the last checkpoint. `doneState` is the final step's
   state dict. Animate the real game entities resolving to their final
   configuration (matching the original game's actual physics/rendering
   logic, not invented motion), then call onComplete() when finished.

None of this should change the game's default behavior if these functions
are simply never called by anything else.

ORIGINAL JAVASCRIPT:
{original_js}

ORIGINAL CSS (for visual reference only):
{original_css}

VALIDATED SIMULATION (Python -- defines the exact shape of `state` in every
checkpoint/done step; your JS drawing code must match these field names):
{simulation_code}
"""


def generate_bridge_script(original_js: str, original_css: str, spec: dict) -> str | None:
    prompt = (
        BRIDGE_CONTRACT_PROMPT
        .replace("{original_js}", original_js)
        .replace("{original_css}", original_css)
        .replace("{simulation_code}", spec["code"])
    )
    raw = call_gemini_text(prompt)

    clean = raw.strip()
    for fence in ("```javascript", "```js", "```"):
        if clean.startswith(fence):
            clean = clean[len(fence):]
    if clean.endswith("```"):
        clean = clean.rsplit("```", 1)[0]
    clean = clean.strip()

    required = [
        "window.setupScene", "window.showStepMarker", "window.revealStepMarker",
        "window.clearStepMarker", "window.playResolutionAnimation",
    ]
    missing = [m for m in required if m not in clean]
    if missing:
        print(f"[Warning] Generated bridge script is missing required symbols: {missing}")
        return None
    return clean


# ==========================================================
# STAGE 5: STAGE FILES
# ==========================================================
def stage_strategy(spec: dict) -> Path:
    out_path = STAGING_DIR / f"{spec['function_name']}.py"
    header = (
        f"# STAGED, NOT YET WIRED into engine.py's STRATEGIES (unless --auto-merge was used)\n"
        f"# Game: {spec.get('game')}\n# Concept: {spec.get('concept')}\n"
        f"# Notes: {spec.get('notes', '')}\n\n"
    )
    out_path.write_text(header + spec["code"] + "\n")
    (STAGING_DIR / f"{spec['function_name']}.tests.json").write_text(json.dumps(spec["test_cases"], indent=2))
    print(f"[*] Staged code:  {out_path}")
    return out_path


def write_game_folder(games_dir: Path, key: str, bridge_js: str, ui_config: dict) -> Path:
    game_dir = games_dir / key
    game_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(SCAFFOLD_PATH, game_dir / "index.html")
    (game_dir / "script_bridged.js").write_text(bridge_js)
    (game_dir / "ui_config.json").write_text(json.dumps(ui_config, indent=2))
    print(f"[*] Wrote game folder: {game_dir}")
    return game_dir


# ==========================================================
# STAGE 6: WIRE IN
# ==========================================================
def strategy_key_from_function_name(function_name: str, game: str) -> str:
    """
    Strips only the 'simulate_' prefix, deliberately KEEPING the game name
    in the key (e.g. 'simulate_breakout_binary_search_interception' ->
    'breakout_binary_search_interception'). This guarantees uniqueness in
    engine.py's single global STRATEGIES dict even when two different games
    land on the same concept name -- which is plausible (binary search,
    BFS, and best-fit are all likely to recur across games) and would
    otherwise silently overwrite/skip a registration.
    """
    return function_name.removeprefix("simulate_")


def inject_into_algorithms_json(algorithms_path: Path, key: str, spec: dict, sample_inputs: dict):
    data = json.loads(algorithms_path.read_text()) if algorithms_path.exists() else {"algorithms": {}}
    data.setdefault("algorithms", {})

    strategy_key = strategy_key_from_function_name(spec["function_name"], spec["game"])
    data["algorithms"][key] = {
        "name": f"{spec['game'].title()} \u2014 {spec['concept']}",
        "template": key,
        "family": f"{spec['game']}_generated",
        "strategy": strategy_key,
        "rules": spec.get("notes", ""),
        "inputs": sample_inputs,
    }
    algorithms_path.write_text(json.dumps(data, indent=2))
    print(f"[*] Injected '{key}' into {algorithms_path}")
    return key


def auto_merge_engine(engine_path: Path, spec: dict):
    backup_path = engine_path.with_suffix(".py.bak")
    shutil.copy(engine_path, backup_path)
    print(f"[*] Backed up {engine_path} -> {backup_path}")

    src = engine_path.read_text()

    marker = "def build_intro_step(algo_data):"
    if marker not in src:
        raise RuntimeError(f"Could not find insertion marker '{marker}' in {engine_path}.")
    if spec["function_name"] not in src:
        src = src.replace(marker, spec["code"].strip() + "\n\n\n" + marker, 1)
    else:
        print(f"[*] '{spec['function_name']}' already present in engine.py -- skipping function insertion.")

    # Ensure the generic fallback exists in build_intro_step so future
    # generated games never need a hand-written elif branch here.
    if "intro_step.update(inputs)" not in src:
        src = re.sub(
            r"(\n\s*)return intro_step\n",
            r"\1else:\1    intro_step.update(inputs)\n\1return intro_step\n",
            src, count=1,
        )
        print("[*] Added generic fallback to build_intro_step().")

    strategy_key = strategy_key_from_function_name(spec["function_name"], spec["game"])
    strategies_marker = "STRATEGIES = {"
    if strategies_marker not in src:
        raise RuntimeError(f"Could not find '{strategies_marker}' in {engine_path}.")
    if f'"{strategy_key}"' not in src.split(strategies_marker, 1)[1].split("}", 1)[0]:
        src = src.replace(
            strategies_marker,
            f'{strategies_marker}\n    "{strategy_key}": {spec["function_name"]},',
            1,
        )
        print(f"[*] Registered strategy '{strategy_key}' in STRATEGIES.")

    engine_path.write_text(src)
    print(f"[*] engine.py updated in place.")


# ==========================================================
# CLI / MAIN
# ==========================================================
def discover_game_files(game_dir: Path) -> tuple[Path, Path, Path]:
    """
    Locates the raw html/css/js in an existing game folder. Tries common
    exact filenames first (matching what's actually in this project's
    templates/games/<name>/ folders today), falls back to a glob by
    extension, and explicitly excludes anything this pipeline itself
    would have produced (script_bridged.js, ui_config.json, an
    already-generated index.html from a prior run) so re-pointing at an
    already-AI-ified folder doesn't feed its own output back in as if it
    were the original source.
    """
    def find(exact_names, glob_pattern, exclude_names):
        for name in exact_names:
            candidate = game_dir / name
            if candidate.exists():
                return candidate
        matches = [
            p for p in game_dir.glob(glob_pattern)
            if p.name not in exclude_names
        ]
        if not matches:
            raise FileNotFoundError(
                f"Could not find a {glob_pattern} file in {game_dir} "
                f"(looked for {exact_names}, then any {glob_pattern})."
            )
        if len(matches) > 1:
            print(f"[Warning] Multiple {glob_pattern} files in {game_dir}, using {matches[0].name}: {[m.name for m in matches]}")
        return matches[0]

    html = find(["index.html"], "*.html", exclude_names=set())
    css = find(["style.css", "styles.css"], "*.css", exclude_names=set())
    js = find(["script.js", "game.js"], "*.js", exclude_names={"script_bridged.js"})
    return html, css, js


def main():
    parser = argparse.ArgumentParser(description="Generate a new concept-teaching game from raw html/css/js.")
    parser.add_argument("--game-dir", type=Path,
                         help="Folder containing the raw game's html/css/js (auto-detects common filenames: "
                              "index.html, style.css/styles.css, script.js/game.js). Alternative to "
                              "--html/--css/--js. If --game-name is omitted, it's inferred from this folder's name.")
    parser.add_argument("--game-name", help="Short slug for the source game, e.g. 'breakout'. "
                                             "Inferred from --game-dir's folder name if omitted.")
    parser.add_argument("--html", type=Path)
    parser.add_argument("--css", type=Path)
    parser.add_argument("--js", type=Path)
    parser.add_argument("--games-dir", type=Path, default=BASE_DIR / "templates" / "games")
    parser.add_argument("--engine-path", type=Path, default=BASE_DIR / "templates" / "engine.py")
    parser.add_argument("--algorithms-path", type=Path, default=BASE_DIR / "algorithms.json")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES_DEFAULT)
    parser.add_argument("--auto-merge", action="store_true",
                         help="Also patch engine.py (insert function + register STRATEGIES entry). "
                              "Off by default -- generated code is staged for review instead.")
    args = parser.parse_args()

    if args.game_dir:
        html_path, css_path, js_path = discover_game_files(args.game_dir)
        game_name = args.game_name or args.game_dir.name
        print(f"[*] Discovered in {args.game_dir}: {html_path.name}, {css_path.name}, {js_path.name}")
        print(f"[*] Using game-name: '{game_name}'")
    elif args.html and args.css and args.js and args.game_name:
        html_path, css_path, js_path = args.html, args.css, args.js
        game_name = args.game_name
    else:
        parser.error("Either --game-dir, or all three of --html/--css/--js plus --game-name, are required.")

    html = html_path.read_text()
    css = css_path.read_text()
    js = js_path.read_text()

    game_facts = extract_game_facts(game_name, html, css, js)
    if not game_facts:
        return

    proposal = propose_concept(game_facts)
    if not proposal:
        return

    spec = generate_validated_strategy(
        game_facts, proposal["concept"], proposal["simulation_description"], args.max_retries
    )
    if not spec:
        return
    spec.setdefault("game", game_facts["game"])

    bridge_js = generate_bridge_script(js, css, spec)
    if not bridge_js:
        print("[Failed] Bridge script generation did not satisfy the required contract. Stopping before staging.")
        return

    stage_strategy(spec)

    key = strategy_key_from_function_name(spec["function_name"], spec["game"])
    output_game_dir = args.games_dir / key
    if args.game_dir and output_game_dir.resolve() == args.game_dir.resolve():
        print(
            f"[Failed] Generated output folder '{output_game_dir}' is the same as the input "
            f"--game-dir. Refusing to overwrite your raw source. Rename the input folder, or "
            f"pass --games-dir pointing somewhere else, and re-run."
        )
        return
    write_game_folder(args.games_dir, key, bridge_js, spec["ui_config"])

    sample_inputs = spec["test_cases"][0]["inputs"]
    inject_into_algorithms_json(args.algorithms_path, key, spec, sample_inputs)

    if args.auto_merge:
        auto_merge_engine(args.engine_path, spec)
        print(f"\n[Done] '{key}' is fully wired in. Visit /play/{key}")
    else:
        print(
            f"\n[Done] '{key}' is staged. To finish wiring it in:\n"
            f"  1. Review {STAGING_DIR / (spec['function_name'] + '.py')}\n"
            f"  2. Paste the function into {args.engine_path}, add it to STRATEGIES as '{key}'\n"
            f"  (or re-run with --auto-merge to do this automatically)."
        )


if __name__ == "__main__":
    main()
