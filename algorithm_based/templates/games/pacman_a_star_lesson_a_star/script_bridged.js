let canvas = document.getElementById("scene-canvas") || document.getElementById("gameCanvas");
let ctx = canvas ? canvas.getContext("2d") : null;

const DEFAULT_LEVEL_LAYOUT = [
  "1111111111111111111111111111",
  "1222222222112222222222222221",
  "1211112112112112112111112121",
  "1311112112112112112111112131",
  "1222222222222222222222222221",
  "1211112111112111112111112121",
  "1222222112222222211222222221",
  "1111112112111112112111111111",
  "0000012112110002112110000000",
  "1111112112111112112111111111",
  "1222222222222112222222222221",
  "1211112111112111112111112121",
  "1222212222222222222222122221",
  "1111212111110001111122111111",
  "0000212110000000000122110000",
  "1111212110111111101122111111",
  "1222222220222222202222222221",
  "1211112112111112112111112121",
  "1222222112222222211222222221",
  "1111112112111112112111111111",
  "0000012112110002112110000000",
  "1111112112111112112111111111",
  "1222222222222222222222222221",
  "1211112111112111112111112121",
  "1311112222222112222222112131",
  "1222222111112111111122222221",
  "1111112112222222212111111111",
  "1222222222112222112222222221",
  "1211111112112112111111112121",
  "1222222222222222222222222221",
  "1111111111111111111111111111",
];

const MIN_TILE = 26;
const MAX_TILE = 56;
const MAX_BOARD_PX = 560;
const CROP_PADDING = 1;

let board = null;
let activeMarker = null;

function isWallChar(ch) {
  return ch === "1";
}

function collectAllCells(trace) {
  const cells = [];
  for (const step of trace) {
    if (step.type === "checkpoint") {
      if (step.state) {
        (step.state.visited || []).forEach((c) => cells.push(c));
        (step.state.frontier || []).forEach((c) => cells.push(c));
        if (step.state.current) cells.push(step.state.current);
        if (step.state.current_r !== undefined) cells.push([step.state.current_r, step.state.current_c]);
      }
      if (step.targetCell) cells.push(step.targetCell);
    } else if (step.type === "done") {
      if (step.state && step.state.path) {
        (step.state.path || []).forEach((c) => cells.push(c));
      }
    }
  }
  return cells;
}

function cellIsOpenIn(layout, row, col) {
  if (row < 0 || col < 0 || row >= layout.length) return false;
  const line = layout[row];
  if (col >= line.length) return false;
  return !isWallChar(line[col]);
}

function sliceBoard(full, minRow, maxRow, minCol, maxCol) {
  const fullRows = full.length;
  const fullCols = full[0].length;
  const rowOffset = Math.max(0, minRow - CROP_PADDING);
  const colOffset = Math.max(0, minCol - CROP_PADDING);
  const rowEnd = Math.min(fullRows - 1, maxRow + CROP_PADDING);
  const colEnd = Math.min(fullCols - 1, maxCol + CROP_PADDING);
  const layout = [];
  for (let r = rowOffset; r <= rowEnd; r++) {
    layout.push(full[r].slice(colOffset, colEnd + 1));
  }
  return { layout, rowOffset, colOffset, rows: layout.length, cols: layout[0].length };
}

