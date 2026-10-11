import { euros } from "./formato.js";

// vista(r): el resultado como HTML.
export function vista(r) {
  return [
    `<p class="propina">Propina: ${euros(r.propina)}</p>`,
    `<p class="total">Total: ${euros(r.total)}</p>`,
    `<p class="por-persona">Cada uno: ${euros(r.porPersona)}</p>`,
  ].join("\n");
}
