# engine.py
import sys
import json
import heapq
import inspect
import importlib.util
import requests
from pathlib import Path
from collections import deque

# Pacman and robot-grid games are not stable yet, so their STRATEGIES entries
# are staged (unwired) by default. Pass --auto-merge on the command line to
# wire them back in anyway.
AUTO_MERGE = "--auto-merge" in sys.argv

# run_all() skips any algorithm whose trace file already exists on disk --
# regenerating means an Ollama call (pass_2_generate_explanations) per
# algorithm, and re-running the full batch just to add one new algorithm
# was silently re-billing that cost for every existing one too. Pass
# --force to regenerate everything anyway (e.g. after editing a strategy's
# logic and needing every affected trace rebuilt).
FORCE = "--force" in sys.argv

BASE_DIR = Path(__file__).resolve().parent
ALGORITHMS_FILE = BASE_DIR.parent / "algorithms.json" # Adjust path if needed

# Restored missing Ollama variables
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:latest"

# Dynamically load all generated algorithms
try:
    with open(ALGORITHMS_FILE, "r") as f:
        data = json.load(f)
        PACMAN_ALGORITHMS = data.get("algorithms", {})
except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Warning: Failed to load algorithms.json ({e}). Defaulting to empty.")
    PACMAN_ALGORITHMS = {}

# ===========================================================================
# 2. PASS 1: DETERMINISTIC SIMULATOR FOR PAC-MAN
# ===========================================================================

def simulate_pacman_a_star_lesson_a_star(inputs):
    grid = inputs["grid"]
    start = inputs["start"]
    goal = inputs["goal"]
    
    rows = len(grid)
    cols = len(grid[0])
    start_r, start_c = start[0], start[1]
    goal_r, goal_c = goal[0], goal[1]
    
    def manhattan(r, c):
        return abs(r - goal_r) + abs(c - goal_c)
        
    counter = 0
    start_h = manhattan(start_r, start_c)
    open_set = [(start_h, start_h, counter, start_r, start_c)]
    
    g_score = {(start_r, start_c): 0}
    came_from = {}
    visited_trace = set()
    closed_set = set()
    
    steps = []
    step_num = 1
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    
    while open_set:
        f, h, _, r, c = heapq.heappop(open_set)
        
        if (r, c) in closed_set:
            continue
        closed_set.add((r, c))
        visited_trace.add((r, c))
        
        g = g_score[(r, c)]
        is_goal = (r == goal_r and c == goal_c)
        
        steps.append({
            "type": "checkpoint",
            "state": {
                "step_num": step_num,
                "current_r": r,
                "current_c": c,
                "g_val": g,
                "h_val": h,
                "f_val": f,
                "is_goal": is_goal
            },
            "explanationRight": f"Correct! At ({r}, {c}), g={g} and h={h}. " + ("Goal cell reached!" if is_goal else "Searching continues as goal is not yet reached."),
            "explanationWrong": f"Incorrect. Check if cell ({r}, {c}) matches the target goal ({goal_r}, {goal_c})."
        })
        
        if is_goal:
            break
            
        step_num += 1
        
        for dr, dc in directions:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                cell_val = grid[nr][nc]
                if str(cell_val) != "1":
                    tentative_g = g + 1
                    if tentative_g < g_score.get((nr, nc), float('inf')):
                        came_from[(nr, nc)] = (r, c)
                        g_score[(nr, nc)] = tentative_g
                        h_next = manhattan(nr, nc)
                        f_next = tentative_g + h_next
                        counter += 1
                        heapq.heappush(open_set, (f_next, h_next, counter, nr, nc))
                        
    curr = (goal_r, goal_c)
    path = []
    if curr in g_score:
        while curr in came_from:
            path.append([curr[0], curr[1]])
            curr = came_from[curr]
        path.append([start_r, start_c])
        path.reverse()
        
    path_cost = len(path) - 1 if path else 0
    animation_time_ms = path_cost * 260
    
    if visited_trace:
        min_r = max(0, min(r for r, c in visited_trace) - 1)
        max_r = min(rows - 1, max(r for r, c in visited_trace) + 1)
        min_c = max(0, min(c for r, c in visited_trace) - 1)
        max_c = min(cols - 1, max(c for r, c in visited_trace) + 1)
        crop_bbox = [min_r, min_c, max_r, max_c]
    else:
        crop_bbox = [0, 0, rows - 1, cols - 1]
        
    steps.append({
        "type": "done",
        "state": {
            "step_num": step_num,
            "current_r": goal_r,
            "current_c": goal_c,
            "g_val": path_cost,
            "h_val": 0,
            "f_val": path_cost,
            "is_goal": True,
            "path": path,
            "path_cost": path_cost,
            "animation_time_ms": animation_time_ms,
            "crop_bbox": crop_bbox
        }
    })
    
    return steps

