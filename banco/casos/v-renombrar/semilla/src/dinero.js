// formatear(centimos) → '12,34 €'.
export function formatear(centimos) {
  return `${(centimos / 100).toFixed(2).replace(".", ",")} €`;
}
