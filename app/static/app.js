const DEVICE_ID_KEY = "farkle.device_id";
const PLAYER_KEY = "farkle.player";

function getDeviceId() {
  // localStorage mantiene el identificador entre visitas del mismo navegador.
  let deviceId = localStorage.getItem(DEVICE_ID_KEY);
  if (!deviceId) {
    deviceId = crypto.randomUUID();
    localStorage.setItem(DEVICE_ID_KEY, deviceId);
  }
  return deviceId;
}

const form = document.querySelector("#player-form");
const nameInput = document.querySelector("#player-name");
const message = document.querySelector("#form-message");
const identityView = document.querySelector("#identity-view");
const lobbyView = document.querySelector("#lobby-view");
const gameView = document.querySelector("#game-view");
const playerChip = document.querySelector("#player-chip");
const lobbyMessage = document.querySelector("#lobby-message");
const gameMessage = document.querySelector("#game-message");
// Estos valores representan la sesión del navegador, no una autenticación de usuario.
let currentPlayer = JSON.parse(localStorage.getItem(PLAYER_KEY) || "null");
let currentGame = null;
let refreshTimer = null;

if (currentPlayer?.name) nameInput.value = currentPlayer.name;

function showLobby(player) {
  // Solo una vista principal permanece visible a la vez.
  identityView.hidden = true;
  gameView.hidden = true;
  lobbyView.hidden = false;
  playerChip.textContent = player.name;
}

function showGame(game) {
  // La sala se refresca periódicamente para que varios clientes vean los mismos jugadores.
  currentGame = game;
  lobbyView.hidden = true;
  identityView.hidden = true;
  gameView.hidden = false;
  renderGame(game);
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => refreshGame(game.id), 3000);
}

function renderGame(game) {
  // Por ahora se representa únicamente el estado estructural, sin dados ni puntuación calculada.
  document.querySelector("#game-code-label").textContent = game.id;
  document.querySelector("#game-phase").textContent = game.status === "waiting" ? "Sala de espera" : "Partida en curso";
  document.querySelector("#game-status-label").textContent = game.status === "waiting" ? "Esperando jugadores" : "Turno activo";
  document.querySelector("#game-turn-label").textContent = game.current_player_id ? `Turno ${game.turn_number}` : "";
  document.querySelector("#player-count").textContent = `${game.players.length} conectados`;
  document.querySelector("#player-list").innerHTML = game.players.map((player) => `
    <div class="player-row"><span class="seat">0${player.seat}</span><strong>${escapeHtml(player.name)}</strong><span class="score">${player.score} pts</span></div>
  `).join("");
  document.querySelector("#start-game").hidden = game.host_player_id !== currentPlayer.id || game.status !== "waiting";
  document.querySelector("#start-game").disabled = game.players.length < 2;
}

function escapeHtml(value) {
  // Los nombres llegan de otros clientes y deben tratarse como texto, nunca como HTML.
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

async function requestJson(url, options) {
  // Centralizar la lectura de errores mantiene iguales los mensajes de todas las acciones.
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "No se pudo completar la operación");
  return data;
}

async function refreshGame(gameId) {
  // El polling es suficiente para el lobby inicial; más adelante puede sustituirse por WebSockets.
  try {
    showGame(await requestJson(`/api/games/${gameId}`));
  } catch (error) {
    gameMessage.textContent = error.message;
    gameMessage.className = "form-message is-error";
  }
}

async function createGame(event) {
  // El servidor genera el código y coloca al creador en el primer asiento.
  event.preventDefault();
  lobbyMessage.textContent = "Creando la mesa...";
  try {
    showGame(await requestJson("/api/games", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: currentPlayer.id }),
    }));
  } catch (error) {
    lobbyMessage.textContent = error.message;
    lobbyMessage.className = "form-message is-error";
  }
}

async function joinGame(event) {
  // El código se normaliza porque se comparte manualmente entre jugadores.
  event.preventDefault();
  lobbyMessage.textContent = "Buscando la mesa...";
  try {
    showGame(await requestJson(`/api/games/${document.querySelector("#game-code").value.trim().toUpperCase()}/join`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: currentPlayer.id }),
    }));
  } catch (error) {
    lobbyMessage.textContent = error.message;
    lobbyMessage.className = "form-message is-error";
  }
}

form.addEventListener("submit", async (event) => {
  // Registrar la identidad es el paso previo común para acceder al lobby.
  event.preventDefault();
  message.textContent = "Guardando tu identidad...";
  message.className = "form-message is-loading";

  try {
    const response = await fetch("/api/players", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: nameInput.value, device_id: getDeviceId() }),
    });
    const player = await response.json();
    if (!response.ok) throw new Error(player.detail || "No se pudo guardar el nombre");

    localStorage.setItem(PLAYER_KEY, JSON.stringify(player));
    currentPlayer = player;
    showLobby(player);
  } catch (error) {
    message.textContent = error.message;
    message.className = "form-message is-error";
  }
});

document.querySelector("#create-game-form").addEventListener("submit", createGame);
document.querySelector("#join-game-form").addEventListener("submit", joinGame);
document.querySelector("#back-to-lobby").addEventListener("click", () => {
  // Salir de la vista no abandona la partida; solo deja de mostrarla en este navegador.
  clearInterval(refreshTimer);
  showLobby(currentPlayer);
});
document.querySelector("#start-game").addEventListener("click", async () => {
  // El backend vuelve a comprobar que el jugador sea el anfitrión.
  try {
    showGame(await requestJson(`/api/games/${currentGame.id}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: currentPlayer.id }),
    }));
  } catch (error) {
    gameMessage.textContent = error.message;
    gameMessage.className = "form-message is-error";
  }
});

if (currentPlayer?.id) showLobby(currentPlayer);