def simulate_tetris_best_fit(inputs):
    memory = list(inputs["memory_blocks"])
    pieces = inputs["pieces"]
    steps = []

    for idx, piece in enumerate(pieces):
        p_name = piece["name"]
        p_size = piece["size"]
        mem_before = list(memory)

        best_block_idx = -1
        min_leftover = float("inf")

        for b_idx, b_size in enumerate(memory):
            if b_size >= p_size:
                leftover = b_size - p_size
                if leftover < min_leftover:
                    min_leftover = leftover
                    best_block_idx = b_idx

        if best_block_idx != -1:
            memory[best_block_idx] -= p_size
            status = "allocated"
            explanation = f"Piece '{p_name}' (size {p_size}) fits best in Block {best_block_idx} (size {mem_before[best_block_idx]}), leaving {min_leftover} units remaining."
        else:
            status = "failed"
            explanation = f"Piece '{p_name}' (size {p_size}) could not fit in any available block."

        steps.append({
            "step": idx + 1,
            "piece": p_name,
            "size": p_size,
            "status": status,
            "allocated_block_index": best_block_idx if best_block_idx != -1 else None,
            "memory_before": mem_before,
            "memory_after": list(memory),
            "explanation": explanation
        })

    return steps


def simulate_pong_binary_search_interception(inputs):
    """
    Predicts the frame + y-coordinate at which the ball crosses a paddle's
    x-line, using binary search on the monotonic predicate
    "has ballX(frame) reached-or-passed paddle_x". Valid while ballSpeedX
    hasn't changed sign (i.e. between paddle hits), which is exactly when
    ballX(frame) = ballX0 + ballSpeedX * frame is strictly monotonic in
    frame -- the precondition binary search needs. Emits one checkpoint per
    search iteration (schema-compliant, like simulate_pacman_a_star) so it
    passes through to_checkpoint_trace() unchanged.
    """
    ball = inputs["ball"]
    board = inputs["board"]
    paddle_x = inputs["paddle_x"]
    max_steps = inputs.get("max_steps", 64)

    bx, by = ball["x"], ball["y"]
    vx, vy = ball["vx"], ball["vy"]
    height = board["height"]

    def x_at(n):
        return bx + vx * n

    def y_at(n):
        # "Unfold the board" reflection trick: recovers the bounced y
        # without branching on every wall hit.
        unwrapped = by + vy * n
        period = 2 * height
        m = unwrapped % period
        return m if m <= height else period - m

    steps = []
    common = {"ball": ball, "board": board, "paddleX": paddle_x}

    if vx == 0:
        steps.append({
            "type": "checkpoint",
            "state": {**common, "lo": 0, "hi": 0, "mid": 0, "xAtMid": bx, "yAtMid": by, "predicateTrue": False},
            "targetCell": None,
            "taskProcessed": "Step 1",
            "explanationRight": "The ball's horizontal velocity is zero, so its x-position never changes -- it can never cross the paddle's x-line, so there is nothing for binary search to converge on.",
            "explanationWrong": "With zero horizontal velocity the ball's x never changes, so it cannot be 'already past' the paddle line at any frame.",
        })
        steps.append({"type": "done", "state": {**common, "intercepted": False}})
        return steps

    predicate = (lambda n: x_at(n) >= paddle_x) if vx > 0 else (lambda n: x_at(n) <= paddle_x)

    lo, hi = 0, max_steps
    if not predicate(hi):
        steps.append({
            "type": "checkpoint",
            "state": {**common, "lo": lo, "hi": hi, "mid": hi, "xAtMid": x_at(hi), "yAtMid": y_at(hi), "predicateTrue": False},
            "targetCell": None,
            "taskProcessed": "Step 1",
            "explanationRight": f"Even at the search horizon of {max_steps} frames, the ball's predicted x has not reached x={paddle_x}, so no interception exists within this window.",
            "explanationWrong": f"At the horizon frame {hi}, the ball's x is {x_at(hi):.1f}, which has not reached x={paddle_x} -- the predicate is false here, not true.",
        })
        steps.append({"type": "done", "state": {**common, "intercepted": False}})
        return steps

    step_num = 1
    while lo < hi:
        mid = (lo + hi) // 2
        x_mid = x_at(mid)
        y_mid = y_at(mid)
        result = predicate(mid)

        if result:
            hi = mid
            right = (f"At frame {mid}, predicted ball x is {x_mid:.1f}, already at or past paddle line "
                      f"x={paddle_x}. Search shrinks the upper bound to {mid} -- the earliest interception "
                      f"frame must be at or before this point.")
            wrong = (f"At frame {mid}, predicted ball x is {x_mid:.1f}, which has ALREADY reached paddle line "
                      f"x={paddle_x} -- the predicate is true here.")
        else:
            lo = mid + 1
            right = (f"At frame {mid}, predicted ball x is {x_mid:.1f}, still short of paddle line "
                      f"x={paddle_x}. Search raises the lower bound to {mid + 1} -- the interception frame "
                      f"must come after this point.")
            wrong = (f"At frame {mid}, predicted ball x is {x_mid:.1f}, which has NOT YET reached paddle line "
                      f"x={paddle_x} -- the predicate is false here.")

        steps.append({
            "type": "checkpoint",
            "state": {**common, "lo": lo, "hi": hi, "mid": mid, "xAtMid": x_mid, "yAtMid": y_mid, "predicateTrue": result},
            "targetCell": None,
            "taskProcessed": f"Step {step_num}",
            "explanationRight": right,
            "explanationWrong": wrong,
        })
        step_num += 1

    intercept_frame = lo
    predicted_y = y_at(intercept_frame)

    steps.append({
        "type": "done",
        "state": {
            **common,
            "intercepted": True,
            "intercept_frame": intercept_frame,
            "predicted_y": predicted_y,
        },
    })
    return steps


