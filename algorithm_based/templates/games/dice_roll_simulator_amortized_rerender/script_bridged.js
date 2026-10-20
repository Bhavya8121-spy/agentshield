const buttonEl = document.getElementById("roll-button");
const diceEl = document.getElementById("dice");
const rollHistoryEl = document.getElementById("roll-history");

let historyList = [];
let currentState = null;
let markerActive = false;
let markerRevealed = false;

function rollDice() {
  const rollResult = Math.floor(Math.random() * 6) + 1;
  const diceFace = getDiceFace(rollResult);
  if (diceEl) diceEl.innerHTML = diceFace;
  historyList.push(rollResult);
  updateRollHistory();

  const k = historyList.length;
  const totalOps = (k * (k + 1)) / 2;
  currentState = {
    k: k,
    latest_roll: rollResult,
    history_length: historyList.length,
    step_render_ops: k,
    total_render_ops: totalOps,
    re_renders_more_than_two: k > 2
  };
  drawCanvas(currentState, markerActive, markerRevealed);
}

function updateRollHistory() {
  if (!rollHistoryEl) return;
  rollHistoryEl.innerHTML = "";
  for (let i = 0; i < historyList.length; i++) {
    const listItem = document.createElement("li");
    listItem.innerHTML = `Roll ${i + 1}: <span>${getDiceFace(
      historyList[i]
    )}</span>`;
    rollHistoryEl.appendChild(listItem);
  }
}

function getDiceFace(rollResult) {
  switch (rollResult) {
    case 1:
      return "&#9856;";
    case 2:
      return "&#9857;";
    case 3:
      return "&#9858;";
    case 4:
      return "&#9859;";
    case 5:
      return "&#9860;";
    case 6:
      return "&#9861;";
    default:
      return "";
  }
}

if (buttonEl) {
  buttonEl.addEventListener("click", () => {
    if (diceEl) diceEl.classList.add("roll-animation");
    setTimeout(() => {
      if (diceEl) diceEl.classList.remove("roll-animation");
      rollDice();
    }, 1000);
  });
}

