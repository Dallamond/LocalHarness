// paso(estado, entrada): un paso del juego. estado {x, vx, pausado, pausaAntes}; entrada {izquierda, derecha,
// pausa} (teclas pulsadas). vx = 2 con derecha, -2 con izquierda, 0 con ninguna o con las dos; x += vx sin salir de
// 0..300. Al pulsar pausa (de no pulsada a pulsada) se alterna `pausado`; pausado, x y vx no cambian.
export function crearEstado() {
  return { x: 0, vx: 0, pausado: false, pausaAntes: false };
}

export function paso(estado, entrada) {
  const pulsada = !!entrada.pausa;
  const pausado = pulsada && !estado.pausaAntes ? !estado.pausado : !!estado.pausado;
  if (pausado) return { ...estado, pausado, pausaAntes: pulsada };
  const vx = entrada.derecha && !entrada.izquierda ? 2 : entrada.izquierda && !entrada.derecha ? -2 : 0;
  const x = Math.min(300, Math.max(0, estado.x + vx));
  return { ...estado, x, vx, pausado, pausaAntes: pulsada };
}
