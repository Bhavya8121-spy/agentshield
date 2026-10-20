import os
import re
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
SCRIPT_JS_PATH = BASE_DIR / "script.js"
OUTPUT_JS_PATH = BASE_DIR / "script_bridged.js"

load_dotenv()
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ==========================================
# 1.5 GROUND TRUTH: THE VERIFIED ALGORITHM, PORTED TO JS
# ==========================================
# This is the same role PONG_GAME_FACTS plays in generate_pong.py: a
# non-negotiable fact fed into the prompt so the model can't invent its own
# (possibly wrong) version of the algorithm. It's not a description of the
# algorithm -- it IS the algorithm, hand-ported from the Python reference in
# generate_pong.py's PONG_SEED_CODE and verified with Node to produce
# identical output on the same test cases (frame 58/y=310, frame 18/y=320,
# and the same "no interception" edge case). The model's job is to wire this
# exact function into the game loop and expose it through the window bridge
# -- not to re-derive or "improve" the algorithm.
REFERENCE_ALGORITHM_JS = r"""
function simulatePongBinarySearchInterception(inputs) {
  const { ball, board, paddleX } = inputs;
  const maxSteps = inputs.maxSteps ?? 32;
  const { x: bx, y: by, vx, vy } = ball;
  const height = board.height;

  const steps = [];
  const xAt = (n) => bx + vx * n;

  let predicate;
  if (vx > 0) {
    predicate = (n) => xAt(n) >= paddleX;
  } else if (vx < 0) {
    predicate = (n) => xAt(n) <= paddleX;
  } else {
    steps.push({
      step: 1, lo: 0, hi: 0, mid: 0,
      xAtMid: bx, predicateTrue: false,
      explanation: "Ball's horizontal velocity is zero, so it never reaches the paddle's x-line; binary search is not applicable here.",
    });
    return steps;
  }

  let lo = 0, hi = maxSteps;
  if (!predicate(hi)) {
    steps.push({
      step: 1, lo, hi, mid: hi,
      xAtMid: xAt(hi), predicateTrue: false,
      explanation: `Even at the search horizon of ${maxSteps} frames, the ball has not reached x=${paddleX}, so no interception exists within this window.`,
    });
    return steps;
  }

  let stepNum = 1;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    const xMid = xAt(mid);
    const result = predicate(mid);
    let explanation;
    if (result) {
      explanation = `At frame ${mid}, predicted ball x is ${xMid.toFixed(1)}, which has already reached paddle line x=${paddleX}, so the earliest interception frame must be at or before ${mid}; search shrinks the upper bound to ${mid}.`;
      hi = mid;
    } else {
      explanation = `At frame ${mid}, predicted ball x is ${xMid.toFixed(1)}, which has not yet reached paddle line x=${paddleX}, so the interception frame must be after ${mid}; search raises the lower bound to ${mid + 1}.`;
      lo = mid + 1;
    }
    steps.push({ step: stepNum, lo, hi, mid, xAtMid: xMid, predicateTrue: result, explanation });
    stepNum++;
  }

  const interceptFrame = lo;
  const unwrappedY = by + vy * interceptFrame;
  const period = 2 * height;
  let m = unwrappedY % period;
  if (m < 0) m += period;
  const predictedY = m <= height ? m : period - m;

  steps.push({
    step: stepNum, lo, hi, mid: interceptFrame,
    xAtMid: xAt(interceptFrame), predicateTrue: true,
    predictedY, interceptFrame,
    explanation: `Binary search converged: the ball first reaches x=${paddleX} at frame ${interceptFrame}. Unfolding the board to account for wall bounces gives a predicted y of ${predictedY.toFixed(1)}, which is where the paddle should move to intercept the ball.`,
  });

  return steps;
}
""".strip()