function buildBoard(trace) {
  const introStep = trace[0] || {};
  const cells = collectAllCells(trace);
  if (cells.length === 0) {
    return { layout: ["0"], rowOffset: 0, colOffset: 0, rows: 1, cols: 1 };
  }

  const rows = cells.map((c) => c[0]);
  const cols = cells.map((c) => c[1]);
  const minRow = Math.min(...rows);
  const maxRow = Math.max(...rows);
  const minCol = Math.min(...cols);
  const maxCol = Math.max(...cols);

  const layoutInput = introStep.grid || introStep.levelLayout;
  if (layoutInput && layoutInput.length) {
    const raw = layoutInput.map(r => Array.isArray(r) ? r.join("") : String(r));
    return sliceBoard(raw, minRow, maxRow, minCol, maxCol);
  }

  const matchesDefault = cells.every(([r, c]) => cellIsOpenIn(DEFAULT_LEVEL_LAYOUT, r, c));
  if (matchesDefault) {
    return sliceBoard(DEFAULT_LEVEL_LAYOUT, minRow, maxRow, minCol, maxCol);
  }

  const rowOffset = Math.max(0, minRow - CROP_PADDING);
  const colOffset = Math.max(0, minCol - CROP_PADDING);
  const rowsCount = maxRow - minRow + CROP_PADDING * 2 + 1;
  const colsCount = maxCol - minCol + CROP_PADDING * 2 + 1;
  const touched = new Set(cells.map(([r, c]) => `${r},${c}`));
  const layout = [];
  for (let r = 0; r < rowsCount; r++) {
    let line = "";
    for (let c = 0; c < colsCount; c++) {
      line += touched.has(`${r + rowOffset},${c + colOffset}`) ? "0" : "1";
    }
    layout.push(line);
  }
  return { layout, rowOffset, colOffset, rows: rowsCount, cols: colsCount };
}

function sizeCanvasToBoard(b) {
  canvas = document.getElementById("scene-canvas") || document.getElementById("gameCanvas");
  if (!canvas) return;
  ctx = canvas.getContext("2d");
  const tileFromWidth = Math.floor(MAX_BOARD_PX / Math.max(b.cols, b.rows));
  b.tileSize = Math.max(MIN_TILE, Math.min(MAX_TILE, tileFromWidth));
  canvas.width = b.cols * b.tileSize;
  canvas.height = b.rows * b.tileSize;
}

function toLocal(b, [row, col]) {
  return [row - b.rowOffset, col - b.colOffset];
}

function isWallAt(b, row, col) {
  const [lr, lc] = toLocal(b, [row, col]);
  if (lr < 0 || lc < 0 || lr >= b.rows || lc >= b.cols) return true;
  return isWallChar(b.layout[lr][lc]);
}

