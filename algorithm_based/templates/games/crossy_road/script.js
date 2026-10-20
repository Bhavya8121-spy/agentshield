const counterDOM = document.getElementById("counter");

const scene = new THREE.Scene();

let isGamePausedForLesson = true; // true whenever the 3D scene should hold still

const ALGORITHM_MANIFEST_URL = "index.json";
const LEADERBOARD_KEY_PREFIX = "crossyQuizLeaderboard";
const DEFAULT_QUESTION_TIME_LIMIT_MS = 15000; // used only if an algorithm's JSON omits it
const DEFAULT_POINTS_PER_CORRECT = 100;
const DEFAULT_POINTS_PER_LEFTOVER_SECOND = 5;


let algorithmManifest = []; // [{ id, file }]
let currentAlgorithm = null; // the fully-loaded JSON for the lesson in progress

function getTotalQuestions() {
  return currentAlgorithm ? currentAlgorithm.questions.length : 0;
}

function getQuestionTimeLimitMs() {
  return (currentAlgorithm && currentAlgorithm.gameplayRules && currentAlgorithm.gameplayRules.questionTimeLimitMs)
    || DEFAULT_QUESTION_TIME_LIMIT_MS;
}

function getPointsPerCorrect() {
  return (currentAlgorithm && currentAlgorithm.gameplayRules && currentAlgorithm.gameplayRules.pointsPerCorrectAnswer)
    ?? DEFAULT_POINTS_PER_CORRECT;
}

function getPointsPerLeftoverSecond() {
  return (currentAlgorithm && currentAlgorithm.gameplayRules && currentAlgorithm.gameplayRules.pointsPerLeftoverSecond)
    ?? DEFAULT_POINTS_PER_LEFTOVER_SECOND;
}

function getLeaderboardKey() {
  return `${LEADERBOARD_KEY_PREFIX}:${currentAlgorithm ? currentAlgorithm.id : "unknown"}`;
}

async function loadAlgorithmManifest() {
  const listEl = document.getElementById("algorithmList");
  try {
    const res = await fetch(ALGORITHM_MANIFEST_URL);
    if (!res.ok) throw new Error(`Manifest request failed: ${res.status}`);
    const manifest = await res.json();
    algorithmManifest = manifest.algorithms || [];
    await renderAlgorithmSelect();
  } catch (err) {
    console.error("Failed to load algorithm manifest:", err);
    listEl.innerHTML = `<p class="algorithm-list-error">Couldn't load the lesson list (${err.message}). If you're opening this file directly, try serving it from a local web server instead.</p>`;
  }
}