def simulate_breakout_binary_search_interception(inputs):
    ball = inputs["ball"]
    board = inputs["board"]
    target_x = inputs["target_x"]
    max_steps = inputs.get("max_steps", 32)

    bx = ball["x"]
    vx = ball["vx"]

    def x_at(n):
        return bx + vx * n

    steps = []
    if vx == 0:
        steps.append({
            "type": "checkpoint",
            "state": {"lo": 0, "hi": 0, "mid": 0, "xAtMid": bx, "targetX": target_x, "crossed": False},
            "explanationRight": "Zero velocity means the ball never crosses the target.",
            "explanationWrong": "Zero velocity means the ball never crosses the target.",
        })
        steps.append({"type": "done", "state": {"crossed": False}})
        return steps

    predicate = (lambda n: x_at(n) >= target_x) if vx > 0 else (lambda n: x_at(n) <= target_x)
    lo, hi = 0, max_steps
    if not predicate(hi):
        steps.append({
            "type": "checkpoint",
            "state": {"lo": lo, "hi": hi, "mid": hi, "xAtMid": x_at(hi), "targetX": target_x, "crossed": False},
            "explanationRight": "Even at the horizon the ball has not reached the target.",
            "explanationWrong": "Even at the horizon the ball has not reached the target.",
        })
        steps.append({"type": "done", "state": {"crossed": False}})
        return steps

    step_num = 1
    while lo < hi:
        mid = (lo + hi) // 2
        x_mid = x_at(mid)
        result = predicate(mid)
        if result:
            hi = mid
        else:
            lo = mid + 1
        steps.append({
            "type": "checkpoint",
            "state": {"lo": lo, "hi": hi, "mid": mid, "xAtMid": x_mid, "targetX": target_x, "crossed": result},
            "explanationRight": f"At frame {mid} x={x_mid:.1f}, bound updated to lo={lo} hi={hi}.",
            "explanationWrong": f"At frame {mid} x={x_mid:.1f}, the predicate is actually {result}.",
        })
        step_num += 1

    steps.append({"type": "done", "state": {"crossed": True, "intercept_frame": lo}})
    return steps


# ===========================================================================
# BOUNCER -- ID-check job-sim. Same admissible-threshold logic as binary
# search's predicate, wearing a doorman costume: reject if underage,
# expired, or already admitted; otherwise accept. Two entry points share
# one rule function:
#   - simulate_bouncer_id_check(inputs): a short FIXED sequence for the
#     guided trace-mode tutorial (first-time walkthrough).
#   - evaluate_bouncer_id_check(live_state, proposed_action): the live,
#     endless-mode grader. The customer is generated client-side in
#     script_bridged.js (with difficulty scaling tied to streak) and sent
#     up as live_state -- there's nothing to hide server-side since the ID
#     card is already fully visible to the player, so this is safe to let
#     the client own, the same way tetris's board state works.
# ===========================================================================

def _bouncer_judge(customer):
    """Returns (correct_action, ordered_list_of_failing_reasons)."""
    reasons = []
    if customer.get("id_expired"):
        reasons.append("expired")
    if customer.get("age", 0) < customer.get("legal_age", 21):
        reasons.append("underage")
    if customer.get("already_admitted"):
        reasons.append("duplicate")
    correct_action = "reject" if reasons else "accept"
    return correct_action, reasons


def _bouncer_reason_text(customer, reason):
    if reason == "expired":
        return f"the ID expired on {customer.get('expiry', 'an earlier date')}"
    if reason == "underage":
        return (f"{customer.get('name', 'this guest')} is {customer.get('age', '?')}, "
                f"under the {customer.get('legal_age', 21)} limit")
    if reason == "duplicate":
        return f"{customer.get('name', 'this guest')} was already let in earlier tonight"
    return "the ID doesn't check out"


def evaluate_bouncer_id_check(live_state, proposed_action=None):
    customer = live_state.get("customer", {})
    correct_action, reasons = _bouncer_judge(customer)
    primary_reason = reasons[0] if reasons else None
    name = customer.get("name", "this guest")

    if correct_action == "accept":
        explanation = f"{name}'s ID checks out -- let them in."
    else:
        explanation = f"Reject -- {_bouncer_reason_text(customer, primary_reason)}."

    result = {
        "correct": None,
        "best_action": correct_action,
        "failing_rule": primary_reason,
        "explanation": explanation,
    }

    if proposed_action is not None:
        is_correct = proposed_action == correct_action
        result["correct"] = is_correct
        if not is_correct:
            if correct_action == "reject":
                result["explanation"] = f"Wrong call -- should've rejected: {_bouncer_reason_text(customer, primary_reason)}."
            else:
                result["explanation"] = f"Wrong call -- {name}'s ID was actually fine, no reason to reject."

    return result


