// posicionDe(filas, caracter): la primera aparición del carácter en el mapa (array de strings), en píxeles:
// {x: columna × 16, y: fila × 16}, contando columnas y filas desde 0; null si no está.
export const TILE = 16;

export function posicionDe(filas, caracter) {
  for (let fila = 0; fila < filas.length; fila++) {
    const col = filas[fila].indexOf(caracter);
    if (col !== -1) return { x: col * TILE, y: fila * TILE };
  }
  return null;
}

export function contar(filas, caracter) {
  return filas.join("").split(caracter).length - 1;
}