# ==========================================
# 2. PROMPT
# ==========================================
FRONTEND_SYSTEM_PROMPT = f"""
You are an expert full-stack web developer and JavaScript engineer.
Your task is to modify an existing classic Pong game script so it can be
controlled and observed externally by a Binary-Search Interception
Visualizer panel sitting on the same HTML page.

I will provide the original Pong JavaScript code, followed by a verified
reference algorithm (REFERENCE ALGORITHM, below). You must output ONLY the
modified JavaScript code. Do not include markdown formatting (like
```javascript) or any explanations.

REFERENCE ALGORITHM (ground truth -- copy this function into the script
VERBATIM, unmodified, as a standalone top-level function. Do not rewrite,
"simplify", or re-derive its logic -- it has already been validated against
hand-traced test cases and any behavioral change would break that
guarantee):

{REFERENCE_ALGORITHM_JS}

Requirements for the modification:
1. Copy `simulatePongBinarySearchInterception` from the reference algorithm
   above into the script verbatim, as a standalone top-level function.
2. Expose a global function `window.enableAIPaddle(side)` where side is
   either "left" or "right". When called, the specified paddle stops
   responding to its keyboard controls (W/S for left, Up/Down for right) and
   is instead driven by the AI: every frame, call
   `simulatePongBinarySearchInterception` with the ball's current position
   (ballX, ballY), velocity (ballSpeedX, ballSpeedY), the board
   ({{width: canvas.width, height: canvas.height}}), and paddleX set to that
   paddle's x-line (0 for left, canvas.width - paddleWidth for right), with
   maxSteps of 64. Move that paddle's Y toward the last step's `predictedY`
   at the existing paddleSpeed, clamped so the paddle stays on-screen
   (matching the same bounds logic already used for keyboard-controlled
   paddle movement in this script). Only recompute a new prediction when the
   ball's direction toward that paddle could plausibly have changed (e.g.
   once per frame is fine, since the algorithm itself is cheap and
   idempotent for an unchanged ball state).
3. Expose `window.disableAIPaddle(side)` to hand control of that paddle back
   to the keyboard.
4. Expose `window.onInterceptionStep(callback)` that registers a callback.
   Every time `simulatePongBinarySearchInterception` is called for an
   AI-controlled paddle, invoke `callback(steps)` with the full array of
   step objects it returned (the array already contains an `explanation`
   string per step) so an external visualizer panel can render the search
   converging in real time. Do not throw if no callback has been registered.
5. Create a global function `window.triggerGameAction(actionType, payload)`
   as a general bridge for future visualizer-panel interactions (e.g.
   actionType "setMaxSteps" to change the search horizon, actionType
   "resetBall" to call the existing reset() function). Keep it a simple
   switch/if-else over actionType; unrecognized actionType should be a
   no-op, not a throw.
6. None of this should change default behavior when window.enableAIPaddle is
   never called -- the game must play exactly as it does today for a normal
   two-player match.
"""


def generate_bridged_javascript():
    if not SCRIPT_JS_PATH.exists():
        print(f"Error: Could not find {SCRIPT_JS_PATH}")
        return

    print("Loading original script.js...")
    original_js = SCRIPT_JS_PATH.read_text()

    prompt = f"""{FRONTEND_SYSTEM_PROMPT}

ORIGINAL JAVASCRIPT:
{original_js}
"""

    print("Sending prompt to Gemini...")
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )

    # Clean up any potential markdown formatting the AI might sneak in
    clean_code = response.text.strip()
    if clean_code.startswith("```javascript"):
        clean_code = clean_code.replace("```javascript", "", 1)
    if clean_code.startswith("```js"):
        clean_code = clean_code.replace("```js", "", 1)
    if clean_code.endswith("```"):
        clean_code = clean_code.rsplit("```", 1)[0]

    clean_code = clean_code.strip()

    # Sanity check before writing to disk: make sure the model actually
    # included the bridge surface we asked for, so a silent bad generation
    # doesn't get wired into index.html unnoticed.
    required_markers = [
        "simulatePongBinarySearchInterception",
        "window.enableAIPaddle",
        "window.disableAIPaddle",
        "window.onInterceptionStep",
        "window.triggerGameAction",
    ]
    missing = [m for m in required_markers if m not in clean_code]
    if missing:
        print(f"[Warning] Generated script is missing expected bridge symbols: {missing}")
        print("Not overwriting any existing output -- review the raw response before retrying.")
        return

    # Save the new bridged script
    OUTPUT_JS_PATH.write_text(clean_code)
    print(f"\n[Success] Bridged JavaScript saved to {OUTPUT_JS_PATH.name}!")
    print('Update your index.html to point to <script src="script_bridged.js"></script> to test it.')
    print('Then call window.enableAIPaddle("right") from the console (or a visualizer button)')
    print('and window.onInterceptionStep(steps => console.log(steps)) to watch the search converge.')


if __name__ == "__main__":
    print("Initializing AI Frontend Generator...")
    generate_bridged_javascript()