// Descuento por volumen: menos de 10 unidades, 0 %; de 10 a 49, 5 %; de 50 a 99, 10 %; 100 o más, 15 %.
// totalConDescuento(unidades, precioCent) = Math.round(unidades × precioCent × (100 − porcentaje) / 100).
export function porcentaje(unidades) {
  if (unidades >= 100) return 15;
  if (unidades >= 50) return 10;
  if (unidades >= 10) return 5;
  return 0;
}

export function totalConDescuento(unidades, precioCent) {
  return Math.round((unidades * precioCent * (100 - porcentaje(unidades))) / 100);
}