function drawMazeBackground(b) {
  if (!ctx) return;
  const t = b.tileSize;
  for (let r = 0; r < b.rows; r++) {
    for (let c = 0; c < b.cols; c++) {
      const val = b.layout[r][c];
      const x = c * t;
      const y = r * t;

      if (isWallChar(val)) {
        const inset = t * 0.08;
        ctx.fillStyle = "#001b4d";
        ctx.fillRect(x + inset, y + inset, t - inset * 2, t - inset * 2);
        ctx.strokeStyle = "#0ff";
        ctx.lineWidth = 2;
        ctx.strokeRect(x + inset + 2, y + inset + 2, t - inset * 2 - 4, t - inset * 2 - 4);
      } else {
        ctx.fillStyle = "#000016";
        ctx.fillRect(x, y, t, t);
        ctx.fillStyle = "#ffd966";
        ctx.beginPath();
        const dotR = val === "3" ? t * 0.14 : t * 0.08;
        ctx.arc(x + t / 2, y + t / 2, dotR, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
}

function drawTileHighlight(b, cell, fillStyle, strokeStyle) {
  if (!ctx) return;
  const [lr, lc] = toLocal(b, cell);
  const t = b.tileSize;
  const x = lc * t;
  const y = lr * t;
  ctx.fillStyle = fillStyle;
  ctx.fillRect(x, y, t, t);
  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, t, t);
}

function drawPacmanAtPixel(px, py, radius, mouthPhase) {
  if (!ctx) return;
  const mouthAngle = 0.15 + Math.abs(Math.sin(mouthPhase * Math.PI)) * 0.35;
  ctx.fillStyle = "#ffd966";
  ctx.beginPath();
  ctx.arc(px, py, radius, mouthAngle, Math.PI * 2 - mouthAngle);
  ctx.lineTo(px, py);
  ctx.closePath();
  ctx.fill();
}

function drawPacmanMarker(b, cell, mouthPhase = 0.5) {
  const [lr, lc] = toLocal(b, cell);
  const t = b.tileSize;
  drawPacmanAtPixel(lc * t + t / 2, lr * t + t / 2, t * 0.4, mouthPhase);
}

function drawGhostMarker(b, cell, color) {
  if (!ctx) return;
  const [lr, lc] = toLocal(b, cell);
  const t = b.tileSize;
  const cx = lc * t + t / 2;
  const cy = lr * t + t / 2;
  const w = t * 0.62;
  const h = t * 0.62;
  const top = cy - h / 2;
  const bottom = cy + h / 2;
  const left = cx - w / 2;
  const right = cx + w / 2;

  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(cx, top + w / 2, w / 2, Math.PI, 0);
  ctx.lineTo(right, bottom);
  const zig = 4;
  for (let i = 0; i < zig; i++) {
    const zx = right - (w / zig) * (i + 0.5);
    const zy = i % 2 === 0 ? bottom : bottom - h * 0.18;
    ctx.lineTo(zx, zy);
  }
  ctx.lineTo(left, bottom);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = "#0b1220";
  ctx.beginPath();
  ctx.arc(cx - w * 0.18, cy - h * 0.05, w * 0.11, 0, Math.PI * 2);
  ctx.arc(cx + w * 0.18, cy - h * 0.05, w * 0.11, 0, Math.PI * 2);
  ctx.fill();
}

function drawCherry(b, cell) {
  if (!ctx) return;
  const [lr, lc] = toLocal(b, cell);
  const t = b.tileSize;
  const cx = lc * t + t / 2;
  const cy = lr * t + t / 2 + t * 0.08;
  const r = t * 0.14;

  ctx.strokeStyle = "#2ecc71";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx - r * 0.6, cy - r * 1.6);
  ctx.lineTo(cx, cy - r * 2.6);
  ctx.lineTo(cx + r * 0.9, cy - r * 1.8);
  ctx.stroke();

  ctx.fillStyle = "#e63946";
  ctx.beginPath();
  ctx.arc(cx - r * 0.6, cy - r * 0.2, r, 0, Math.PI * 2);
  ctx.arc(cx + r * 0.7, cy, r, 0, Math.PI * 2);
  ctx.fill();
}

function drawStartMarker(b, cell) {
  if (!ctx) return;
  const [lr, lc] = toLocal(b, cell);
  const t = b.tileSize;
  const x = lc * t;
  const y = lr * t;
  ctx.strokeStyle = "#2ecc71";
  ctx.lineWidth = 2;
  ctx.setLineDash([4, 3]);
  ctx.strokeRect(x + 2, y + 2, t - 4, t - 4);
  ctx.setLineDash([]);
}

function drawFinalPath(b, pathCells) {
  if (!ctx || !pathCells || pathCells.length === 0) return;
  const t = b.tileSize;
  ctx.strokeStyle = "#ff9d2f";
  ctx.lineWidth = 4;
  ctx.beginPath();
  pathCells.forEach((cell, i) => {
    const [lr, lc] = toLocal(b, cell);
    const x = lc * t + t / 2;
    const y = lr * t + t / 2;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawStaticFrame(extra) {
  if (!board || !canvas || !ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawMazeBackground(board);
  if (puzzleStart) drawStartMarker(board, puzzleStart);
  if (puzzleGoal) drawCherry(board, puzzleGoal);
  if (extra) extra();
  if (activeMarker) {
    const cell = activeMarker.cell;
    if (activeMarker.revealed) {
      const isGoal = activeMarker.state && activeMarker.state.is_goal;
      const color = isGoal ? "#10b981" : "#ef4444";
      const bg = isGoal ? "rgba(16, 185, 129, 0.35)" : "rgba(239, 68, 68, 0.35)";
      drawTileHighlight(board, cell, bg, color);
      drawGhostMarker(board, cell, color);
    } else {
      drawTileHighlight(board, cell, "rgba(255, 255, 255, 0.25)", "#00ffff");
      drawGhostMarker(board, cell, "#94a3b8");
    }
  }
  if (currentPacmanCell) drawPacmanMarker(board, currentPacmanCell);
}

let audioCtx = null;
function getAudioContext() {
  if (audioCtx) return audioCtx;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  audioCtx = new Ctx();
  return audioCtx;
}

function playCorrectSound() {
  const ac = getAudioContext();
  if (!ac) return;
  try {
    ac.resume();
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.connect(gain);
    gain.connect(ac.destination);
    osc.type = "square";
    osc.frequency.setValueAtTime(680, ac.currentTime);
    gain.gain.setValueAtTime(0.12, ac.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ac.currentTime + 0.15);
    osc.start(ac.currentTime);
    osc.stop(ac.currentTime + 0.15);
  } catch (_) {}
}

function playWrongSound() {
  const ac = getAudioContext();
  if (!ac) return;
  try {
    ac.resume();
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.connect(gain);
    gain.connect(ac.destination);
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(220, ac.currentTime);
    osc.frequency.exponentialRampToValueAtTime(110, ac.currentTime + 0.2);
    gain.gain.setValueAtTime(0.12, ac.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ac.currentTime + 0.2);
    osc.start(ac.currentTime);
    osc.stop(ac.currentTime + 0.2);
  } catch (_) {}
}

function playWinFanfare() {
  const ac = getAudioContext();
  if (!ac) return;
  try {
    ac.resume();
    [523, 659, 784, 1047].forEach((freq, i) => {
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.connect(gain);
      gain.connect(ac.destination);
      osc.type = "square";
      const t0 = ac.currentTime + i * 0.11;
      osc.frequency.setValueAtTime(freq, t0);
      gain.gain.setValueAtTime(0.1, t0);
      gain.gain.exponentialRampToValueAtTime(0.01, t0 + 0.25);
      osc.start(t0);
      osc.stop(t0 + 0.25);
    });
  } catch (_) {}
}

function manhattan(a, b) {
  return Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]);
}

function bfsDistances(b, start) {
  const dist = new Map();
  const startKey = `${start[0]},${start[1]}`;
  dist.set(startKey, 0);
  const queue = [start];
  let qi = 0;
  while (qi < queue.length) {
    const [r, c] = queue[qi++];
    const d = dist.get(`${r},${c}`);
    for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
      const nr = r + dr;
      const nc = c + dc;
      if (isWallAt(b, nr, nc)) continue;
      const key = `${nr},${nc}`;
      if (!dist.has(key)) {
        dist.set(key, d + 1);
        queue.push([nr, nc]);
      }
    }
  }
  return dist;
}

function bfsPath(b, start, goal) {
  const startKey = `${start[0]},${start[1]}`;
  const goalKey = `${goal[0]},${goal[1]}`;
  const parent = new Map();
  const visited = new Set([startKey]);
  const queue = [start];
  let qi = 0;
  while (qi < queue.length) {
    const [r, c] = queue[qi++];
    const key = `${r},${c}`;
    if (key === goalKey) break;
    for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
      const nr = r + dr;
      const nc = c + dc;
      if (isWallAt(b, nr, nc)) continue;
      const nkey = `${nr},${nc}`;
      if (!visited.has(nkey)) {
        visited.add(nkey);
        parent.set(nkey, key);
        queue.push([nr, nc]);
      }
    }
  }
  if (!visited.has(goalKey)) return null;
  const path = [goal];
  let curKey = goalKey;
  while (curKey !== startKey) {
    const pKey = parent.get(curKey);
    const [pr, pc] = pKey.split(",").map(Number);
    path.push([pr, pc]);
    curKey = pKey;
  }
  path.reverse();
  return path;
}

function randomWalkPath(b, start, goal) {
  const goalKey = `${goal[0]},${goal[1]}`;
  const visited = new Set([`${start[0]},${start[1]}`]);
  const path = [start];
  const maxSteps = b.rows * b.cols * 6;
  let steps = 0;

  while (`${path[path.length - 1][0]},${path[path.length - 1][1]}` !== goalKey) {
    steps++;
    if (steps > maxSteps) return null;
    const [r, c] = path[path.length - 1];
    const neighbors = [[-1, 0], [1, 0], [0, -1], [0, 1]]
      .map(([dr, dc]) => [r + dr, c + dc])
      .filter(([nr, nc]) => !isWallAt(b, nr, nc));
    for (let i = neighbors.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [neighbors[i], neighbors[j]] = [neighbors[j], neighbors[i]];
    }
    let next = neighbors.find((n) => !visited.has(`${n[0]},${n[1]}`));
    if (!next) {
      if (path.length <= 1) return null;
      path.pop();
      continue;
    }
    visited.add(`${next[0]},${next[1]}`);
    path.push(next);
  }
  return path;
}

function pathSignature(path) {
  return path.map((c) => c.join(",")).join("|");
}

function buildPathOptions() {
  if (!correctPath) return [];
  const optimalLen = correctPath.length;
  const signatures = new Set([pathSignature(correctPath)]);
  const decoys = [];

  const tryCollect = (minExtra, attempts) => {
    let guard = 0;
    while (decoys.length < 3 && guard < attempts) {
      guard++;
      const p = randomWalkPath(board, puzzleStart, puzzleGoal);
      if (!p) continue;
      if (p.length < optimalLen + minExtra) continue;
      const sig = pathSignature(p);
      if (signatures.has(sig)) continue;
      signatures.add(sig);
      decoys.push(p);
    }
  };

  tryCollect(2, 150);
  tryCollect(0, 150);

  const all = [
    { path: correctPath, correct: true },
    ...decoys.map((p) => ({ path: p, correct: false })),
  ];
  for (let i = all.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [all[i], all[j]] = [all[j], all[i]];
  }
  return all.map((o, i) => ({ ...o, letter: OPTION_LETTERS[i] || String(i + 1) }));
}

function deriveStartGoal(trace) {
  const introStep = trace[0] || {};
  const inputs = introStep.inputs || introStep;
  let start = inputs.start || introStep.start || null;
  let goal = inputs.goal || introStep.goal || null;
  if (!start) {
    const firstCheckpoint = trace.find((s) => s.type === "checkpoint");
    if (firstCheckpoint && firstCheckpoint.state) {
      if (firstCheckpoint.state.current) start = firstCheckpoint.state.current;
      else if (firstCheckpoint.state.current_r !== undefined) start = [firstCheckpoint.state.current_r, firstCheckpoint.state.current_c];
    }
  }
  if (!goal) {
    const doneStep = trace.find((s) => s.type === "done");
    if (doneStep && doneStep.state && doneStep.state.path && doneStep.state.path.length) {
      goal = doneStep.state.path[doneStep.state.path.length - 1];
    }
  }
  return { start, goal };
}

const params = new URLSearchParams(window.location.search);
const TRACE_FILE_PATH = params.get("trace") || "pacman_a_star_trace.json";

const lessonTitleEl = document.getElementById("lessonTitle");
const stepNumEl = document.getElementById("stepNum");
const stepTotalEl = document.getElementById("stepTotal");
const restartBtn = document.getElementById("restartBtn");
const panelTitleEl = document.getElementById("panelTitle");
const panelBodyEl = document.getElementById("panelBody");
const actionBtn = document.getElementById("actionBtn");
const hintTextEl = document.getElementById("hintText");
const optionsPanelEl = document.getElementById("optionsPanel");
const overlayEl = document.getElementById("overlayScreen");

let traceData = [];
let stepIndex = 0;
let awaitingAnswer = false;
let puzzleStart = null;
let puzzleGoal = null;
let correctPath = null;
let currentPacmanCell = null;
let currentQuestionOptions = [];

async function loadTrace() {
  if (panelTitleEl) panelTitleEl.textContent = "Loading lesson…";
  hideOverlay();
  try {
    const response = await fetch(TRACE_FILE_PATH);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    traceData = await response.json();

    board = buildBoard(traceData);
    sizeCanvasToBoard(board);

    const { start, goal } = deriveStartGoal(traceData);
    puzzleStart = start;
    puzzleGoal = goal;
    correctPath = start && goal ? bfsPath(board, start, goal) : null;
    currentPacmanCell = start;

    stepIndex = 0;
    renderStep();
  } catch (error) {
    console.error("Failed to load algorithm trace:", error);
    if (panelTitleEl) panelTitleEl.textContent = "Couldn't load this lesson";
    if (panelBodyEl) panelBodyEl.textContent = `Could not fetch ${TRACE_FILE_PATH}.`;
  }
}

function hideOverlay() {
  if (!overlayEl) return;
  overlayEl.className = "overlay-screen hidden";
  overlayEl.innerHTML = "";
}

function showOverlay(kind, html) {
  if (!overlayEl) return;
  overlayEl.className = `overlay-screen ${kind}`;
  overlayEl.innerHTML = html;
  const btn = overlayEl.querySelector("button");
  if (btn) btn.addEventListener("click", resetLesson);
}

const OPTION_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H"];

function previewPath(path) {
  drawStaticFrame(() => drawFinalPath(board, path));
}

function renderPathOptionsPanel(options) {
  if (!optionsPanelEl) return;
  optionsPanelEl.innerHTML = "";
  options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.className = "option-card";
    btn.innerHTML = `
      <span class="option-letter">${opt.letter}</span>
      <span class="option-coord">${opt.path.length - 1} moves</span>
    `;
    btn.addEventListener("mouseenter", () => previewPath(opt.path));
    btn.addEventListener("mouseleave", () => drawStaticFrame());
    btn.addEventListener("focus", () => previewPath(opt.path));
    btn.addEventListener("blur", () => drawStaticFrame());
    btn.addEventListener("click", () => handlePathPick(opt, btn));
    optionsPanelEl.appendChild(btn);
  });
}

