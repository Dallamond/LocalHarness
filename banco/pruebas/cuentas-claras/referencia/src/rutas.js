export const VISTAS = ["resumen", "movimientos", "nuevo", "presupuestos", "importar"];

export function leerRuta(hash) {
  const [camino, consulta = ""] = String(hash || "").replace(/^#/, "").replace(/^\//, "").split("?");
  const vista = camino || "resumen";
  if (!VISTAS.includes(vista)) return { vista: "no-encontrada", params: {} };
  return { vista, params: Object.fromEntries(new URLSearchParams(consulta)) };
}

export function crearRuta(vista, params = {}) {
  const pares = Object.keys(params).sort().filter((k) => params[k] !== undefined && params[k] !== "")
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`);
  return `#/${vista}${pares.length ? `?${pares.join("&")}` : ""}`;
}
