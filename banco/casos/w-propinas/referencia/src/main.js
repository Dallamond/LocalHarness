import { calcular } from "./propinas.js";
import { vista } from "./vista.js";

const $ = (id) => document.getElementById(id);
const aCentimos = (texto) => Math.round(Number(String(texto).replace(",", ".")) * 100) || 0;

function pintar() {
  try {
    const r = calcular(aCentimos($("cuenta").value), Number($("porcentaje").value), Number($("personas").value));
    $("resultado").innerHTML = vista(r);
  } catch (e) {
    $("resultado").textContent = e.message;
  }
}

for (const id of ["cuenta", "porcentaje", "personas"]) $(id).addEventListener("input", pintar);
pintar();
