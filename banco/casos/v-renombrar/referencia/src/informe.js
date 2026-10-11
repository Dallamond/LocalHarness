import { formatearEuros } from "./dinero.js";
import { lineaTicket } from "./ticket.js";

// informe(items): una línea por item y la del total.
export function informe(items) {
  const total = items.reduce((a, i) => a + i.centimos, 0);
  return [...items.map((i) => lineaTicket(i.nombre, i.centimos)), `TOTAL ${formatearEuros(total)}`].join("\n");
}