def simulate_bouncer_id_check(inputs):
    """Fixed 3-customer trace for the one-time guided tutorial pass. The
    real, replayable game is evaluate_bouncer_id_check via LIVE_EVALUATORS
    -- this only needs to exist so run_pipeline()/dispatch() has something
    deterministic to show a first-time player before they hit endless mode."""
    customers = inputs.get("customers", [
        {"name": "Jordan Lee", "age": 24, "id_expired": False, "already_admitted": False, "legal_age": 21},
        {"name": "Sam Ortiz", "age": 19, "id_expired": False, "already_admitted": False, "legal_age": 21},
        {"name": "Riley Chen", "age": 27, "id_expired": True, "already_admitted": False, "legal_age": 21},
    ])

    steps = []
    for idx, customer in enumerate(customers, start=1):
        correct_action, reasons = _bouncer_judge(customer)
        primary_reason = reasons[0] if reasons else None
        state = {
            "step": idx,
            "name": customer["name"],
            "age": customer["age"],
            "id_expired": customer["id_expired"],
            "legal_age": customer.get("legal_age", 21),
            "correct_action": correct_action,
            "failing_rule": primary_reason,
        }
        if correct_action == "reject":
            right = f"Correct -- {customer['name']} should be rejected: {_bouncer_reason_text(customer, primary_reason)}."
            wrong = f"Incorrect -- {customer['name']} should be rejected: {_bouncer_reason_text(customer, primary_reason)}."
        else:
            right = f"Correct -- {customer['name']}'s ID checks out, let them in."
            wrong = f"Incorrect -- {customer['name']}'s ID checks out, no reason to reject."
        steps.append({
            "type": "checkpoint",
            "state": state,
            "explanationRight": right,
            "explanationWrong": wrong,
        })

    steps.append({"type": "done", "state": steps[-1]["state"] if steps else {}})
    return steps

def simulate_dice_roll_simulator_amortized_rerender(inputs):
    rolls = inputs.get("rolls", [])
    total_rolls = inputs.get("total_rolls", len(rolls))
    if not rolls:
        rolls = [(i % 6) + 1 for i in range(total_rolls)]
    
    history_list = []
    total_render_ops = 0
    steps = []
    
    for k_idx, roll in enumerate(rolls[:total_rolls], start=1):
        history_list.append(roll)
        step_render_ops = k_idx
        total_render_ops += step_render_ops
        re_renders_more_than_two = step_render_ops > 2
        
        state = {
            "k": k_idx,
            "latest_roll": roll,
            "history_length": len(history_list),
            "step_render_ops": step_render_ops,
            "total_render_ops": total_render_ops,
            "re_renders_more_than_two": re_renders_more_than_two
        }
        
        steps.append({
            "type": "checkpoint",
            "state": state,
            "explanationRight": f"Correct! Step {k_idx} appends to the history list (length {len(history_list)}) and re-renders all {step_render_ops} items.",
            "explanationWrong": f"Incorrect. Because the full list is re-rendered on every roll, step {k_idx} performs {step_render_ops} re-renders."
        })
        
    last_state = steps[-1]["state"] if steps else {
        "k": 0,
        "latest_roll": 0,
        "history_length": 0,
        "step_render_ops": 0,
        "total_render_ops": 0,
        "re_renders_more_than_two": False
    }
    steps.append({
        "type": "done",
        "state": last_state
    })
    return steps


# NOTE: simulate_pacman_a_star_heuristic_evaluation intentionally does NOT
# live here. It is staged in generated_strategies/simulate_pacman_a_star_heuristic_evaluation.py
# (with a passing .tests.json) and is picked up automatically by
# load_generated_strategies() below. Keeping only one copy of this function
# avoids the shadow-duplicate bug where a hardcoded in-engine version could
# silently override the tested, staged one (or vice versa) depending on
# merge order. Run with --auto-merge once you're ready to trust it, or drop
# the "STAGED" marker from that file's header to promote it permanently.


def build_intro_step(algo_data):
    inputs = algo_data.get("inputs", {})
    intro_step = {
        "type": "intro",
        "algorithmName": algo_data.get("name", "Algorithm"),
        "rules": algo_data.get("rules", ""),
        "instructions": "At each step, click the highlighted tile that you think the algorithm will expand next. Explanations appear after every guess."
    }
    if "levelLayout" in inputs:
        intro_step["levelLayout"] = inputs["levelLayout"]
        intro_step["start"] = inputs.get("start")
        intro_step["goal"] = inputs.get("goal")
    elif algo_data.get("template") == "pong":
        intro_step["ball"] = inputs["ball"]
        intro_step["board"] = inputs["board"]
        intro_step["paddleX"] = inputs.get("paddle_x")
        intro_step["maxSteps"] = inputs.get("max_steps", 64)
    else:
        intro_step.update(inputs)

    return intro_step

