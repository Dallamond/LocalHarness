// rango(a, b): los enteros de a a b, AMBOS incluidos; [] si a > b. suma(xs): suma de una lista.
export function rango(a, b) {
  const out = [];
  for (let i = a; i < b; i++) out.push(i);
  return out;
}

export function suma(xs) {
  return xs.reduce((x, y) => x + y, 0);
}
