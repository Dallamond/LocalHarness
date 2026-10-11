// totalFactura(lineas): suma de precio × cantidad (céntimos, en euros).
export function totalFactura(lineas) {
  return lineas.reduce((a, l) => a + l.precio * l.cantidad, 0);
}
