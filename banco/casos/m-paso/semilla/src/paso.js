// paso(estado, entrada): un paso del juego. estado {x, vx}; entrada {izquierda, derecha} (teclas pulsadas).
// vx = 2 con derecha, -2 con izquierda, 0 con ninguna o con las dos; x += vx sin salir de 0..300.
export function crearEstado() {
  return { x: 0, vx: 0 };
}

export function paso(estado, entrada) {
  const vx = entrada.derecha && !entrada.izquierda ? 2 : entrada.izquierda && !entrada.derecha ? -2 : 0;
  const x = Math.min(300, Math.max(0, estado.x + vx));
  return { ...estado, x, vx };
}
