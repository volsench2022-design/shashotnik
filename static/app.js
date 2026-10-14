const authView = document.querySelector("#auth-view");
const lobbyView = document.querySelector("#lobby-view");
const gameView = document.querySelector("#game-view");
const authForm = document.querySelector("#auth-form");
const authMessage = document.querySelector("#auth-message");
const boardElement = document.querySelector("#board");
let authMode = "register";
let token = sessionStorage.getItem("checkers-token");
let player = null;
let socket = null;
let gameState = null;
let selectedSquare = null;
let allowedMoves = [];

function show(view) {
  [authView, lobbyView, gameView].forEach((item) => item.classList.toggle("hidden", item !== view));
}

function updateProfile(user) {
  player = user;
  document.querySelector("#player-name").textContent = user.username;
  document.querySelector("#player-rating").textContent = user.rating;
  document.querySelector("#player-wins").textContent = user.wins;
  document.querySelector("#player-record").textContent = `${user.wins}—${user.losses}`;
}

async function api(path, data, authenticated = false) {
  const headers = { "Content-Type": "application/json" };
  if (authenticated && token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { method: data ? "POST" : "GET", headers, body: data ? JSON.stringify(data) : undefined });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Something went wrong. Please try again.");
  return result;
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    authMode = tab.dataset.mode;
    document.querySelectorAll(".tab").forEach((item) => {
      const active = item === tab;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", String(active));
    });
    document.querySelector("#auth-action").textContent = authMode === "register" ? "CREATE FREE ACCOUNT" : "SIGN IN TO PLAY";
    document.querySelector("#password").autocomplete = authMode === "register" ? "new-password" : "current-password";
    authMessage.textContent = "";
  });
});

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authMessage.textContent = "";
  const button = authForm.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const result = await api(`/api/${authMode}`, {
      username: authForm.username.value.trim(),
      password: authForm.password.value,
    });
    token = result.token;
    sessionStorage.setItem("checkers-token", token);
    updateProfile(result.user);
    show(lobbyView);
    authForm.reset();
  } catch (error) {
    authMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

function renderBoard(state) {
  boardElement.replaceChildren();
  const movesFromSelected = allowedMoves.filter((move) => move.from[0] === selectedSquare?.[0] && move.from[1] === selectedSquare?.[1]);
  const targets = new Set(movesFromSelected.map((move) => `${move.to[0]},${move.to[1]}`));
  for (let row = 0; row < 8; row += 1) {
    for (let col = 0; col < 8; col += 1) {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = `square ${(row + col) % 2 ? "dark" : "light"}`;
      cell.setAttribute("role", "gridcell");
      cell.setAttribute("aria-label", `Row ${row + 1}, column ${col + 1}`);
      if (selectedSquare?.[0] === row && selectedSquare?.[1] === col) cell.classList.add("selected");
      if (targets.has(`${row},${col}`)) cell.classList.add("target");
      const piece = state.board[row][col];
      if (piece) {
        const disc = document.createElement("span");
        disc.className = `piece ${piece.toLowerCase() === "r" ? "red" : "black"}${piece === piece.toUpperCase() ? " king" : ""}`;
        disc.setAttribute("aria-label", `${piece.toLowerCase() === "r" ? "red" : "black"} ${piece === piece.toUpperCase() ? "king" : "checker"}`);
        cell.append(disc);
      }
      cell.addEventListener("click", () => clickSquare(row, col, state));
      boardElement.append(cell);
    }
  }
}

function clickSquare(row, col, state) {
  if (!state.yourTurn) return;
  const move = allowedMoves.find((item) => item.from[0] === selectedSquare?.[0] && item.from[1] === selectedSquare?.[1] && item.to[0] === row && item.to[1] === col);
  if (move) {
    socket?.send(JSON.stringify({ type: "move", from: move.from, to: move.to }));
    selectedSquare = null;
    return;
  }
  const ownPiece = state.board[row][col];
  const isOwnPiece = ownPiece && (state.yourSide === "red" ? ownPiece.toLowerCase() === "r" : ownPiece.toLowerCase() === "b");
  if (isOwnPiece && allowedMoves.some((item) => item.from[0] === row && item.from[1] === col)) selectedSquare = [row, col];
  else selectedSquare = null;
  renderBoard(state);
}

function showGameMessage(text, isError = false) {
  const element = document.querySelector("#game-message");
  element.textContent = text;
  element.style.color = isError ? "var(--coral)" : "";
}

function connect() {
  if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${scheme}//${location.host}/ws`);
  socket.addEventListener("open", () => socket.send(JSON.stringify({ token })));
  socket.addEventListener("message", async (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "queued") {
      document.querySelector("#opponent-name").textContent = "Searching for a rival…";
      showGameMessage(message.message);
    } else if (message.type === "state") {
      gameState = message;
      allowedMoves = message.legalMoves;
      selectedSquare = null;
      document.querySelector("#opponent-name").textContent = message.opponent;
      document.querySelector("#turn-indicator").textContent = message.yourTurn ? "YOUR TURN" : "THEIR TURN";
      document.querySelector("#turn-indicator").classList.toggle("active", message.yourTurn);
      showGameMessage(message.yourTurn ? "Your move. Good luck!" : "Opponent is thinking…");
      document.querySelector("#rematch-button").classList.add("hidden");
      renderBoard(message);
    } else if (message.type === "error") {
      showGameMessage(message.message, true);
    } else if (message.type === "game_over") {
      const ratingChange = message.ratings[player.id] - player.rating;
      showGameMessage(`${message.result === "win" ? "You won" : message.result === "draw" ? "It's a draw" : "Game over"} · ${message.reason} · Rating ${ratingChange >= 0 ? "+" : ""}${ratingChange}`);
      document.querySelector("#turn-indicator").textContent = "MATCH OVER";
      document.querySelector("#turn-indicator").classList.remove("active");
      document.querySelector("#rematch-button").classList.remove("hidden");
      try {
        updateProfile(await api("/api/me", null, true));
      } catch (error) {
        showGameMessage(error.message, true);
      }
    }
  });
  socket.addEventListener("close", (event) => {
    if (token && gameView.classList.contains("hidden") === false && event.code !== 1000) {
      showGameMessage(event.reason || "Connection lost. Return to the lobby and try again.", true);
    }
  });
}

document.querySelector("#queue-button").addEventListener("click", () => {
  show(gameView);
  document.querySelector("#rematch-button").classList.add("hidden");
  document.querySelector("#turn-indicator").textContent = "SEARCHING";
  boardElement.replaceChildren();
  connect();
});
document.querySelector("#rematch-button").addEventListener("click", () => {
  document.querySelector("#rematch-button").classList.add("hidden");
  showGameMessage("Looking for another opponent…");
  socket?.send(JSON.stringify({ type: "rematch" }));
});
document.querySelector("#resign-button").addEventListener("click", () => {
  if (gameState && window.confirm("Resign this match?")) socket?.send(JSON.stringify({ type: "resign" }));
});
document.querySelector("#signout-button").addEventListener("click", () => {
  token = null;
  player = null;
  sessionStorage.removeItem("checkers-token");
  socket?.close();
  show(authView);
});

async function start() {
  if (!token) return show(authView);
  try {
    updateProfile(await api("/api/me", null, true));
    show(lobbyView);
  } catch {
    token = null;
    sessionStorage.removeItem("checkers-token");
    show(authView);
  }
}
start();