# ===========================================================================
# 2b. DYNAMIC STRATEGY LOADING
#
# Hand-written strategies above are always trusted and always loaded.
# Anything dropped into one of GENERATED_STRATEGY_DIRS as a
# `simulate_<key>.py` file gets picked up automatically here -- no edit
# to this file required. This is what lets a code-generation pipeline
# (LLM-authored strategy + sibling `.tests.json`) add a new teachable
# concept just by writing files to disk.
#
# Convention (inferred from structure.txt -- confirm/adjust if your real
# generated files differ):
#   generated_strategies/simulate_<key>.py       defines simulate_<key>(inputs)
#   generated_strategies/simulate_<key>.tests.json   [{"inputs": ..., "expected": ...}, ...]
# ===========================================================================

# Only one of these ever existed on disk: generated_strategies/ lives at the
# repo root (a sibling of app.py), not inside templates/ (BASE_DIR). The
# other two candidate paths were dead entries that never matched anything.
GENERATED_STRATEGY_DIRS = [
    BASE_DIR.parent / "generated_strategies",
]


def _load_module_from_path(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strategy_key_from_filename(stem):
    # simulate_dice_roll_simulator_amortized_rerender -> dice_roll_simulator_amortized_rerender
    return stem[len("simulate_"):] if stem.startswith("simulate_") else stem


def _staged_marker(py_file):
    """
    Reads a generated file's own header comment to decide if it declared
    itself staged, e.g.:
      # STAGED, NOT YET WIRED into engine.py's STRATEGIES (unless --auto-merge was used)
    This makes staging a property of the FILE (author's intent, written
    by whatever generated it), not a hardcoded list maintained by hand
    in engine.py -- so a new staged strategy needs zero edits here to
    stay quarantined until --auto-merge.
    """
    try:
        with open(py_file, "r") as f:
            head = "".join(f.readline() for _ in range(5))
    except OSError:
        return False
    return "STAGED" in head.upper()


def _run_self_tests(func, tests_path):
    """
    Runs func against its sibling .tests.json, if one exists. A strategy
    with no tests file is loaded but unverified (logged as such) rather
    than rejected -- generated_strategies/ may contain files written
    before a test convention existed. A strategy that FAILS its tests is
    rejected: a broken generated function should never silently go live
    and start handing learners wrong answers.
    """
    if not tests_path.exists():
        return True, "no tests file found -- loaded unverified"

    try:
        with open(tests_path) as f:
            tests = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return False, f"tests file exists but could not be read/parsed: {e}"

    cases = tests if isinstance(tests, list) else tests.get("cases", [])
    if not cases:
        return True, "tests file present but empty -- loaded unverified"

    for i, case in enumerate(cases):
        inputs = case.get("inputs")
        expected = case.get("expected")
        try:
            actual = func(inputs)
        except Exception as e:
            return False, f"test case {i} raised {type(e).__name__}: {e}"
        if expected is not None and actual != expected:
            return False, f"test case {i} output did not match expected"

    return True, f"{len(cases)} test case(s) passed"


def load_generated_strategies(strict=False):
    """
    Scans GENERATED_STRATEGY_DIRS for simulate_*.py files, imports each,
    validates against its sibling .tests.json, and returns
    {strategy_key: function} for everything that imported cleanly and
    passed its tests.

    strict=True raises on the first failure instead of skipping it --
    use this in a CI / pre-deploy check so a broken generated strategy
    fails the build instead of quietly vanishing at runtime.
    """
    discovered = {}
    for directory in GENERATED_STRATEGY_DIRS:
        if not directory.exists():
            continue
        for py_file in sorted(directory.glob("simulate_*.py")):
            key = _strategy_key_from_filename(py_file.stem)
            tests_path = py_file.parent / f"{py_file.stem}.tests.json"

            if _staged_marker(py_file) and not AUTO_MERGE:
                print(f"[Strategy Loader] SKIPPED {py_file.name}: file declares itself "
                      f"STAGED (use --auto-merge to include it anyway)")
                continue

            try:
                module = _load_module_from_path(py_file)
            except Exception as e:
                msg = f"[Strategy Loader] SKIPPED {py_file.name}: import failed ({type(e).__name__}: {e})"
                if strict:
                    raise RuntimeError(msg) from e
                print(msg)
                continue

            func = getattr(module, py_file.stem, None)
            if func is None or not inspect.isfunction(func):
                # Fall back to any single simulate_-prefixed function in
                # the module, in case the internal name doesn't match
                # the filename exactly.
                candidates = [
                    v for n, v in vars(module).items()
                    if n.startswith("simulate_") and inspect.isfunction(v)
                ]
                func = candidates[0] if len(candidates) == 1 else None

            if func is None:
                msg = f"[Strategy Loader] SKIPPED {py_file.name}: no simulate_* function found inside it"
                if strict:
                    raise RuntimeError(msg)
                print(msg)
                continue

            ok, detail = _run_self_tests(func, tests_path)
            if not ok:
                msg = f"[Strategy Loader] SKIPPED {py_file.name}: {detail}"
                if strict:
                    raise RuntimeError(msg)
                print(msg)
                continue

            if key in discovered:
                print(f"[Strategy Loader] WARNING: duplicate strategy key '{key}' "
                      f"also found at {py_file} -- keeping the first one loaded")
                continue

            discovered[key] = func
            print(f"[Strategy Loader] Loaded '{key}' from {py_file} ({detail})")

    return discovered


STRATEGIES = {
    "breakout_binary_search_interception": simulate_breakout_binary_search_interception,
    "best_fit_allocation": simulate_tetris_best_fit,
    "binary_search_interception": simulate_pong_binary_search_interception,
    "dice_roll_simulator_amortized_rerender": simulate_dice_roll_simulator_amortized_rerender,
    # Promoted out of staging: its game folder + trace are already committed
    # on disk and no generated_strategies/ file exists for it anymore, so
    # this hardcoded version is the trusted, active implementation -- no
    # --auto-merge flag should be required to run it.
    "pacman_a_star_lesson_a_star": simulate_pacman_a_star_lesson_a_star,
    "bouncer_id_check": simulate_bouncer_id_check,
}

# Auto-discovered strategies are merged in without touching this file again.
# Hand-written strategies above always win on key collision -- a generated
# file can never silently shadow a trusted, hand-tested strategy.
for _key, _func in load_generated_strategies().items():
    STRATEGIES.setdefault(_key, _func)


# ===========================================================================
# 2c. LIVE EVALUATORS -- real gameplay, not trace playback
#
# A `simulate_*` strategy answers "what SHOULD happen, computed once,
# ahead of time" -- that's what builds the static _trace.json a learner
# quizzes against. A live evaluator answers a different question, asked
# fresh on every move: "given the board / grid / frontier as it ACTUALLY
# stands right now, and what the player just proposed, was that correct,
# and what's the best move?" No stored trace is involved -- it's the same
# shape as simulate_tetris_best_fit + /api/evaluate_placement already in
# app.py, just generalized so any strategy can offer it, not only tetris.
#
# Convention (mirrors the strategy convention above):
#   generated_strategies/evaluate_<key>.py   defines evaluate_<key>(live_state, proposed_action)
#
# Contract every evaluate_<key> function must follow:
#   Input:
#     live_state:      dict describing the CURRENT real game state
#                       (e.g. the live grid, current frontier/open-set,
#                       visited set -- whatever that algorithm needs to
#                       recompute the correct next move from scratch)
#     proposed_action:  whatever the player just did (e.g. the [r, c]
#                       tile they clicked), or None to just ask "what's
#                       the best move right now?"
#   Output: a dict with at least:
#     "correct":     bool or None (None if proposed_action was None)
#     "best_action": the algorithm's actual best move given live_state
#     "explanation": human-readable reason, for teaching, not just judging
# A strategy with no evaluator is trace-only -- it can still power the
# guided tutorial, it just can't power freeform live play yet.
# ===========================================================================

GENERATED_EVALUATOR_DIRS = GENERATED_STRATEGY_DIRS  # same folders, evaluate_*.py files


def _evaluator_key_from_filename(stem):
    return stem[len("evaluate_"):] if stem.startswith("evaluate_") else stem


def load_generated_evaluators(strict=False):
    """
    Mirrors load_generated_strategies(), but for evaluate_*.py files.
    No test-file convention is assumed yet (evaluators are newer / less
    standardized than strategies) -- every evaluator that imports cleanly
    and exposes a matching function is loaded. Tighten this the same way
    _run_self_tests tightened strategies once evaluate_*.tests.json
    becomes a real convention in this codebase.
    """
    discovered = {}
    for directory in GENERATED_EVALUATOR_DIRS:
        if not directory.exists():
            continue
        for py_file in sorted(directory.glob("evaluate_*.py")):
            key = _evaluator_key_from_filename(py_file.stem)

            if _staged_marker(py_file) and not AUTO_MERGE:
                print(f"[Evaluator Loader] SKIPPED {py_file.name}: file declares itself "
                      f"STAGED (use --auto-merge to include it anyway)")
                continue

            try:
                module = _load_module_from_path(py_file)
            except Exception as e:
                msg = f"[Evaluator Loader] SKIPPED {py_file.name}: import failed ({type(e).__name__}: {e})"
                if strict:
                    raise RuntimeError(msg) from e
                print(msg)
                continue

            func = getattr(module, py_file.stem, None)
            if func is None or not inspect.isfunction(func):
                candidates = [
                    v for n, v in vars(module).items()
                    if n.startswith("evaluate_") and inspect.isfunction(v)
                ]
                func = candidates[0] if len(candidates) == 1 else None

            if func is None:
                msg = f"[Evaluator Loader] SKIPPED {py_file.name}: no evaluate_* function found inside it"
                if strict:
                    raise RuntimeError(msg)
                print(msg)
                continue

            if key in discovered:
                print(f"[Evaluator Loader] WARNING: duplicate evaluator key '{key}' "
                      f"also found at {py_file} -- keeping the first one loaded")
                continue

            discovered[key] = func
            print(f"[Evaluator Loader] Loaded '{key}' from {py_file}")

    return discovered


LIVE_EVALUATORS = {
    # Tetris already does this, just not through this registry yet --
    # simulate_tetris_best_fit is already a pure "given the real board
    # right now, what's correct" function (see app.py's
    # /api/evaluate_placement), so it doubles as its own live evaluator.
    "best_fit_allocation": simulate_tetris_best_fit,
    # The real bouncer game -- endless, client-generated customers graded
    # fresh every round via /api/evaluate/<algo_key>. simulate_bouncer_id_check
    # (in STRATEGIES) only powers the one-time fixed-trace tutorial pass.
    "bouncer_id_check": evaluate_bouncer_id_check,
}

for _key, _func in load_generated_evaluators().items():
    LIVE_EVALUATORS.setdefault(_key, _func)


def dispatch_live(algo_key, algo_data, live_state, proposed_action=None):
    """
    The live-play counterpart to dispatch(). Recomputes the correct move
    from live_state every call -- nothing is read from or written to a
    _trace.json file. Raises NotImplementedError (caught by the Flask
    route, not a 500) for strategies that only have trace support so
    far, so the frontend can fall back to tutorial/quiz mode cleanly.
    """
    strategy = algo_data.get("strategy")
    evaluator = LIVE_EVALUATORS.get(strategy)
    if evaluator is None:
        raise NotImplementedError(
            f"No live evaluator registered for strategy '{strategy}' "
            f"(algorithm '{algo_key}'). Add generated_strategies/evaluate_{strategy}.py "
            f"to enable live play for it; trace-based tutorial mode still works."
        )
    return evaluator(live_state, proposed_action)

# NOTE ON STAGING: there used to be a hand-maintained _STAGED_STRATEGIES
# dict here gating two hardcoded pacman functions behind --auto-merge.
# It also documented a past bug: a dead "a_star" key once pointed at
# `simulate_pacman_a_star`, a function that was never defined anywhere in
# this file, which raised a NameError at import time and crashed the whole
# module -- taking every game down, not just pacman. That key never existed
# in algorithms.json and has been fully removed, not just unwired.
#
# `pacman_a_star_lesson_a_star` has since been promoted into STRATEGIES
# above (its game folder + trace are already committed and trusted).
# `pacman_a_star_heuristic_evaluation` was removed from this file entirely
# -- it now lives only in generated_strategies/, staged via that file's own
# "STAGED" header marker, and is picked up by load_generated_strategies()
# below. This makes staging a property of each file rather than a list
# maintained by hand here, so a new staged strategy needs zero edits to
# this file to stay quarantined until --auto-merge (or until its header
# marker is removed).

def dispatch(algo_key, algo_data):
    strategy = algo_data.get("strategy")
    if strategy in STRATEGIES:
        raw_steps = STRATEGIES[strategy](algo_data["inputs"])
        return to_checkpoint_trace(raw_steps)
    raise NotImplementedError(f"Unknown strategy '{strategy}' for algorithm '{algo_key}'")


def to_checkpoint_trace(raw_steps):
    """
    Wraps a generated strategy function's raw output into the
    {"type": "checkpoint"/"done"} schema that pass_2_generate_explanations,
    build_intro_step, and the frontend adapter all expect. Search-style
    strategies (like simulate_pacman_a_star) already emit this schema
    natively and pass through unchanged.
    """
    if raw_steps and isinstance(raw_steps[0], dict) and "type" in raw_steps[0]:
        return raw_steps  # already schema-compliant, e.g. A*

    trace = []
    for step in raw_steps:
        trace.append({
            "type": "checkpoint",
            "state": step,
            "taskProcessed": f"Step {step.get('step', len(trace) + 1)}",
            "explanationRight": step.get("explanation", ""),
            "explanationWrong": (
                f"A different placement would either not fit or waste more "
                f"space than the chosen allocation for '{step.get('piece', 'this item')}'."
            ),
        })
    trace.append({"type": "done", "state": raw_steps[-1] if raw_steps else {}})
    return trace
# ===========================================================================
# 3. PASS 2: OPTIONAL LLM EXPLANATION ENHANCEMENT
# ===========================================================================

def query_llm_stream(prompt, format_json=False):
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": 0.1, "num_predict": 2048}
    }
    if format_json:
        payload["format"] = "json"

    try:
        response = requests.post(OLLAMA_URL, json=payload, stream=True)
        response.raise_for_status()

        full_text = ""
        for line in response.iter_lines():
            if line:
                body = json.loads(line)
                chunk = body.get("response", "")
                print(chunk, end="", flush=True)
                full_text += chunk
        print("\n")
        return full_text
    except Exception as e:
        print(f"\n[Warning] Ollama LLM query failed ({e}). Using templated explanations.")
        return None

