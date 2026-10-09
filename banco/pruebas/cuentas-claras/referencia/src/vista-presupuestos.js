import { formatear } from "./dinero.js";
import { escapar } from "./html.js";
import { CATEGORIAS } from "./movimientos.js";

export function vistaPresupuestos(estados) {
  const filas = estados.map((e) => `<div class="presupuesto ${e.estado}" data-categoria="${escapar(e.categoria)}">`
    + `<span>${escapar(e.categoria)}</span> <progress value="${Math.min(e.porcentaje, 100)}" max="100"></progress>`
    + ` <span>${formatear(e.gastado)} de ${formatear(e.limite)} (${e.porcentaje} %)</span></div>`).join("");
  const opciones = CATEGORIAS.filter((c) => c !== "ingresos").map((c) => `<option value="${c}">${c}</option>`).join("");
  return `<section class="presupuestos">${filas || '<p class="vacio">Sin presupuestos</p>'}`
    + `<form id="form-presupuesto"><label>Categoría <select name="categoria">${opciones}</select></label>`
    + `<label>Límite <input name="importe" inputmode="decimal"></label><button>Guardar</button></form></section>`;
}