async function renderAlgorithmSelect() {
  const listEl = document.getElementById("algorithmList");
  listEl.innerHTML = "";

  // Fetch each algorithm's metadata (title/description/question count) up
  // front so the picker can show useful info before the player commits.
  const summaries = await Promise.all(
    algorithmManifest.map(async (entry) => {
      try {
        const res = await fetch(`${entry.file}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const data = await res.json();
        return { entry, data };
      } catch (err) {
        console.error(`Failed to load algorithm "${entry.id}":`, err);
        return { entry, data: null };
      }
    })
  );

  summaries.forEach(({ entry, data }) => {
    if (!data) return; // skip lessons that failed to load rather than breaking the whole picker
    const card = document.createElement("button");
    card.className = "algorithm-card";
    card.innerHTML = `
      <span class="algorithm-card-title">${data.title}</span>
      <span class="algorithm-card-desc">${data.description}</span>
      <span class="algorithm-card-meta">${data.questions.length} roads &middot; ${Math.round((data.gameplayRules?.questionTimeLimitMs ?? DEFAULT_QUESTION_TIME_LIMIT_MS) / 1000)}s per question</span>
    `;
    card.addEventListener("click", () => selectAlgorithm(entry.id, data));
    listEl.appendChild(card);
  });

  if (!listEl.children.length) {
    listEl.innerHTML = `<p class="algorithm-list-error">No lessons could be loaded.</p>`;
  }
}

function selectAlgorithm(id, data) {
  currentAlgorithm = data;
  document.getElementById("algorithmSelectScreen").classList.add("hidden");
  showRulesForCurrentAlgorithm();
}

function showRulesForCurrentAlgorithm() {
  document.getElementById("rulesTimeLimit").textContent =
    `${Math.round(getQuestionTimeLimitMs() / 1000)} seconds`;
  document.getElementById("rulesQuestionCount").textContent = getTotalQuestions();
  startRulesCountdown();
}

let username = "";
let currentQuestionIndex = 0;
let correctCount = 0;
let timeBonusSeconds = 0; // sum of leftover seconds across correct answers
let questionTimerInterval = null;
let questionDeadline = 0;
let answerLocked = false;


let memoryLeaderboard = [];

function loadLeaderboard() {
  try {
    const raw = localStorage.getItem(getLeaderboardKey());
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return memoryLeaderboard;
  }
}

function saveLeaderboard(list) {
  try {
    localStorage.setItem(getLeaderboardKey(), JSON.stringify(list));
  } catch (e) {
    memoryLeaderboard = list;
  }
}

function addLeaderboardEntry(name, score, roadsCrossed) {
  const list = loadLeaderboard();
  const entry = { name, score, roadsCrossed, ts: Date.now() };
  list.push(entry);
  list.sort((a, b) => b.score - a.score);
  const trimmed = list.slice(0, 10);
  saveLeaderboard(trimmed);
  return { list: trimmed, entry };
}

function computeScore() {
  return correctCount * getPointsPerCorrect() + timeBonusSeconds * getPointsPerLeftoverSecond();
}


function generateLesson(config, roadNumber) {
  document.getElementById("lessonTitle").innerHTML = `Road ${roadNumber}: ${config.shortTitle}`;
  document.getElementById("lessonDescription").innerHTML = config.description;

  const optionsContainer = document.getElementById("lessonOptions");
  optionsContainer.innerHTML = "";
  config.options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.textContent = opt.label;
    btn.addEventListener("click", () => submitAnswer(opt.id, btn));
    optionsContainer.appendChild(btn);
  });
}

function showQuestion(index) {
  answerLocked = false;
  const config = currentAlgorithm.questions[index];
  generateLesson(config, index + 1);
  document.getElementById("lessonProgress").textContent =
    `ROAD ${index + 1} / ${getTotalQuestions()}  ·  SCORE ${computeScore()}`;
  document.getElementById("quizFeedback").innerHTML = "";
  document.getElementById("winAnimation").classList.add("hidden");
  document.getElementById("startupLesson").classList.remove("hidden");
  startQuestionTimer();
}

function startQuestionTimer() {
  clearInterval(questionTimerInterval);
  const timeLimitMs = getQuestionTimeLimitMs();
  questionDeadline = Date.now() + timeLimitMs;
  const fill = document.getElementById("timerBarFill");
  fill.classList.remove("timer-warning", "timer-danger");
  fill.style.width = "100%";

  questionTimerInterval = setInterval(() => {
    const remaining = questionDeadline - Date.now();
    const fraction = Math.max(remaining, 0) / timeLimitMs;
    fill.style.width = fraction * 100 + "%";
    fill.classList.toggle("timer-warning", fraction <= 0.5 && fraction > 0.25);
    fill.classList.toggle("timer-danger", fraction <= 0.25);

    if (remaining <= 0) {
      clearInterval(questionTimerInterval);
      submitAnswer("__TIMEOUT__", null);
    }
  }, 100);
}


function submitAnswer(choiceId, btnEl) {
  if (answerLocked) return;
  answerLocked = true;
  clearInterval(questionTimerInterval);

  const config = currentAlgorithm.questions[currentQuestionIndex];
  const feedback = document.getElementById("quizFeedback");
  document.querySelectorAll("#lessonOptions button").forEach((b) => b.classList.add("disabled-option"));

  if (choiceId === "__TIMEOUT__") {
    feedback.style.color = "#ef4444";
    feedback.innerHTML = "⏰ Time's up! You didn't answer in time, so the road wasn't crossed safely.";
    setTimeout(() => {
      forceCrossIntoTraffic(() => triggerCrash(config, null));
    }, 900);
    return;
  }

  const opt = config.options.find((o) => o.id === choiceId);
  if (!opt) return;

  if (btnEl) btnEl.classList.add(opt.correct ? "correct-flash" : "wrong-flash");

  if (opt.correct) {
    feedback.style.color = "#10b981";
    feedback.innerHTML = opt.explanation;

    const secondsLeft = Math.max(0, Math.round((questionDeadline - Date.now()) / 1000));
    timeBonusSeconds += secondsLeft;
    correctCount++;

    const winAnimation = document.getElementById("winAnimation");
    winAnimation.classList.remove("hidden");

    setTimeout(() => {
      smartCrossToCheckpoint(() => {
        currentQuestionIndex++;
        if (currentQuestionIndex >= getTotalQuestions()) {
          triggerWin();
        } else {
          showQuestion(currentQuestionIndex);
        }
      });
    }, 900);
  } else {
    feedback.style.color = "#ef4444";
    feedback.innerHTML = opt.explanation;

    setTimeout(() => {
      forceCrossIntoTraffic(() => triggerCrash(config, opt));
    }, 900);
  }
}


function findSafePathToLane(targetLaneIdx) {
  const startKey = `${currentLane},${currentColumn},0`;
  const visited = new Set([startKey]);
  const queue = [{ lane: currentLane, column: currentColumn, ticks: 0, path: [] }];
  let qi = 0;

  const candidateMoves = [
    { dir: "forward", dLane: 1, dCol: 0 },
    { dir: "right", dLane: 0, dCol: 1 },
    { dir: "left", dLane: 0, dCol: -1 },
    { dir: "wait", dLane: 0, dCol: 0 },
  ];

  while (qi < queue.length) {
    const state = queue[qi++];
    
    if (state.lane === targetLaneIdx) return state.path; 
    
    // INCREASED to 60: gives the AI plenty of time to wait for slow trucks to pass
    if (state.ticks >= 60) continue; 

    for (const mv of candidateMoves) {
      const nLane = state.lane + mv.dLane;
      const nCol = state.column + mv.dCol;
      
      if (nLane < 0 || nLane >= lanes.length) continue;
      if (nCol < 0 || nCol >= columns) continue;

      const targetLane = lanes[nLane];
      const arrivalTicks = state.ticks + 1;
      
      // Strict anti-clipping checks
      if (!isColumnSafeAtTime(targetLane, nCol, arrivalTicks * stepTime)) continue;
      if (!isColumnSafeAtTime(targetLane, nCol, (arrivalTicks - 0.5) * stepTime)) continue;

      const key = `${nLane},${nCol},${arrivalTicks}`;
      if (visited.has(key)) continue;
      visited.add(key);
      
      queue.push({ lane: nLane, column: nCol, ticks: arrivalTicks, path: [...state.path, mv.dir] });
    }
  }
  return null;
}

// Executes the crossing
function smartCrossToCheckpoint(onArrive) {
  document.getElementById("startupLesson").classList.add("hidden");
  isGamePausedForLesson = false;
  previousTimestamp = null;

  const targetLaneIndex = checkpoints[currentQuestionIndex]; 
  const path = findSafePathToLane(targetLaneIndex); 
  
  if (path && path.length > 0) {
    moves.push(...path);
    if (!stepStartTimestamp) startMoving = true;
  } else {
    const remainingLanes = targetLaneIndex - currentLane;
    const directMoves = Array(Math.max(1, remainingLanes)).fill("forward");
    moves.push(...directMoves);
    if (!stepStartTimestamp) startMoving = true;
  }

  function pollForArrival() {
    if (moves.length === 0 && !stepStartTimestamp) {
      // NEW: The chicken has arrived! Wait 1.2 seconds before loading the next question.
      setTimeout(() => {
        isGamePausedForLesson = true;
        onArrive();
      }, 1200);
      
      return; // Stops the polling loop
    }
    requestAnimationFrame(pollForArrival);
  }
  
  requestAnimationFrame(pollForArrival);
}

// WRONG ANSWER / TIMEOUT: AI is forced onto the road; we poll every frame
// for a real collision and only call onArrive() once the bird is actually hit
// (falling back to a timeout so the game can never hang if no hit registers).
// A collision check that looks at the CURRENT lane and requires a slight physical overlap
function isChickenHitRightNow() {
  const lane = lanes[currentLane];
  if (!lane || (lane.type !== "car" && lane.type !== "truck")) return false;
  
  const chickenHalf = (chickenSize * zoom) / 2;
  const vehicleHalfLength = (laneVehicleLength(lane) * zoom) / 2;
  
  return lane.vechicles.some(
    // Subtracting a few pixels (4 * zoom) ensures the car actually crunches into the bird visually
    (v) => Math.abs(v.position.x - chicken.position.x) < (vehicleHalfLength + chickenHalf - (4 * zoom))
  );
}

function forceCrossIntoTraffic(onArrive) {
  document.getElementById("startupLesson").classList.add("hidden");
  isGamePausedForLesson = false;
  previousTimestamp = null;

  const collisionPath = findCollisionPath();
  
  if (collisionPath && collisionPath.length > 0) {
    moves.push(...collisionPath);
    if (!stepStartTimestamp) startMoving = true;
  } else {
    moves.push("forward", "forward");
    if (!stepStartTimestamp) startMoving = true;
  }

  function pollForImpact() {
    if (isChickenHitRightNow()) {
      isGamePausedForLesson = true;
      onArrive();
      return;
    }
    
    if (moves.length === 0 && !stepStartTimestamp) {
        isGamePausedForLesson = true;
        onArrive();
        return;
    }

    requestAnimationFrame(pollForImpact);
  }

  requestAnimationFrame(pollForImpact);
}

// Inverts the BFS: looks for a path that ENDS in an occupied coordinate
function findCollisionPath() {
  const startKey = `${currentLane},${currentColumn},0`;
  const visited = new Set([startKey]);
  const queue = [{ lane: currentLane, column: currentColumn, ticks: 0, path: [] }];
  let qi = 0;

  const candidateMoves = [
    { dir: "forward", dLane: 1, dCol: 0 },
    { dir: "wait", dLane: 0, dCol: 0 },
    { dir: "left", dLane: 0, dCol: -1 },
    { dir: "right", dLane: 0, dCol: 1 },
  ];

  while (qi < queue.length) {
    const state = queue[qi++];
    
    // If this state puts the chicken inside a car, this is the golden path
    const laneObj = lanes[state.lane];
    if (state.ticks > 0 && !isColumnSafeAtTime(laneObj, state.column, state.ticks * stepTime)) {
        return state.path; 
    }

    if (state.ticks >= 8) continue; // Don't look too far, grab nearest car

    for (const mv of candidateMoves) {
      const nLane = state.lane + mv.dLane;
      const nCol = state.column + mv.dCol;
      
      if (nLane < 0 || nLane >= lanes.length) continue;
      if (nCol < 0 || nCol >= columns) continue;

      const arrivalTicks = state.ticks + 1;
      const key = `${nLane},${nCol},${arrivalTicks}`;
      
      if (visited.has(key)) continue;
      visited.add(key);
      queue.push({ lane: nLane, column: nCol, ticks: arrivalTicks, path: [...state.path, mv.dir] });
    }
  }
  return null;
}

function triggerCrash(config, chosenOpt) {
  document.body.classList.add("impact-flash");
  setTimeout(() => document.body.classList.remove("impact-flash"), 400);

  const score = computeScore();
  const roadLabel = `Road ${currentQuestionIndex + 1}: ${config.shortTitle}`;
  document.getElementById("crashExplanation").textContent =
    chosenOpt
      ? `You picked "${chosenOpt.label.replace(/^[A-D]\)\s*/, "")}" on "${roadLabel}" -- that wasn't the right call.`
      : `You ran out of time on "${roadLabel}".`;
  document.getElementById("crashRoads").textContent = `${currentQuestionIndex} / ${getTotalQuestions()}`;
  document.getElementById("crashScore").textContent = score;

  addLeaderboardEntry(username, score, currentQuestionIndex);
  document.getElementById("crashScreen").classList.remove("hidden");
}

function launchConfetti(fieldId) {
  const field = document.getElementById(fieldId);
  field.innerHTML = "";
  const colors = ["#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];
  for (let i = 0; i < 80; i++) {
    const piece = document.createElement("div");
    piece.className = "confetti-piece";
    piece.style.left = Math.random() * 100 + "%";
    piece.style.background = colors[i % colors.length];
    piece.style.animationDuration = 1.5 + Math.random() * 1.5 + "s";
    piece.style.animationDelay = Math.random() * 0.3 + "s";
    field.appendChild(piece);
  }
}

function triggerWin() {
  const winScreen = document.getElementById("winScreen");
  winScreen.classList.remove("hidden");
  launchConfetti("winConfettiField");

  const score = computeScore();
  setTimeout(() => {
    winScreen.classList.add("hidden");
    addLeaderboardEntry(username, score, getTotalQuestions());
    showScoreboard(score, true);
  }, 3000);
}

function showScoreboard(finalScore, wasWin) {
  const list = loadLeaderboard();
  document.getElementById("scoreboardYourResult").textContent = wasWin
    ? `🏁 ${username}, you made it home and mastered "${currentAlgorithm.title}"! Score: ${finalScore}`
    : `${username}, your score on "${currentAlgorithm.title}" this run: ${finalScore}`;

  const listEl = document.getElementById("scoreboardList");
  listEl.innerHTML = "";
  const totalQuestions = getTotalQuestions();
  list.forEach((entry) => {
    const li = document.createElement("li");
    const isThisRun = entry.name === username && entry.score === finalScore;
    if (isThisRun) li.classList.add("you");
    li.innerHTML = `<span>${entry.name}</span><span>${entry.score} pts (${entry.roadsCrossed}/${totalQuestions})</span>`;
    listEl.appendChild(li);
  });

  document.getElementById("crashScreen").classList.add("hidden");
  document.getElementById("scoreboardScreen").classList.remove("hidden");
}

// ----------------------------------------------------------------------------
// Run lifecycle: starting, retrying, and resetting the 3D scene between runs
// ----------------------------------------------------------------------------
function resetRunState() {
  currentQuestionIndex = 0;
  correctCount = 0;
  timeBonusSeconds = 0;
  answerLocked = false;
  
  if (lanes) {
    lanes.forEach((lane) => scene.remove(lane.mesh));
  }
  
  initaliseValues(); 
  
  checkpoints = [];
  const totalQuestions = getTotalQuestions();

  for (let q = 0; q < totalQuestions; q++) {
    // 1. Add traffic lanes
    const lanesToCross = Math.floor(Math.random() * 3) + 2; 
    for (let i = 0; i < lanesToCross; i++) {
      const index = lanes.length;
      const forcedType = Math.random() < 0.5 ? "car" : "truck";
      const lane = new Lane(index, forcedType);
      lane.mesh.position.y = index * positionWidth * zoom;
      scene.add(lane.mesh);
      lanes.push(lane);
    }
    
    // 2. Add the grassland checkpoint
    const safeIndex = lanes.length;
    const safeLane = new Lane(safeIndex, "field");
    safeLane.mesh.position.y = safeIndex * positionWidth * zoom;
    
    // NEW: Add a flag to the right side of the checkpoint
    const flag = new Flag();
    flag.position.x = (boardWidth * zoom) / 2 - (positionWidth * 2) * zoom;
    safeLane.mesh.add(flag);

    scene.add(safeLane.mesh);
    lanes.push(safeLane);
    checkpoints.push(safeIndex);
  }

  for (let i = 0; i < 8; i++) {
    const padIndex = lanes.length;
    const padLane = new Lane(padIndex, "forest"); 
    padLane.mesh.position.y = padIndex * positionWidth * zoom;
    scene.add(padLane.mesh);
    lanes.push(padLane);
  }
}

function beginRun() {
  resetRunState();
  document.getElementById("crashScreen").classList.add("hidden");
  document.getElementById("scoreboardScreen").classList.add("hidden");
  showQuestion(0);
}

function startRulesCountdown() {
  const rulesScreen = document.getElementById("rulesScreen");
  const countdownText = document.getElementById("rulesCountdownText");
  rulesScreen.classList.remove("hidden");

  let secondsLeft = 5;
  countdownText.textContent = `Starting in ${secondsLeft}…`;
  const rulesInterval = setInterval(() => {
    secondsLeft--;
    if (secondsLeft <= 0) {
      clearInterval(rulesInterval);
      rulesScreen.classList.add("hidden");
      beginRun();
    } else {
      countdownText.textContent = `Starting in ${secondsLeft}…`;
    }
  }, 1000);
}

// ----------------------------------------------------------------------------
// Static UI wiring (runs once at load; the elements already exist since this
// script tag is at the end of <body>)
// ----------------------------------------------------------------------------
const usernameInput = document.getElementById("usernameInput");
const usernameStartBtn = document.getElementById("usernameStartBtn");

usernameInput.addEventListener("input", () => {
  usernameStartBtn.disabled = usernameInput.value.trim().length === 0;
});
usernameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !usernameStartBtn.disabled) usernameStartBtn.click();
});
usernameStartBtn.addEventListener("click", () => {
  username = usernameInput.value.trim().slice(0, 18) || "Player";
  document.getElementById("usernameScreen").classList.add("hidden");
  document.getElementById("algorithmSelectScreen").classList.remove("hidden");
});

function goToAlgorithmSelect() {
  document.getElementById("crashScreen").classList.add("hidden");
  document.getElementById("scoreboardScreen").classList.add("hidden");
  document.getElementById("algorithmSelectScreen").classList.remove("hidden");
}

document.getElementById("retryBtn").addEventListener("click", beginRun);
document.getElementById("playAgainBtn").addEventListener("click", beginRun);
document.getElementById("chooseAnotherBtn").addEventListener("click", goToAlgorithmSelect);
document.getElementById("crashChooseAnotherBtn").addEventListener("click", goToAlgorithmSelect);
document.getElementById("newPlayerBtn").addEventListener("click", () => {
  document.getElementById("scoreboardScreen").classList.add("hidden");
  usernameInput.value = "";
  usernameStartBtn.disabled = true;
  document.getElementById("usernameScreen").classList.remove("hidden");
});

// Kick off the manifest fetch as soon as the page loads so the algorithm
// picker is already populated by the time the player reaches it.
loadAlgorithmManifest();

const distance = 500;
const camera = new THREE.OrthographicCamera(
  window.innerWidth / -2,
  window.innerWidth / 2,
  window.innerHeight / 2,
  window.innerHeight / -2,
  0.1,
  10000
);

camera.rotation.x = (50 * Math.PI) / 180;
camera.rotation.y = (20 * Math.PI) / 180;
camera.rotation.z = (10 * Math.PI) / 180;

const initialCameraPositionY = -Math.tan(camera.rotation.x) * distance;
const initialCameraPositionX =
  Math.tan(camera.rotation.y) *
  Math.sqrt(distance ** 2 + initialCameraPositionY ** 2);
camera.position.y = initialCameraPositionY;
camera.position.x = initialCameraPositionX;
camera.position.z = distance;

const zoom = 2;

const chickenSize = 15;

const positionWidth = 42;
const columns = 17;
const boardWidth = positionWidth * columns;

const stepTime = 200; // Miliseconds it takes for the chicken to take a step forward, backward, left or right

let lanes;
let currentLane;
let currentColumn;
let checkpoints = [];

let previousTimestamp;
let startMoving;
let moves;
let stepStartTimestamp;

const carFrontTexture = new Texture(40, 80, [{ x: 0, y: 10, w: 30, h: 60 }]);
const carBackTexture = new Texture(40, 80, [{ x: 10, y: 10, w: 30, h: 60 }]);
const carRightSideTexture = new Texture(110, 40, [
  { x: 10, y: 0, w: 50, h: 30 },
  { x: 70, y: 0, w: 30, h: 30 },
]);
const carLeftSideTexture = new Texture(110, 40, [
  { x: 10, y: 10, w: 50, h: 30 },
  { x: 70, y: 10, w: 30, h: 30 },
]);

const truckFrontTexture = new Texture(30, 30, [{ x: 15, y: 0, w: 10, h: 30 }]);
const truckRightSideTexture = new Texture(25, 30, [
  { x: 0, y: 15, w: 10, h: 10 },
]);
const truckLeftSideTexture = new Texture(25, 30, [
  { x: 0, y: 5, w: 10, h: 10 },
]);

const generateLanes = () =>
  [-9, -8, -7, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    .map((index) => {
      const lane = new Lane(index);
      lane.mesh.position.y = index * positionWidth * zoom;
      scene.add(lane.mesh);
      return lane;
    })
    .filter((lane) => lane.index >= 0);

const addLane = () => {
  const index = lanes.length;
  const lane = new Lane(index);
  lane.mesh.position.y = index * positionWidth * zoom;
  scene.add(lane.mesh);
  lanes.push(lane);
};

const chicken = new Chicken();
scene.add(chicken);

hemiLight = new THREE.HemisphereLight(0xffffff, 0xffffff, 0.6);
scene.add(hemiLight);

const initialDirLightPositionX = -100;
const initialDirLightPositionY = -100;
dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
dirLight.position.set(initialDirLightPositionX, initialDirLightPositionY, 200);
dirLight.castShadow = true;
dirLight.target = chicken;
scene.add(dirLight);

dirLight.shadow.mapSize.width = 2048;
dirLight.shadow.mapSize.height = 2048;
var d = 500;
dirLight.shadow.camera.left = -d;
dirLight.shadow.camera.right = d;
dirLight.shadow.camera.top = d;
dirLight.shadow.camera.bottom = -d;

// var helper = new THREE.CameraHelper( dirLight.shadow.camera );
// var helper = new THREE.CameraHelper( camera );
// scene.add(helper)

backLight = new THREE.DirectionalLight(0x000000, 0.4);
backLight.position.set(200, 200, 50);
backLight.castShadow = true;
scene.add(backLight);

const laneTypes = ["car", "truck", "forest"];
const laneSpeeds = [2, 2.5, 3];
const vechicleColors = [0xa52523, 0xbdb638, 0x78b14b];
const threeHeights = [20, 45, 60];

const initaliseValues = () => {
  lanes = generateLanes();

  currentLane = 0;
  currentColumn = Math.floor(columns / 2);

  previousTimestamp = null;

  startMoving = false;
  moves = [];
  stepStartTimestamp;

  chicken.position.x = 0;
  chicken.position.y = 0;

  camera.position.y = initialCameraPositionY;
  camera.position.x = initialCameraPositionX;

  dirLight.position.x = initialDirLightPositionX;
  dirLight.position.y = initialDirLightPositionY;
};

initaliseValues();

const renderer = new THREE.WebGLRenderer({
  alpha: true,
  antialias: true,
});
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

function Texture(width, height, rects) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.fillStyle = "rgba(0,0,0,0.6)";
  rects.forEach((rect) => {
    context.fillRect(rect.x, rect.y, rect.w, rect.h);
  });
  return new THREE.CanvasTexture(canvas);
}

function Flag() {
  const flagGroup = new THREE.Group();

  // The flagpole
  const pole = new THREE.Mesh(
    new THREE.BoxBufferGeometry(2 * zoom, 2 * zoom, 35 * zoom),
    new THREE.MeshLambertMaterial({ color: 0xcccccc, flatShading: true })
  );
  pole.position.z = 17.5 * zoom;
  pole.castShadow = true;
  pole.receiveShadow = true;
  flagGroup.add(pole);

  // The flag cloth
  const cloth = new THREE.Mesh(
    new THREE.BoxBufferGeometry(15 * zoom, 2 * zoom, 12 * zoom),
    new THREE.MeshLambertMaterial({ color: 0xf59e0b, flatShading: true }) // Bright amber color
  );
  cloth.position.x = 8.5 * zoom;
  cloth.position.z = 28 * zoom;
  cloth.castShadow = true;
  cloth.receiveShadow = true;
  flagGroup.add(cloth);

  return flagGroup;
}

function Wheel() {
  const wheel = new THREE.Mesh(
    new THREE.BoxBufferGeometry(12 * zoom, 33 * zoom, 12 * zoom),
    new THREE.MeshLambertMaterial({ color: 0x333333, flatShading: true })
  );
  wheel.position.z = 6 * zoom;
  return wheel;
}

function Car() {
  const car = new THREE.Group();
  const color =
    vechicleColors[Math.floor(Math.random() * vechicleColors.length)];

  const main = new THREE.Mesh(
    new THREE.BoxBufferGeometry(60 * zoom, 30 * zoom, 15 * zoom),
    new THREE.MeshPhongMaterial({ color, flatShading: true })
  );
  main.position.z = 12 * zoom;
  main.castShadow = true;
  main.receiveShadow = true;
  car.add(main);

  const cabin = new THREE.Mesh(
    new THREE.BoxBufferGeometry(33 * zoom, 24 * zoom, 12 * zoom),
    [
      new THREE.MeshPhongMaterial({
        color: 0xcccccc,
        flatShading: true,
        map: carBackTexture,
      }),
      new THREE.MeshPhongMaterial({
        color: 0xcccccc,
        flatShading: true,
        map: carFrontTexture,
      }),
      new THREE.MeshPhongMaterial({
        color: 0xcccccc,
        flatShading: true,
        map: carRightSideTexture,
      }),
      new THREE.MeshPhongMaterial({
        color: 0xcccccc,
        flatShading: true,
        map: carLeftSideTexture,
      }),
      new THREE.MeshPhongMaterial({ color: 0xcccccc, flatShading: true }), // top
      new THREE.MeshPhongMaterial({ color: 0xcccccc, flatShading: true }), // bottom
    ]
  );
  cabin.position.x = 6 * zoom;
  cabin.position.z = 25.5 * zoom;
  cabin.castShadow = true;
  cabin.receiveShadow = true;
  car.add(cabin);

  const frontWheel = new Wheel();
  frontWheel.position.x = -18 * zoom;
  car.add(frontWheel);

  const backWheel = new Wheel();
  backWheel.position.x = 18 * zoom;
  car.add(backWheel);

  car.castShadow = true;
  car.receiveShadow = false;

  return car;
}

function Truck() {
  const truck = new THREE.Group();
  const color =
    vechicleColors[Math.floor(Math.random() * vechicleColors.length)];

  const base = new THREE.Mesh(
    new THREE.BoxBufferGeometry(100 * zoom, 25 * zoom, 5 * zoom),
    new THREE.MeshLambertMaterial({ color: 0xb4c6fc, flatShading: true })
  );
  base.position.z = 10 * zoom;
  truck.add(base);

  const cargo = new THREE.Mesh(
    new THREE.BoxBufferGeometry(75 * zoom, 35 * zoom, 40 * zoom),
    new THREE.MeshPhongMaterial({ color: 0xb4c6fc, flatShading: true })
  );
  cargo.position.x = 15 * zoom;
  cargo.position.z = 30 * zoom;
  cargo.castShadow = true;
  cargo.receiveShadow = true;
  truck.add(cargo);

  const cabin = new THREE.Mesh(
    new THREE.BoxBufferGeometry(25 * zoom, 30 * zoom, 30 * zoom),
    [
      new THREE.MeshPhongMaterial({ color, flatShading: true }), // back
      new THREE.MeshPhongMaterial({
        color,
        flatShading: true,
        map: truckFrontTexture,
      }),
      new THREE.MeshPhongMaterial({
        color,
        flatShading: true,
        map: truckRightSideTexture,
      }),
      new THREE.MeshPhongMaterial({
        color,
        flatShading: true,
        map: truckLeftSideTexture,
      }),
      new THREE.MeshPhongMaterial({ color, flatShading: true }), // top
      new THREE.MeshPhongMaterial({ color, flatShading: true }), // bottom
    ]
  );
  cabin.position.x = -40 * zoom;
  cabin.position.z = 20 * zoom;
  cabin.castShadow = true;
  cabin.receiveShadow = true;
  truck.add(cabin);

  const frontWheel = new Wheel();
  frontWheel.position.x = -38 * zoom;
  truck.add(frontWheel);

  const middleWheel = new Wheel();
  middleWheel.position.x = -10 * zoom;
  truck.add(middleWheel);

  const backWheel = new Wheel();
  backWheel.position.x = 30 * zoom;
  truck.add(backWheel);

  return truck;
}

function Three() {
  const three = new THREE.Group();

  const trunk = new THREE.Mesh(
    new THREE.BoxBufferGeometry(15 * zoom, 15 * zoom, 20 * zoom),
    new THREE.MeshPhongMaterial({ color: 0x4d2926, flatShading: true })
  );
  trunk.position.z = 10 * zoom;
  trunk.castShadow = true;
  trunk.receiveShadow = true;
  three.add(trunk);

  height = threeHeights[Math.floor(Math.random() * threeHeights.length)];

  const crown = new THREE.Mesh(
    new THREE.BoxBufferGeometry(30 * zoom, 30 * zoom, height * zoom),
    new THREE.MeshLambertMaterial({ color: 0x7aa21d, flatShading: true })
  );
  crown.position.z = (height / 2 + 20) * zoom;
  crown.castShadow = true;
  crown.receiveShadow = false;
  three.add(crown);

  return three;
}

function Chicken() {
  const chicken = new THREE.Group();

  const body = new THREE.Mesh(
    new THREE.BoxBufferGeometry(
      chickenSize * zoom,
      chickenSize * zoom,
      20 * zoom
    ),
    new THREE.MeshPhongMaterial({ color: 0xffffff, flatShading: true })
  );
  body.position.z = 10 * zoom;
  body.castShadow = true;
  body.receiveShadow = true;
  chicken.add(body);

  const rowel = new THREE.Mesh(
    new THREE.BoxBufferGeometry(2 * zoom, 4 * zoom, 2 * zoom),
    new THREE.MeshLambertMaterial({ color: 0xf0619a, flatShading: true })
  );
  rowel.position.z = 21 * zoom;
  rowel.castShadow = true;
  rowel.receiveShadow = false;
  chicken.add(rowel);

  return chicken;
}

function Road() {
  const road = new THREE.Group();

  const createSection = (color) =>
    new THREE.Mesh(
      new THREE.PlaneBufferGeometry(boardWidth * zoom, positionWidth * zoom),
      new THREE.MeshPhongMaterial({ color })
    );

  const middle = createSection(0x454a59);
  middle.receiveShadow = true;
  road.add(middle);

  const left = createSection(0x393d49);
  left.position.x = -boardWidth * zoom;
  road.add(left);

  const right = createSection(0x393d49);
  right.position.x = boardWidth * zoom;
  road.add(right);

  return road;
}

function Grass() {
  const grass = new THREE.Group();

  const createSection = (color) =>
    new THREE.Mesh(
      new THREE.BoxBufferGeometry(
        boardWidth * zoom,
        positionWidth * zoom,
        3 * zoom
      ),
      new THREE.MeshPhongMaterial({ color })
    );

  const middle = createSection(0xbaf455);
  middle.receiveShadow = true;
  grass.add(middle);

  const left = createSection(0x99c846);
  left.position.x = -boardWidth * zoom;
  grass.add(left);

  const right = createSection(0x99c846);
  right.position.x = boardWidth * zoom;
  grass.add(right);

  grass.position.z = 1.5 * zoom;
  return grass;
}

function Lane(index, forceType) {
  this.index = index;
  this.type =
    index <= 0
      ? "field"
      : forceType || laneTypes[Math.floor(Math.random() * laneTypes.length)];

  switch (this.type) {
    case "field": {
      this.type = "field";
      this.mesh = new Grass();
      break;
    }
    case "forest": {
      this.mesh = new Grass();

      this.occupiedPositions = new Set();
      this.threes = [1, 2, 3, 4].map(() => {
        const three = new Three();
        let position;
        do {
          position = Math.floor(Math.random() * columns);
        } while (this.occupiedPositions.has(position));
        this.occupiedPositions.add(position);
        three.position.x =
          (position * positionWidth + positionWidth / 2) * zoom -
          (boardWidth * zoom) / 2;
        this.mesh.add(three);
        return three;
      });
      break;
    }
    case "car": {
      this.mesh = new Road();
      this.direction = Math.random() >= 0.5;

      const occupiedPositions = new Set();
      this.vechicles = [1, 2, 3].map(() => {
        const vechicle = new Car();
        let position;
        do {
          position = Math.floor((Math.random() * columns) / 2);
        } while (occupiedPositions.has(position));
        occupiedPositions.add(position);
        vechicle.position.x =
          (position * positionWidth * 2 + positionWidth / 2) * zoom -
          (boardWidth * zoom) / 2;
        if (!this.direction) vechicle.rotation.z = Math.PI;
        this.mesh.add(vechicle);
        return vechicle;
      });

      this.speed = laneSpeeds[Math.floor(Math.random() * laneSpeeds.length)];
      break;
    }
    case "truck": {
      this.mesh = new Road();
      this.direction = Math.random() >= 0.5;

      const occupiedPositions = new Set();
      this.vechicles = [1, 2].map(() => {
        const vechicle = new Truck();
        let position;
        do {
          position = Math.floor((Math.random() * columns) / 3);
        } while (occupiedPositions.has(position));
        occupiedPositions.add(position);
        vechicle.position.x =
          (position * positionWidth * 3 + positionWidth / 2) * zoom -
          (boardWidth * zoom) / 2;
        if (!this.direction) vechicle.rotation.z = Math.PI;
        this.mesh.add(vechicle);
        return vechicle;
      });

      this.speed = laneSpeeds[Math.floor(Math.random() * laneSpeeds.length)];
      break;
    }
  }
}

// ============================================================================
// TRAFFIC PREDICTION ENGINE -- used by the auto-pathing in findSafePathToLane()
// and findCollisionPath() above.
//
// Cars and trucks move at constant speed and wrap around the board, so their
// position at any future moment is fully predictable from the game's own
// motion formula (see animate() below). That means "is this lane safe" isn't
// a fixed fact about a cell -- it's a fact about a (cell, time) pair.
//
// So instead of searching a plain grid, those functions search a
// *time-expanded* graph: each node is (lane, column, tick), where a tick is
// one stepTime-long move. An edge from tick t to t+1 only exists if the
// destination cell is predicted to be clear of traffic at time t+1. Every
// edge costs exactly one tick, so plain BFS over this graph already returns
// the fastest safe route -- no heuristic needed. This also naturally finds
// "wait a beat, then go" plays, which plain grid pathfinding (like A* on a
// static maze) can't express at all.
// ============================================================================

function laneVehicleLength(lane) {
  return lane.type === "truck" ? 105 : 60;
}

// Predicts a single vehicle's x position `dtMs` milliseconds from now,
// replicating the wrap-around motion applied every frame in animate().
function predictVehicleX(vechicle, lane, dtMs) {
  const aBitBefore = (-boardWidth * zoom) / 2 - positionWidth * 2 * zoom;
  const aBitAfter = (boardWidth * zoom) / 2 + positionWidth * 2 * zoom;
  const span = aBitAfter - aBitBefore;
  const distance = (lane.speed / 16) * dtMs;
  const raw = vechicle.position.x + (lane.direction ? -distance : distance);
  return ((((raw - aBitBefore) % span) + span) % span) + aBitBefore;
}

function columnToX(column) {
  return (column * positionWidth + positionWidth / 2) * zoom - (boardWidth * zoom) / 2;
}

// Is (lane, column) predicted to be clear `dtMs` from now?
function isColumnSafeAtTime(lane, column, dtMs) {
  if (lane.type === "field") return true;
  if (lane.type === "forest") return !lane.occupiedPositions.has(column);

  const columnX = columnToX(column);
  const margin = (chickenSize * zoom) / 2;
  const vehicleHalfLength = (laneVehicleLength(lane) * zoom) / 2;
  return lane.vechicles.every((vechicle) => {
    const predictedX = predictVehicleX(vechicle, lane, dtMs);
    return Math.abs(predictedX - columnX) > vehicleHalfLength + margin;
  });
}

// Wire up the "Quit to Menu" button
document.getElementById("quitBtn").addEventListener("click", () => {
  // 1. Stop the countdown timer so the game doesn't crash in the background
  clearInterval(questionTimerInterval);
  answerLocked = true; 
  
  // 2. Hide the game UI and pause the 3D engine
  document.getElementById("startupLesson").classList.add("hidden");
  isGamePausedForLesson = true;
  
  // 3. Route back to the lesson select screen
  goToAlgorithmSelect();
});

// Wire up the "Scoreboard" button
document.getElementById("viewScoreboardBtn").addEventListener("click", () => {
  clearInterval(questionTimerInterval);
  answerLocked = true;
  
  document.getElementById("startupLesson").classList.add("hidden");
  isGamePausedForLesson = true;
  
  // Calculate the score at the exact moment they clicked and show the board
  const currentScore = computeScore();
  showScoreboard(currentScore, false);
});
// NOTE: manual movement (arrow keys / on-screen D-pad) has been removed.
// Crossing now happens automatically, driven entirely by quiz answers --
// see smartCrossToCheckpoint()/forceCrossIntoTraffic() and the quiz engine near the top of this file.

function animate(timestamp) {
  requestAnimationFrame(animate);

  // If the lesson is active, draw the initial 3D scene but DO NOT move the cars
  if (isGamePausedForLesson) {
      renderer.render(scene, camera);
      return;
  }

  if (!previousTimestamp) previousTimestamp = timestamp;
  const delta = timestamp - previousTimestamp;
  previousTimestamp = timestamp;

  // Animate cars and trucks moving on the lane
  lanes.forEach((lane) => {
    if (lane.type === "car" || lane.type === "truck") {
      const aBitBeforeTheBeginingOfLane =
        (-boardWidth * zoom) / 2 - positionWidth * 2 * zoom;
      const aBitAfterTheEndOFLane =
        (boardWidth * zoom) / 2 + positionWidth * 2 * zoom;
      lane.vechicles.forEach((vechicle) => {
        if (lane.direction) {
          vechicle.position.x =
            vechicle.position.x < aBitBeforeTheBeginingOfLane
              ? aBitAfterTheEndOFLane
              : (vechicle.position.x -= (lane.speed / 16) * delta);
        } else {
          vechicle.position.x =
            vechicle.position.x > aBitAfterTheEndOFLane
              ? aBitBeforeTheBeginingOfLane
              : (vechicle.position.x += (lane.speed / 16) * delta);
        }
      });
    }
  });

  if (startMoving) {
    stepStartTimestamp = timestamp;
    startMoving = false;
  }

  if (stepStartTimestamp) {
    const moveDeltaTime = timestamp - stepStartTimestamp;
    const moveDeltaDistance =
      Math.min(moveDeltaTime / stepTime, 1) * positionWidth * zoom;
    const jumpDeltaDistance =
      Math.sin(Math.min(moveDeltaTime / stepTime, 1) * Math.PI) * 8 * zoom;
    switch (moves[0]) {
      case "forward": {
        const positionY =
          currentLane * positionWidth * zoom + moveDeltaDistance;
        camera.position.y = initialCameraPositionY + positionY;
        dirLight.position.y = initialDirLightPositionY + positionY;
        chicken.position.y = positionY; // initial chicken position is 0

        chicken.position.z = jumpDeltaDistance;
        break;
      }
      case "backward": {
        positionY = currentLane * positionWidth * zoom - moveDeltaDistance;
        camera.position.y = initialCameraPositionY + positionY;
        dirLight.position.y = initialDirLightPositionY + positionY;
        chicken.position.y = positionY;

        chicken.position.z = jumpDeltaDistance;
        break;
      }
      case "left": {
        const positionX =
          (currentColumn * positionWidth + positionWidth / 2) * zoom -
          (boardWidth * zoom) / 2 -
          moveDeltaDistance;
        camera.position.x = initialCameraPositionX + positionX;
        dirLight.position.x = initialDirLightPositionX + positionX;
        chicken.position.x = positionX; // initial chicken position is 0
        chicken.position.z = jumpDeltaDistance;
        break;
      }
      case "right": {
        const positionX =
          (currentColumn * positionWidth + positionWidth / 2) * zoom -
          (boardWidth * zoom) / 2 +
          moveDeltaDistance;
        camera.position.x = initialCameraPositionX + positionX;
        dirLight.position.x = initialDirLightPositionX + positionX;
        chicken.position.x = positionX;

        chicken.position.z = jumpDeltaDistance;
        break;
      }
    }
    // Once a step has ended
    if (moveDeltaTime > stepTime) {
      switch (moves[0]) {
        case "forward": {
          currentLane++;
          counterDOM.innerHTML = currentLane;
          break;
        }
        case "backward": {
          currentLane--;
          counterDOM.innerHTML = currentLane;
          break;
        }
        case "left": {
          currentColumn--;
          break;
        }
        case "right": {
          currentColumn++;
          break;
        }
      }
      moves.shift();
      // If more steps are to be taken then restart counter otherwise stop stepping
      stepStartTimestamp = moves.length === 0 ? null : timestamp;
    }
  }

  // NOTE: physics-based collision detection is intentionally disabled.
  // In this quiz-run version, whether the chicken survives a road is
  // decided entirely by the answer the player picks (see submitAnswer()
  // and triggerCrash() below) -- not by real-time overlap with traffic.
  renderer.render(scene, camera);
}

requestAnimationFrame(animate);