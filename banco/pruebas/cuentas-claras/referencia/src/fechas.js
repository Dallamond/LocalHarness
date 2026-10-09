const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
  "noviembre", "diciembre"];

export function diasDelMes(mes) {
  const [a, m] = mes.split("-").map(Number);
  if (m === 2) return (a % 4 === 0 && a % 100 !== 0) || a % 400 === 0 ? 29 : 28;
  return [4, 6, 9, 11].includes(m) ? 30 : 31;
}

export function esFechaValida(texto) {
  if (typeof texto !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(texto)) return false;
  const m = Number(texto.slice(5, 7));
  const d = Number(texto.slice(8, 10));
  return m >= 1 && m <= 12 && d >= 1 && d <= diasDelMes(texto.slice(0, 7));
}

export const mesDe = (fecha) => fecha.slice(0, 7);

export function sumarMeses(mes, n) {
  const [a, m] = mes.split("-").map(Number);
  const total = a * 12 + (m - 1) + n;
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, "0")}`;
}

export const nombreMes = (mes) => `${MESES[Number(mes.slice(5, 7)) - 1]} ${mes.slice(0, 4)}`;