function renderStep() {
  const introStep = traceData[0] || {};
  if (actionBtn) actionBtn.style.display = "none";
  awaitingAnswer = false;
  if (optionsPanelEl) optionsPanelEl.innerHTML = "";
  hideOverlay();
  currentPacmanCell = puzzleStart;

  if (lessonTitleEl) lessonTitleEl.textContent = introStep.algorithmName || "A* Search";
  if (panelTitleEl) panelTitleEl.textContent = introStep.algorithmName || "A* Search";
  if (panelBodyEl) panelBodyEl.innerHTML = `${introStep.rules || ""}<br><br><em>${introStep.instructions || ""}</em>`;
  if (stepNumEl) stepNumEl.textContent = "0";
  if (stepTotalEl) stepTotalEl.textContent = "1";
  if (hintTextEl) hintTextEl.textContent = "Read the rules, then start the lesson.";

  if (actionBtn) {
    actionBtn.textContent = "Start lesson";
    actionBtn.style.display = "inline-block";
    actionBtn.onclick = startQuestion;
  }

  drawStaticFrame();
}

function startQuestion() {
  if (actionBtn) actionBtn.style.display = "none";
  if (stepNumEl) stepNumEl.textContent = "1";
  if (panelTitleEl) panelTitleEl.textContent = "Which path leads Pac-Man to the cherry?";
  if (panelBodyEl) panelBodyEl.textContent = "Hover an option to preview its route on the maze, then pick a path.";
  if (hintTextEl) hintTextEl.textContent = "Hover each option to trace it on the board -- only one is the shortest route.";

  currentQuestionOptions = buildPathOptions();
  awaitingAnswer = true;
  drawStaticFrame();
  renderPathOptionsPanel(currentQuestionOptions);
}

