import { formatear } from "./dinero.js";
import { nombreMes } from "./fechas.js";
import { escapar } from "./html.js";
import { evolucion, resumenMes } from "./resumen.js";
import { graficoBarras } from "./grafico.js";

export function vistaResumen(estado, mes) {
  const r = resumenMes(estado.movimientos, mes);
  const cats = r.porCategoria.map((c) => `<li data-categoria="${escapar(c.categoria)}">${escapar(c.categoria)}`
    + ` <span>${formatear(c.centimos)}</span></li>`).join("");
  return `<section class="resumen" data-mes="${mes}"><h1>${nombreMes(mes)}</h1>`
    + `<p class="ingresos">Ingresos <strong>${formatear(r.ingresos)}</strong></p>`
    + `<p class="gastos">Gastos <strong>${formatear(r.gastos)}</strong></p>`
    + `<p class="saldo">Saldo <strong>${formatear(r.saldo)}</strong></p>`
    + `<ul class="categorias">${cats}</ul>${graficoBarras(evolucion(estado.movimientos, mes, 6))}</section>`;
}