def pass_2_generate_explanations(algo_name, perfect_trace):
    needs_explanation = [s for s in perfect_trace if s["type"] == "checkpoint" and "explanationRight" not in s]
    if not needs_explanation:
        return perfect_trace

    prompt = f"""
    You are a Computer Science tutor. Here is a mathematically correct trace for {algo_name}:
    {json.dumps(perfect_trace, indent=2)}

    For every checkpoint object in the trace, add two properties:
    - "explanationRight": 1 sentence explaining why this move is correct according to {algo_name}.
    - "explanationWrong": 1 sentence explaining what rule would be broken if a different choice was made.

    Output ONLY a JSON object with a "steps" key containing the updated trace array.
    """

    print("--- Executing Pass 2: LLM Generating Explanations (Streaming below) ---")
    raw_json = query_llm_stream(prompt, format_json=True)
    if raw_json:
        try:
            data = json.loads(raw_json)
            return data.get("steps", data)
        except Exception:
            pass
    return perfect_trace

# ===========================================================================
# 4. PIPELINE EXECUTION
# ===========================================================================
# NOTE: a write_manifest() step used to run here, writing manifest.json into
# a PACMAN_DIR that pointed at templates/games/pacman-astar/ -- a folder from
# the old hand-built prototype that no longer exists. Nothing in app.py ever
# read that manifest (confirmed by grep), so both were removed rather than
# repointed. Each template's own games/<template_type>/ folder is the real,
# live source of truth for its trace files -- see the DYNAMIC SAVING step
# below.

