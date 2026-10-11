// formatearEuros(centimos) → '12,34 €'.
export function formatearEuros(centimos) {
  return `${(centimos / 100).toFixed(2).replace(".", ",")} €`;
}
