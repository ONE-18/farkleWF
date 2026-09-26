const DEVICE_ID_KEY = "farkle.device_id";
const PLAYER_KEY = "farkle.player";

function getDeviceId() {
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
const savedPlayer = JSON.parse(localStorage.getItem(PLAYER_KEY) || "null");

if (savedPlayer?.name) nameInput.value = savedPlayer.name;

form.addEventListener("submit", async (event) => {
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
    message.textContent = `Listo, ${player.name}. La mesa te espera.`;
    message.className = "form-message is-success";
  } catch (error) {
    message.textContent = error.message;
    message.className = "form-message is-error";
  }
});