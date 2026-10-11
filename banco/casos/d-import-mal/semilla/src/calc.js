// Calculadora: sumar(a, b), restar(a, b) y media(xs) (0 si la lista está vacía).
export const sumar = (a, b) => a + b;
export const restar = (a, b) => a - b;

export function media(xs) {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}
