# STAGED, NOT YET WIRED into engine.py's LIVE_EVALUATORS (unless --auto-merge was used)
# Game: pacman-a-star
# Concept: A* Search Path Admissibility and Heuristic Evaluation -- LIVE MODE
#
# Counterpart to simulate_pacman_a_star_heuristic_evaluation.py. That
# function computes one fixed trace ahead of time; this one answers "given
# the frontier as it ACTUALLY stands right now, what's the correct node to
# expand next?" -- recomputed fresh on every call, the same way
# simulate_tetris_best_fit already works for tetris. This is what lets the
# frontend ask the player "which tile do you expand next?" against a REAL,
# possibly player-influenced frontier, instead of quizzing a canned replay.
#
# live_state shape:
#   {
#     "grid": [[...]],                # same grid format as the trace version
#     "goal": [gr, gc],
#     "frontier": [[r, c, g], ...],    # every node currently in the open set,
#                                      # with its g-cost (path cost so far)
#     "visited": [[r, c], ...]         # already-expanded nodes (excluded)
#   }
# proposed_action:
#   [r, c] -- the tile the player clicked as "expand this one next", or
#   None to just ask "what's the best move right now?"
#
# Returns:
#   {
#     "correct": bool | None,
#     "best_action": [r, c] | None,
#     "f_value": int | None,
#     "explanation": str,
#     "ranked_frontier": [{"cell": [r, c], "g": ..., "h": ..., "f": ...}, ...]
#   }

def evaluate_pacman_a_star_heuristic_evaluation(live_state, proposed_action=None):
    grid = live_state["grid"]
    goal = live_state["goal"]
    frontier = live_state.get("frontier", [])
    visited = {tuple(v) for v in live_state.get("visited", [])}

    goal_r, goal_c = goal[0], goal[1]

    def manhattan(r, c):
        return abs(r - goal_r) + abs(c - goal_c)

    live_frontier = [
        (r, c, g) for (r, c, g) in frontier if (r, c) not in visited
    ]

    if not live_frontier:
        return {
            "correct": None,
            "best_action": None,
            "f_value": None,
            "explanation": "The frontier is empty -- there's nothing left to expand.",
            "ranked_frontier": [],
        }

    scored = [
        {"cell": [r, c], "g": g, "h": manhattan(r, c), "f": g + manhattan(r, c)}
        for (r, c, g) in live_frontier
    ]
    # A*'s tie-break is normally FIFO insertion order, which a live,
    # possibly-replayed frontier can't guarantee -- so ties break on
    # lowest h, then row, then col instead. Deterministic, documented,
    # and close enough for teaching purposes; note this if you need
    # bit-for-bit parity with the trace version's tie-breaking.
    scored.sort(key=lambda e: (e["f"], e["h"], e["cell"][0], e["cell"][1]))

    best = scored[0]
    best_cell = best["cell"]

    result = {
        "correct": None,
        "best_action": best_cell,
        "f_value": best["f"],
        "explanation": (
            f"Cell {tuple(best_cell)} has the lowest f-score (f={best['f']} = "
            f"g={best['g']} + h={best['h']}), so A* expands it next."
        ),
        "ranked_frontier": scored,
    }

    if proposed_action is not None:
        proposed = list(proposed_action)
        is_correct = proposed == best_cell
        result["correct"] = is_correct
        if not is_correct:
            match = next((e for e in scored if e["cell"] == proposed), None)
            if match:
                result["explanation"] = (
                    f"Not quite -- {tuple(proposed)} has f={match['f']} "
                    f"(g={match['g']} + h={match['h']}), but {tuple(best_cell)} "
                    f"has a lower f={best['f']}, so A* expands that one first."
                )
            else:
                result["explanation"] = (
                    f"{tuple(proposed)} isn't even in the current frontier, so it "
                    f"can't be expanded next. The lowest-f node available is "
                    f"{tuple(best_cell)} (f={best['f']})."
                )

    return result