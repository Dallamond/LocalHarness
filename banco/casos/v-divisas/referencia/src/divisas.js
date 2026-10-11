// Monedas: unidades de cada una por 1 euro.
export const TASAS = { EUR: 1, USD: 1.1, GBP: 0.85 };

export function convertir(centimos, de, a) {
  if (!(de in TASAS) || !(a in TASAS)) throw new Error("moneda desconocida");
  return Math.round((centimos / TASAS[de]) * TASAS[a]);
}