function animatePacman(fromCell, toCell, durationMs, onDone) {
  const start = performance.now();
  function frame(now) {
    const t = Math.min(1, (now - start) / durationMs);
    const [flr, flc] = toLocal(board, fromCell);
    const [tlr, tlc] = toLocal(board, toCell);
    const lr = flr + (tlr - flr) * t;
    const lc = flc + (tlc - flc) * t;
    const tile = board.tileSize;

    if (canvas && ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      drawMazeBackground(board);
      if (puzzleStart) drawStartMarker(board, puzzleStart);
      if (puzzleGoal) drawCherry(board, puzzleGoal);
      drawPacmanAtPixel(lc * tile + tile / 2, lr * tile + tile / 2, tile * 0.4, t * 4);
    }

    if (t < 1) {
      requestAnimationFrame(frame);
    } else {
      onDone();
    }
  }
  requestAnimationFrame(frame);
}

function animatePathSequential(path, stepMs, onDone) {
  let i = 0;
  function nextHop() {
    if (i >= path.length - 1) {
      onDone();
      return;
    }
    animatePacman(path[i], path[i + 1], stepMs, () => {
      i++;
      nextHop();
    });
  }
  nextHop();
}

function handlePathPick(opt, btnEl) {
  if (!awaitingAnswer) return;

  if (opt.correct) {
    awaitingAnswer = false;
    if (optionsPanelEl) {
      const buttons = optionsPanelEl.querySelectorAll(".option-card");
      buttons.forEach((b) => (b.disabled = true));
    }
    if (btnEl) btnEl.classList.add("correct");
    playCorrectSound();
    if (panelBodyEl) panelBodyEl.textContent = "Correct! That's the shortest route -- watch Pac-Man go.";
    if (hintTextEl) hintTextEl.textContent = "Nice pick -- that's the optimal path.";

    animatePathSequential(opt.path, 260, () => {
      currentPacmanCell = opt.path[opt.path.length - 1];
      drawStaticFrame(() => drawFinalPath(board, opt.path));
      playWinFanfare();
      setTimeout(() => {
        showOverlay(
          "win",
          `<div class="overlay-card">
            <div class="overlay-icon">🍒</div>
            <h2>You win!</h2>
            <p>Pac-Man reached the cherry in ${opt.path.length - 1} moves -- the shortest possible route.</p>
            <button>Play again 🔁</button>
          </div>`
        );
      }, 250);
    });
    return;
  }

  if (btnEl) btnEl.classList.add("wrong");
  playWrongSound();
  if (panelBodyEl) panelBodyEl.textContent = "Try again -- that route is longer than the shortest path to the cherry.";
  if (hintTextEl) hintTextEl.textContent = "Try again -- hover the options to compare routes, then pick the shortest.";
  setTimeout(() => { if (btnEl) btnEl.classList.remove("wrong"); }, 500);
  drawStaticFrame();
}

