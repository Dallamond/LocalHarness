import { convertir } from "./divisas.js";

// totalFactura(lineas): suma de precio × cantidad (céntimos, en euros).
export function totalFactura(lineas) {
  return lineas.reduce((a, l) => a + l.precio * l.cantidad, 0);
}

// totalFacturaEn(lineas, moneda): el total convertido de EUR a esa moneda.
export function totalFacturaEn(lineas, moneda) {
  return convertir(totalFactura(lineas), "EUR", moneda);
}
