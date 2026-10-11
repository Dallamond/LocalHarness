// calcular(cuentaCent, pct, personas) → {propina, total, porPersona} en céntimos.
export function calcular(cuentaCent, pct, personas) {
  if (!Number.isInteger(personas) || personas < 1) throw new Error("personas no válidas");
  const propina = Math.round((cuentaCent * pct) / 100);
  const total = cuentaCent + propina;
  return { propina, total, porPersona: Math.ceil(total / personas) };
}