function resetLesson() {
  stepIndex = 0;
  currentPacmanCell = puzzleStart;
  hideOverlay();
  renderStep();
}

if (restartBtn) restartBtn.addEventListener("click", resetLesson);

if (lessonTitleEl) {
  loadTrace();
}

window.setupScene = function (introStep) {
  activeMarker = null;
  canvas = document.getElementById("scene-canvas") || document.getElementById("gameCanvas");
  if (canvas) {
    ctx = canvas.getContext("2d");
  }

  const inputs = (introStep && introStep.inputs) ? introStep.inputs : (introStep || {});
  let rawLayout = inputs.grid || inputs.levelLayout || introStep.grid || introStep.levelLayout || DEFAULT_LEVEL_LAYOUT;
  if (Array.isArray(rawLayout)) {
    rawLayout = rawLayout.map((row) => (Array.isArray(row) ? row.join("") : String(row)));
  } else {
    rawLayout = DEFAULT_LEVEL_LAYOUT;
  }

  puzzleStart = inputs.start || introStep.start || [1, 1];
  puzzleGoal = inputs.goal || introStep.goal || [1, 1];
  currentPacmanCell = puzzleStart;

  board = sliceBoard(rawLayout, 0, rawLayout.length - 1, 0, rawLayout[0].length - 1);
  sizeCanvasToBoard(board);
  drawStaticFrame();
};

