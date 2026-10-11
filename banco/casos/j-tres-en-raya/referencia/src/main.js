import { crearTablero, ganador, jugadaIA, jugar } from "./tablero.js";

let t = crearTablero();
const casillas = [...document.querySelectorAll("#tablero button")];
const estado = document.getElementById("estado");

function pintar() {
  casillas.forEach((b, i) => { b.textContent = t[i] ?? ""; });
  const g = ganador(t);
  estado.textContent = g === "empate" ? "Empate" : g ? `Gana ${g}` : "Te toca (X)";
}

casillas.forEach((b, i) => b.addEventListener("click", () => {
  if (t[i] !== null || ganador(t)) return;
  t = jugar(t, i, "X");
  if (!ganador(t)) t = jugar(t, jugadaIA(t, "O"), "O");
  pintar();
}));
document.getElementById("otra").addEventListener("click", () => { t = crearTablero(); pintar(); });
pintar();
