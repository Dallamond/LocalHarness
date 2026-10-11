// proximaCita(citas, ahora): de una lista de citas {titulo, fecha} (fecha ISO 'AAAA-MM-DDTHH:MM'), la de fecha más
// temprana que sea igual o posterior a `ahora`; null si no hay ninguna. La lista puede venir desordenada.
export function proximaCita(citas, ahora) {
  let mejor = null;
  for (const c of citas) if (c.fecha >= ahora && (mejor === null || c.fecha < mejor.fecha)) mejor = c;
  return mejor;
}