def _trace_path(algo_key, algo_data):
    """Where run_pipeline() will write/has written this algorithm's trace.
    Shared by run_pipeline() (to write it) and run_all() (to check whether
    it already exists before spending an Ollama call regenerating it)."""
    template_type = algo_data.get("template", "pac_man")
    return BASE_DIR / "games" / template_type / f"{algo_key}_trace.json"


def run_pipeline(algo_key):
    if algo_key not in PACMAN_ALGORITHMS:
        raise ValueError(f"Algorithm '{algo_key}' not found in configuration.")

    algo_data = PACMAN_ALGORITHMS[algo_key]
    template_type = algo_data.get("template", "pac_man")

    print(f"--- Executing Pass 1: Math Trace for {algo_data['name']} ---")
    
    # 1. Compute deterministic trace using registered strategy
    perfect_trace = dispatch(algo_key, algo_data)

    # 2. Add LLM dynamic explanations if needed
    explained_trace = pass_2_generate_explanations(algo_data["name"], perfect_trace)
    
    # 3. Bundle intro step
    intro_step = build_intro_step(algo_data)
    final_trace = [intro_step] + explained_trace
    
    # DYNAMIC SAVING: Save directly into templates/games/<template_type>/
    filename = _trace_path(algo_key, algo_data)
    filename.parent.mkdir(parents=True, exist_ok=True)

    with open(filename, "w") as f:
        json.dump(final_trace, f, indent=2)

    print(f"[Success] Trace saved to {filename}")

