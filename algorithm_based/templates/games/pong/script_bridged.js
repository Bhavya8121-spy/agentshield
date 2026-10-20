// script_bridged.js
//
// Hand-verified bridge for the Pong "Binary Search Interception" dashboard.
// Same role as the Tetris bridge's setupFrozenBoard()/animateDropAndSpawn():
// the trace-driven index.html calls these window.* hooks, this file owns
// all canvas drawing. It does not run the actual two-player Pong game loop
// (script.js) -- this dashboard shows one scripted ball path per the fixed
// puzzle instance in algorithms.json, exactly like the Tetris dashboard
// shows one fixed piece sequence.
//
// Coordinate system: internal canvas resolution matches the real game
// (600x400, ball radius 10, paddle 10x80) so any recorded (x, y) from the
// engine.py trace maps 1:1 onto this canvas -- no rescaling logic to get
// wrong.

(function () {
  const BALL_RADIUS = 10;
  const PADDLE_WIDTH = 10;
  const PADDLE_HEIGHT = 80;

  let canvas, ctx;
  let sceneBall = null;   // {x, y}
  let sceneBoard = null;  // {width, height}
  let scenePaddleX = null;
  let scenePaddleY = null; // current paddle y (top-left), null until first reveal
  let ghost = null;        // {x, y, mid, lo, hi} or null
  let animHandle = null;

  function ensureCanvas() {
    canvas = document.getElementById("pong-canvas");
    ctx = canvas.getContext("2d");
  }

  function paddleSideIsLeft() {
    return scenePaddleX !== null && scenePaddleX < sceneBoard.width / 2;
  }

  function drawScene() {
    if (!ctx || !sceneBoard) return;
    const { width, height } = sceneBoard;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#050510";
    ctx.fillRect(0, 0, width, height);

    // Center line
    ctx.strokeStyle = "#2a2a3a";
    ctx.setLineDash([6, 8]);
    ctx.beginPath();
    ctx.moveTo(width / 2, 0);
    ctx.lineTo(width / 2, height);
    ctx.stroke();
    ctx.setLineDash([]);

    // Target paddle x-line (dashed, neon) -- the line binary search is
    // homing in on.
    ctx.strokeStyle = "#00f3ff";
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(scenePaddleX + PADDLE_WIDTH / 2, 0);
    ctx.lineTo(scenePaddleX + PADDLE_WIDTH / 2, height);
    ctx.stroke();
    ctx.setLineDash([]);

    // Paddle (only drawn once it has a y -- before the first reveal there's
    // nothing to show yet, which is the point: the player predicts where it
    // *should* go before seeing it move there).
    if (scenePaddleY !== null) {
      ctx.fillStyle = "#39ff14";
      const px = paddleSideIsLeft() ? 0 : sceneBoard.width - PADDLE_WIDTH;
      ctx.fillRect(px, scenePaddleY, PADDLE_WIDTH, PADDLE_HEIGHT);
    }

    // Real ball, frozen at its starting position.
    ctx.fillStyle = "#ffd700";
    ctx.beginPath();
    ctx.arc(sceneBall.x, sceneBall.y, BALL_RADIUS, 0, Math.PI * 2);
    ctx.fill();

    // Ghost marker: the candidate frame currently being tested by the
    // binary search step shown in the side panel.
    if (ghost) {
      const neutral = ghost.predicateTrue === null;
      ctx.strokeStyle = neutral ? "#ffd700" : (ghost.predicateTrue ? "#39ff14" : "#ff003c");
      ctx.fillStyle = neutral ? "rgba(255,215,0,0.25)" : (ghost.predicateTrue ? "rgba(57,255,20,0.25)" : "rgba(255,0,60,0.25)");
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(ghost.x, ghost.y, BALL_RADIUS, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = "#e0e0e0";
      ctx.font = "14px monospace";
      ctx.fillText(`frame ${ghost.mid}`, Math.min(Math.max(ghost.x - 24, 4), width - 60), Math.max(ghost.y - 16, 14));
    }
  }

  // ---- Public bridge API ----

  window.setupPongScene = function (ball, board, paddleX) {
    ensureCanvas();
    sceneBall = { x: ball.x, y: ball.y };
    sceneBoard = { width: board.width, height: board.height };
    scenePaddleX = paddleX;
    scenePaddleY = null;
    ghost = null;
    drawScene();
  };

  // Neutral marker shown BEFORE the player answers -- deliberately
  // uncolored by correctness, or the color itself would give the answer
  // away. predicateTrue is null until revealGhost() is called.
  window.showGhost = function (mid, xAtMid, yAtMid) {
    ghost = { mid, x: xAtMid, y: yAtMid, predicateTrue: null };
    drawScene();
  };

  // Recolors the current ghost to reflect the algorithm's actual answer,
  // called only after the player has locked in their own guess.
  window.revealGhost = function (predicateTrue) {
    if (ghost) ghost.predicateTrue = predicateTrue;
    drawScene();
  };

  window.clearGhost = function () {
    ghost = null;
    drawScene();
  };

  window.showNoInterception = function () {
    ghost = null;
    drawScene();
    ctx.fillStyle = "#ff003c";
    ctx.font = "20px 'VT323', monospace";
    ctx.textAlign = "center";
    ctx.fillText(
      "NO INTERCEPTION WITHIN SEARCH HORIZON",
      sceneBoard.width / 2,
      sceneBoard.height / 2
    );
    ctx.textAlign = "left";
  };

  // Animates the ball's REAL flight (respecting wall bounces frame by
  // frame, same physics as script.js's update()) from frame 0 to
  // interceptFrame, while the paddle glides to predictedY. Calls
  // onComplete() once the animation finishes.
  window.playInterceptionAnimation = function (ball, board, paddleX, interceptFrame, predictedY, onComplete) {
    if (animHandle) cancelAnimationFrame(animHandle);
    ghost = null;

    let frame = 0;
    let x = ball.x, y = ball.y;
    let vy = ball.vy;
    const vx = ball.vx;
    const height = board.height;

    scenePaddleX = paddleX;
    // Paddle starts centered, glides to predictedY over the course of the
    // animation -- mirrors how a real player/AI would track the ball.
    const paddleStartY = height / 2 - PADDLE_HEIGHT / 2;
    scenePaddleY = paddleStartY;

    function step() {
      frame++;
      x += vx;
      y += vy;
      if (y - BALL_RADIUS < 0 || y + BALL_RADIUS > height) {
        vy = -vy;
        y = Math.max(BALL_RADIUS, Math.min(height - BALL_RADIUS, y));
      }

      const progress = Math.min(frame / interceptFrame, 1);
      scenePaddleY = paddleStartY + (predictedY - PADDLE_HEIGHT / 2 - paddleStartY) * progress;

      sceneBall = { x, y };
      drawScene();

      if (frame < interceptFrame) {
        animHandle = requestAnimationFrame(step);
      } else {
        // Snap to the exact predicted catch point.
        scenePaddleY = Math.max(0, Math.min(height - PADDLE_HEIGHT, predictedY - PADDLE_HEIGHT / 2));
        drawScene();
        ctx.fillStyle = "#39ff14";
        ctx.font = "24px 'VT323', monospace";
        ctx.textAlign = "center";
        ctx.fillText("INTERCEPTED!", board.width / 2, 30);
        ctx.textAlign = "left";
        if (typeof onComplete === "function") onComplete();
      }
    }

    animHandle = requestAnimationFrame(step);
  };
})();