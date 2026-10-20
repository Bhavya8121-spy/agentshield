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
# 2. PROMPTS
# ==========================================
FRONTEND_SYSTEM_PROMPT = """
You are an expert full-stack web developer and JavaScript engineer.
Your task is to modify an existing classic Tetris game script so it can be controlled 
externally by an Algorithm Visualizer sitting on the same HTML page.

I will provide the original Tetris JavaScript code. 
You must output ONLY the modified JavaScript code. Do not include markdown formatting (like ```javascript) or any explanations.

Requirements for the modification:
1. Expose a global function on the `window` object called `window.forceSpawnPiece(pieceName)`.
2. When called, this function should pause the normal game timer (so random pieces stop falling).
3. It must map the visualizer's string (e.g., 'O-Block', 'I-Block') to the correct shape index in the Tetris game.
4. It must spawn that piece at the top of the board.
5. Create a global function `window.triggerGameAction(actionType, payload)` as a general bridge for future visualizer clicks.
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

    # Save the new bridged script
    OUTPUT_JS_PATH.write_text(clean_code)
    print(f"\n[Success] Bridged JavaScript saved to {OUTPUT_JS_PATH.name}!")
    print("Update your index.html to point to <script src=\"script_bridged.js\"></script> to test it.")

if __name__ == "__main__":
    print("Initializing AI Frontend Generator...")
    generate_bridged_javascript()