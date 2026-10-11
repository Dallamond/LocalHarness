import { formatear } from "./dinero.js";

// lineaTicket(nombre, centimos) → 'nombre: 12,34 €'.
export function lineaTicket(nombre, centimos) {
  return `${nombre}: ${formatear(centimos)}`;
}