def run_all():
    for algo_key in PACMAN_ALGORITHMS:
        try:
            algo_data = PACMAN_ALGORITHMS[algo_key]
            # We skip the network_node firewall template since it doesn't need pathfinding math
            if algo_data.get("template") == "network_node":
                continue
            # Skip staged-but-not-yet-wired strategies quietly instead of
            # logging them as FAILED -- they're intentionally unwired, not
            # broken. STRATEGIES already reflects every hand-written
            # strategy plus every generated_strategies/ file that either
            # isn't STAGED or was included via --auto-merge, so "not in
            # STRATEGIES" is a complete, self-maintaining staged check --
            # no hardcoded list to keep in sync here.
            strategy = algo_data.get("strategy")
            if strategy not in STRATEGIES:
                print(f"[Skipped] {algo_key}: strategy '{strategy}' is not wired into STRATEGIES yet "
                      f"(staged in generated_strategies/, or missing entirely -- use --auto-merge if staged)")
                continue
            # Skip algorithms whose trace already exists -- regenerating
            # calls Ollama (pass_2_generate_explanations) per algorithm, so
            # a bare `python engine.py` run used to re-bill every existing
            # algorithm's LLM cost just to pick up one newly-added one.
            # Pass --force to intentionally regenerate everything anyway.
            trace_path = _trace_path(algo_key, algo_data)
            if trace_path.exists() and not FORCE:
                print(f"[Up to date] {algo_key}: trace already exists at {trace_path.name} (use --force to regenerate)")
                continue
            run_pipeline(algo_key)
        except Exception as e:
            print(f"FAILED: {algo_key}: {e}")

if __name__ == "__main__":
    run_all()