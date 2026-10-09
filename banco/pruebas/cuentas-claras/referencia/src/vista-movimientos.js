import { formatear } from "./dinero.js";
import { escapar } from "./html.js";

export function tablaMovimientos(lista) {
  if (!lista.length) return '<p class="vacio">No hay movimientos</p>';
  const filas = lista.map((m) => `<tr data-id="${m.id}"><td>${m.fecha}</td><td>${escapar(m.concepto)}</td>`
    + `<td>${escapar(m.categoria)}</td><td class="${m.centimos < 0 ? "gasto" : "ingreso"}">${formatear(m.centimos)}</td>`
    + `<td><button type="button" data-borrar="${m.id}">Borrar</button></td></tr>`);
  return `<table class="movimientos"><thead><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Importe</th>`
    + `<th></th></tr></thead><tbody>${filas.join("")}</tbody></table>`;
}
