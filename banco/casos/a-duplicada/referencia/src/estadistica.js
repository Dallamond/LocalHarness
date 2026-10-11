// media(xs): media aritmética redondeada a 2 decimales (Math.round(x × 100) / 100); 0 si la lista está vacía.
// mediana(xs): el valor del medio de la lista ordenada (la media de los dos del medio si son pares).
export function mediana(xs) {
  const o = [...xs].sort((a, b) => a - b);
  const m = Math.floor(o.length / 2);
  return o.length % 2 ? o[m] : (o[m - 1] + o[m]) / 2;
}

export function media(xs) {
  if (!xs.length) return 0;
  return Math.round((xs.reduce((a, b) => a + b, 0) / xs.length) * 100) / 100;
}