function drawCanvas(state, showMarker, isRevealed) {
  const canvas = document.getElementById("scene-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const w = canvas.width || 800;
  const h = canvas.height || 500;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);

  if (!state) return;

  const k = state.k || 0;
  const roll = state.latest_roll || 1;
  const historyLen = state.history_length || 0;
  const stepOps = state.step_render_ops || 0;
  const totalOps = state.total_render_ops || 0;
  const reRendersMore = state.re_renders_more_than_two;

  ctx.fillStyle = "#333333";
  ctx.font = "bold 22px 'Open Sans', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(`Dice Roll Simulator — Step ${k}`, w / 2, 40);

  const diceSize = 90;
  const diceX = w / 2 - diceSize / 2;
  const diceY = 60;

  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.15)";
  ctx.shadowBlur = 8;
  ctx.shadowOffsetY = 4;
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#333333";
  ctx.lineWidth = 3;
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(diceX, diceY, diceSize, diceSize, 12);
  else ctx.rect(diceX, diceY, diceSize, diceSize);
  ctx.fill();
  ctx.stroke();
  ctx.restore();

  ctx.fillStyle = "#333333";
  const dotRadius = 7;
  const cx = diceX + diceSize / 2;
  const cy = diceY + diceSize / 2;
  const left = diceX + 22;
  const right = diceX + 68;
  const top = diceY + 22;
  const bottom = diceY + 68;

  const dots = [];
  if (roll % 2 === 1) dots.push([cx, cy]);
  if (roll > 1) { dots.push([left, top]); dots.push([right, bottom]); }
  if (roll > 3) { dots.push([right, top]); dots.push([left, bottom]); }
  if (roll === 6) { dots.push([left, cy]); dots.push([right, cy]); }

  dots.forEach(([x, y]) => {
    ctx.beginPath();
    ctx.arc(x, y, dotRadius, 0, Math.PI * 2);
    ctx.fill();
  });

  const statsY = 175;
  ctx.fillStyle = "#f8f9fa";
  ctx.fillRect(40, statsY, w - 80, 85);
  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  ctx.strokeRect(40, statsY, w - 80, 85);

  ctx.fillStyle = "#333333";
  ctx.font = "15px 'Open Sans', sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(`History Length: ${historyLen}`, 60, statsY + 32);
  ctx.fillText(`Total Render Ops: ${totalOps}`, 60, statsY + 60);
  ctx.fillText(`Step Render Ops: ${stepOps}`, w / 2 + 10, statsY + 32);

  if (showMarker) {
    const markerX = w / 2 + 10;
    const markerY = statsY + 45;
    const markerW = 330;
    const markerH = 32;

    if (!isRevealed) {
      ctx.fillStyle = "#e2e8f0";
      ctx.strokeStyle = "#64748b";
      ctx.lineWidth = 2;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(markerX, markerY, markerW, markerH, 6);
      else ctx.rect(markerX, markerY, markerW, markerH);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = "#334155";
      ctx.font = "bold 13px 'Open Sans', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Re-renders > 2? [ Candidate Prediction ]", markerX + markerW / 2, markerY + 20);
    } else {
      const isTrue = reRendersMore === true;
      ctx.fillStyle = isTrue ? "#dcfce7" : "#fee2e2";
      ctx.strokeStyle = isTrue ? "#22c55e" : "#ef4444";
      ctx.lineWidth = 2;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(markerX, markerY, markerW, markerH, 6);
      else ctx.rect(markerX, markerY, markerW, markerH);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = isTrue ? "#15803d" : "#b91c1c";
      ctx.font = "bold 13px 'Open Sans', sans-serif";
      ctx.textAlign = "center";
      const label = isTrue ? `Re-renders > 2: TRUE (${stepOps} ops)` : `Re-renders > 2: FALSE (${stepOps} ops)`;
      ctx.fillText(label, markerX + markerW / 2, markerY + 20);
    }
  }

  const listY = 285;
  ctx.fillStyle = "#333333";
  ctx.font = "bold 15px 'Open Sans', sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Rendered History Items:", 40, listY);

  const startX = 40;
  const itemWidth = 65;
  const itemHeight = 35;
  const gap = 10;
  const maxItemsPerRow = Math.floor((w - 80) / (itemWidth + gap));

  for (let i = 0; i < historyLen; i++) {
    const row = Math.floor(i / maxItemsPerRow);
    const col = i % maxItemsPerRow;
    const ix = startX + col * (itemWidth + gap);
    const iy = listY + 12 + row * (itemHeight + gap);

    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#47a5c4";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(ix, iy, itemWidth, itemHeight, 4);
    else ctx.rect(ix, iy, itemWidth, itemHeight);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#333333";
    ctx.font = "13px 'Open Sans', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(`#${i + 1}`, ix + itemWidth / 2, iy + 22);
  }
}

window.setupScene = function(introStep) {
  const state = (introStep && introStep.state) ? introStep.state : (introStep || {});
  if (state.k !== undefined) {
    currentState = state;
  } else {
    currentState = {
      k: 0,
      latest_roll: 1,
      history_length: 0,
      step_render_ops: 0,
      total_render_ops: 0,
      re_renders_more_than_two: false
    };
  }
  markerActive = false;
  markerRevealed = false;
  drawCanvas(currentState, markerActive, markerRevealed);
};

window.showStepMarker = function(state) {
  currentState = state;
  markerActive = true;
  markerRevealed = false;
  drawCanvas(currentState, markerActive, markerRevealed);
};

window.revealStepMarker = function(state) {
  currentState = state;
  markerActive = true;
  markerRevealed = true;
  drawCanvas(currentState, markerActive, markerRevealed);
};

window.clearStepMarker = function() {
  markerActive = false;
  markerRevealed = false;
  drawCanvas(currentState, markerActive, markerRevealed);
};

window.playResolutionAnimation = function(doneState, onComplete) {
  currentState = doneState || currentState;
  markerActive = false;
  markerRevealed = false;

  let startTime = null;
  const duration = 1000;

  function animate(timestamp) {
    if (!startTime) startTime = timestamp;
    const elapsed = timestamp - startTime;

    if (elapsed < duration) {
      const tempRoll = Math.floor(Math.random() * 6) + 1;
      const animState = Object.assign({}, currentState, { latest_roll: tempRoll });
      drawCanvas(animState, false, false);
      requestAnimationFrame(animate);
    } else {
      drawCanvas(currentState, false, false);
      if (typeof onComplete === "function") {
        onComplete();
      }
    }
  }

  requestAnimationFrame(animate);
};