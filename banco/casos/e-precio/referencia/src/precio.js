// Precio final en céntimos: primero el descuento (entre 0 y 50 %), luego el IVA; cada paso, al céntimo.
const MAX_DESCUENTO = 50;

export function desglose(base, ivaPct, descuentoPct) {
  if (base < 0) throw new Error("base negativa");
  const pct = Math.min(Math.max(descuentoPct, 0), MAX_DESCUENTO);
  const descuento = Math.round((base * pct) / 100);
  const neto = base - descuento;
  const iva = Math.round((neto * ivaPct) / 100);
  return { base, descuento, neto, iva, total: neto + iva };
}

export function precioFinal(base, ivaPct, descuentoPct) {
  return desglose(base, ivaPct, descuentoPct).total;
}
