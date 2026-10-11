import { totalFactura } from "./factura.js";
import { convertir } from "./divisas.js";

// resumen(facturas): {numero, total} de una lista de facturas (cada una, una lista de líneas).
export function resumen(facturas) {
  return { numero: facturas.length, total: facturas.reduce((a, f) => a + totalFactura(f), 0) };
}

// resumenEn(facturas, moneda): el resumen con el total convertido de EUR a esa moneda.
export function resumenEn(facturas, moneda) {
  const r = resumen(facturas);
  return { ...r, total: convertir(r.total, "EUR", moneda) };
}