window.showStepMarker = function (state) {
  if (!state) return;
  const r = state.current_r !== undefined ? state.current_r : (state.current ? state.current[0] : 0);
  const c = state.current_c !== undefined ? state.current_c : (state.current ? state.current[1] : 0);
  activeMarker = {
    cell: [r, c],
    state: state,
    revealed: false,
  };
  drawStaticFrame();
};

window.revealStepMarker = function (state) {
  if (!state) return;
  const r = state.current_r !== undefined ? state.current_r : (state.current ? state.current[0] : 0);
  const c = state.current_c !== undefined ? state.current_c : (state.current ? state.current[1] : 0);
  activeMarker = {
    cell: [r, c],
    state: state,
    revealed: true,
  };
  drawStaticFrame();
};

window.clearStepMarker = function () {
  activeMarker = null;
  drawStaticFrame();
};

window.playResolutionAnimation = function (doneState, onComplete) {
  activeMarker = null;
  const path = doneState && doneState.path ? doneState.path : [];
  if (path.length > 0) {
    animatePathSequential(path, 200, () => {
      currentPacmanCell = path[path.length - 1];
      drawStaticFrame(() => drawFinalPath(board, path));
      playWinFanfare();
      if (typeof onComplete === "function") onComplete();
    });
  } else {
    drawStaticFrame();
    if (typeof onComplete === "function") onComplete();
  }
};