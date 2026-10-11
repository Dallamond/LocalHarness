// euros(centimos) → '1.234,50 €' (miles con punto, decimales con coma).
export function euros(centimos) {
  const signo = centimos < 0 ? "-" : "";
  const abs = Math.abs(centimos);
  const enteros = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${signo}${enteros},${String(abs % 100).padStart(2, "0")} €`;
}
