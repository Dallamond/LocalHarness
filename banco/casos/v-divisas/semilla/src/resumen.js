import { totalFactura } from "./factura.js";

// resumen(facturas): {numero, total} de una lista de facturas (cada una, una lista de líneas).
export function resumen(facturas) {
  return { numero: facturas.length, total: facturas.reduce((a, f) => a + totalFactura(f), 0) };
}
