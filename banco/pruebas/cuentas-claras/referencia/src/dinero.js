// Importes en céntimos enteros: nada de decimales flotantes en el dinero.
export function aCentimos(valor) {
  if (typeof valor === "number") {
    if (!Number.isFinite(valor)) throw new Error("importe no válido");
    return Math.round(valor * 100);
  }
  let t = String(valor ?? "").replace(/€/g, "").replace(/\s/g, "");
  let signo = 1;
  if (t.startsWith("-") || t.startsWith("+")) {
    signo = t[0] === "-" ? -1 : 1;
    t = t.slice(1);
  }
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(t)) throw new Error("importe no válido");
  const [entero, dec = ""] = t.split(".");
  return signo * (Number(entero) * 100 + Number(dec.padEnd(2, "0")));
}

export function formatear(centimos) {
  const signo = centimos < 0 ? "-" : "";
  const abs = Math.abs(centimos);
  const entero = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${signo}${entero},${String(abs % 100).padStart(2, "0")} €`;
}
