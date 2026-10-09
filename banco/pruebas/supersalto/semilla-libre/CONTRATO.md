# Contrato de «Supersalto» (modalidad libre)

Es lo que el juego tiene que cumplir al final: nombres de archivo, funciones exportadas, firmas y números. Se
corrige con un examen oculto que importa estos módulos, así que los nombres, las firmas y los valores son
obligatorios. **Cómo llegar hasta aquí lo decidís vosotros**: el orden, los tests (los escribís vosotros, con
números concretos) y cómo partir el trabajo. Las secciones van en un orden razonable, pero no es obligatorio.

Cuando una sección dice «Edita» se refiere a un módulo de una sección anterior: se amplía sin cambiar su firma.

## 1. Mapa y rectángulos

- src/mapa.js exporta TILE = 16, SOLIDOS = ['#', 'B', '?', 'M', 'T', 'U'], crearMapa(filas) (filas = array de strings; devuelve {ancho: filas[0].length, alto: filas.length, tiles: copia del array}; lanza un Error si alguna fila tiene distinto ancho), tileEn(mapa, columna, fila) (el carácter; '#' si columna < 0, columna >= ancho o fila < 0; '.' si fila >= alto, para poder caer al vacío), esSolido(mapa, columna, fila) (true si tileEn está en SOLIDOS) y columnaDe(x) = Math.floor(x / TILE).

- src/rect.js exporta solapan(a, b) con rectángulos {x, y, ancho, alto}: true solo si se pisan de verdad (a.x < b.x + b.ancho && a.x + a.ancho > b.x, y lo mismo en y); tocarse por el borde NO es solapar.

## 2. Física y cámara

- src/fisica.js exporta GRAVEDAD = 0.5, VEL_MAX_CAIDA = 8 y aplicarGravedad(cuerpo), que devuelve un cuerpo NUEVO ({...cuerpo}) con vy = Math.min(cuerpo.vy + GRAVEDAD, VEL_MAX_CAIDA).

- src/camara.js exporta ANCHO_PANTALLA = 256, ALTO_PANTALLA = 224, camaraX(jugadorX, anchoMapaPx) = jugadorX - 128 recortado entre 0 y Math.max(0, anchoMapaPx - 256), y rangoColumnas(camX) = {desde: Math.floor(camX / 16), hasta: Math.floor((camX + 255) / 16)}.

## 3. Leer niveles y copiar los diseños

- src/nivel.js exporta parsearNivel(texto): parte el texto en líneas, quita el '\r' y las líneas vacías, y recorre cada carácter: 'J' → inicio {x: columna*16, y: fila*16}; 'o' → monedas [{x, y}]; 'E' → enemigos [{tipo: 'goomba', x, y}]; 'K' → enemigos [{tipo: 'koopa', x, y}]; 'F' → meta {x, y}; esos cinco caracteres se cambian por '.' en las filas. Devuelve {mapa: crearMapa(filasLimpias) de src/mapa.js, inicio, monedas, enemigos, meta}. Lanza un Error 'falta J' si no hay J y 'falta F' si no hay F.

- src/niveles.js exporta NIVELES = [nivel1, nivel2]: dos strings con template literal (comillas invertidas) que copian CARÁCTER A CARÁCTER docs/nivel-1.txt (14 filas de 56) y docs/nivel-2.txt (14 filas de 72), una fila por línea, sin espacios delante.

## 4. Colisiones en X y en Y

Los dos módulos usan esSolido y columnaDe de src/mapa.js y devuelven cuerpos nuevos. Un cuerpo es {x, y, ancho, alto, vx, vy, enSuelo}.

- src/colision-x.js exporta moverX(cuerpo, mapa): nx = x + vx; filas que ocupa: de Math.floor(y / 16) a Math.floor((y + alto - 1) / 16); si vx > 0, col = Math.floor((nx + ancho) / 16) y si algún tile (col, fila) es sólido → x = col*16 - ancho y vx = 0; si vx < 0, col = Math.floor(nx / 16) y si es sólido → x = (col + 1)*16 y vx = 0; si no choca, x = nx; con vx = 0 no cambia nada.

- src/colision-y.js exporta moverY(cuerpo, mapa): ny = y + vy; columnas que ocupa: de Math.floor(x / 16) a Math.floor((x + ancho - 1) / 16); si vy > 0, fila = Math.floor((ny + alto) / 16) y si algún tile es sólido → y = fila*16 - alto, vy = 0, enSuelo = true; si no choca → y = ny y enSuelo = false; si vy < 0, fila = Math.floor(ny / 16) y si algún tile es sólido → y = (fila + 1)*16, vy = 0 y además golpeTecho = {columna, fila} del primer tile sólido empezando por la izquierda; si no, y = ny. Devuelve {cuerpo, golpeTecho} (golpeTecho null si no golpea).

## 5. Entrada y velocidad horizontal

- src/entrada.js exporta crearEntrada() = {izquierda: false, derecha: false, saltar: false, pausa: false}, aplicarTecla(entrada, codigo, pulsada), pura, que devuelve una entrada nueva: 'ArrowLeft' y 'KeyA' → izquierda; 'ArrowRight' y 'KeyD' → derecha; 'Space', 'KeyW' y 'ArrowUp' → saltar; 'KeyP' → pausa; otro código devuelve una copia igual; y escucharTeclado(ventana, alCambiar), que añade keydown y keyup a ventana y llama a alCambiar(codigo, pulsada) (esta última no se prueba).

- src/movimiento.js exporta ACELERACION = 0.3, VEL_MAX = 2.5, FRICCION = 0.8 y velocidadHorizontal(vx, entrada): solo derecha → Math.min(vx + 0.3, 2.5); solo izquierda → Math.max(vx - 0.3, -2.5); ninguna o las dos → vx * 0.8, y 0 si su valor absoluto queda por debajo de 0.1.

## 6. Salto y monedas

- src/salto.js exporta FUERZA_SALTO = -8.5, CORTE_SALTO = -3, intentarSaltar(cuerpo, saltar) (si saltar y cuerpo.enSuelo → cuerpo nuevo con vy -8.5 y enSuelo false; si no, una copia igual) y cortarSalto(cuerpo, saltar) (si NO se mantiene saltar y vy < -3 → vy = -3, para que el salto sea más corto al soltar, como en Mario; si no, copia igual).

- src/monedas.js exporta recogerMonedas(jugador, monedas): cada moneda {x, y} ocupa el rectángulo {x, y, ancho: 16, alto: 16}; usa solapan de src/rect.js; devuelve {quedan: las que no tocan al jugador, recogidas: cuántas tocó}.

## 7. Jugador y bloques

- src/jugador.js exporta crearJugador(inicio) = {x: inicio.x + 2, y: inicio.y, ancho: 12, alto: 16, vx: 0, vy: 0, enSuelo: false, mirando: 1, grande: false} y actualizarJugador(jugador, entrada, mapa), que en este orden: vx = velocidadHorizontal (src/movimiento.js), intentarSaltar y cortarSalto (src/salto.js), aplicarGravedad (src/fisica.js), moverX (src/colision-x.js) y moverY (src/colision-y.js); mirando = 1 si vx > 0, -1 si vx < 0 y si no el de antes. Devuelve {jugador, golpeTecho}.

- src/bloques.js exporta golpearBloque(mapa, columna, fila): si el tile es '?' devuelve {mapa: un mapa NUEVO con ese tile cambiado a 'U', puntos: 200, sale: 'moneda'}; si es 'M' → {mapa nuevo con 'U', puntos: 0, sale: 'champi'}; cualquier otro tile → {mapa (el mismo), puntos: 0, sale: null}. Las filas son strings: se rehace la fila con slice.

## 8. Goombas y marcador

- src/goomba.js exporta crearGoomba({x, y}) = {tipo: 'goomba', x, y, ancho: 16, alto: 16, vx: -0.5, vy: 0, enSuelo: false, vivo: true, aplastado: 0} y actualizarGoomba(g, mapa): si vivo es false, solo aplastado + 1; si no, aplicarGravedad (src/fisica.js), moverX (src/colision-x.js) y, si el choque dejó vx = 0 y antes no era 0, vx = la de antes cambiada de signo (se da la vuelta); luego moverY (src/colision-y.js). Se cae por los bordes como en Mario.

- src/marcador.js exporta textoMarcador({puntos, monedas, mundo, tiempo, vidas}) = {puntos: String(puntos).padStart(6, '0'), monedas: 'x' + String(monedas).padStart(2, '0'), mundo, tiempo: String(tiempo).padStart(3, '0'), vidas: 'x' + vidas} y crearReloj(segundos) = {segundos, frames: 0} con ticReloj(reloj) (frames + 1; al llegar a 60, frames 0 y segundos - 1, sin bajar de 0).

## 9. Pisar o morir y vidas

- src/combate.js exporta resolverChoques(jugador, enemigos): para cada enemigo con vivo true que solapa (src/rect.js) con el jugador: si jugador.vy > 0 y (jugador.y + jugador.alto) - enemigo.y <= 8, lo pisa: ese enemigo pasa a vivo false, el jugador rebota con vy -5 y se suman 100 puntos; si no, el jugador muere. Los enemigos muertos no hacen nada. Devuelve {jugador, enemigos, puntos, muere}.

- src/vidas.js exporta perderVida(partida), que devuelve una partida nueva con vidas - 1 y estado 'muerto' (o 'fin' si quedan 0 vidas), sin tocar los puntos, y cayoAlVacio(jugador, mapa) = jugador.y > mapa.alto * 16.

## 10. Estado de la partida y dibujo

- src/partida.js exporta crearPartida(niveles) (carga niveles[0] con parsearNivel de src/nivel.js: jugador = crearJugador(inicio) de src/jugador.js, enemigos con crearGoomba de src/goomba.js para los 'goomba' y también para los 'koopa' de momento, puntos 0, contadorMonedas 0, vidas 3, reloj crearReloj(400) de src/marcador.js, camara 0, espera 0, estado 'jugando', y guarda niveles) y cargarNivel(partida, indice), que carga otro nivel conservando puntos, contadorMonedas y vidas.

- src/render.js exporta COLORES ({cielo: '#5c94fc', '#': '#c84c0c', B: '#a0522d', '?': '#fca044', M: '#fca044', U: '#888888', T: '#00a800', moneda: '#fce4a0', jugador: '#d82800', goomba: '#8b4513', bandera: '#ffffff'}) y dibujar(ctx, partida): pinta el cielo, solo los tiles de rangoColumnas(partida.camara) de src/camara.js (cada tile en (columna*16 - camara, fila*16)), las monedas, la bandera, los enemigos vivos, el jugador y, arriba, el texto de textoMarcador de src/marcador.js con ctx.fillText.

## 11. Paso del juego y página

- src/paso.js exporta paso(partida, entrada) que devuelve una partida nueva: en 'jugando' → actualizarJugador (src/jugador.js), si hay golpeTecho golpearBloque (src/bloques.js) sumando sus puntos y +1 a contadorMonedas si sale 'moneda'; actualizarGoomba a cada enemigo (src/goomba.js); recogerMonedas (src/monedas.js) sumando 200 puntos y 1 a contadorMonedas por cada una; resolverChoques (src/combate.js); si muere o cayoAlVacio (src/vidas.js) → perderVida y espera 120; ticReloj; camara = camaraX (src/camara.js). En 'muerto' → espera - 1 y al llegar a 0, cargarNivel (src/partida.js) del mismo nivel con estado 'jugando'. En 'fin' no hace nada.

- index.html: página con fondo negro, título «Supersalto», un canvas id «pantalla» de 256×224 centrado, escalado ×3 con CSS (width 768px, image-rendering: pixelated) y <script type="module" src="src/main.js">. src/main.js: importa NIVELES (src/niveles.js), crearPartida (src/partida.js), paso (src/paso.js), dibujar (src/render.js) y crearEntrada, aplicarTecla y escucharTeclado (src/entrada.js); guarda la entrada en una variable que actualiza escucharTeclado(window, ...) y hace un bucle con requestAnimationFrame y paso fijo de 1000/60 ms acumulando el tiempo.

## 12. Bandera y fin de nivel

- src/meta.js exporta tocaMeta(jugador, meta) (solapan de src/rect.js con el rectángulo {x: meta.x + 6, y: meta.y - 144, ancho: 4, alto: 160}, el mástil de la bandera) y puntosMeta(jugador, meta) = 5000 si jugador.y < meta.y - 96, 2000 si < meta.y - 48, y si no 400 (más arriba, más puntos, como en Mario).

- src/fin-nivel.js exporta terminarNivel(partida): suma partida.reloj.segundos * 50 puntos (bonus de tiempo), y si quedan niveles después de partida.nivel → estado 'meta' y espera 180; si era el último → estado 'victoria'.

## 13. Meta en el paso y pantallas de texto

- Edita src/paso.js (sin cambiar la firma de paso): en 'jugando', si tocaMeta (src/meta.js) → suma puntosMeta y llama a terminarNivel (src/fin-nivel.js); en 'meta' → espera - 1 y al llegar a 0 cargarNivel (src/partida.js) del nivel siguiente con estado 'jugando'; si el reloj llega a 0 segundos, el jugador muere como si cayera.

- src/pantallas.js exporta textoPantalla(partida), pura, que devuelve null en 'jugando' y si no un array de líneas: 'pausa' → ['PAUSA', 'pulsa P para seguir']; 'muerto' → ['MUNDO 1-' + (nivel + 1), 'x ' + vidas]; 'fin' → ['FIN DEL JUEGO', 'pulsa Espacio']; 'meta' → ['¡NIVEL SUPERADO!', 'puntos ' + puntos]; 'victoria' → ['¡HAS GANADO!', 'puntos ' + puntos, 'pulsa Espacio'].

## 14. Pausa, reinicio y pantallas dibujadas

- src/control.js exporta controlar(partida, entrada, anterior), pura, donde anterior es la entrada del paso anterior (para detectar el momento de pulsar): si pausa pasa de false a true, 'jugando' ↔ 'pausa'; en 'fin' o 'victoria', si saltar pasa de false a true, devuelve crearPartida(partida.niveles) de src/partida.js; si no, la partida igual.

- Edita src/render.js (sin cambiar la firma de dibujar): si textoPantalla (src/pantallas.js) no es null, pinta encima un rectángulo negro semitransparente (ctx.globalAlpha 0.7) de 256×224 y las líneas centradas con ctx.textAlign = 'center' una debajo de otra cada 16 px.

## 15. Champiñón y crecer

- src/champi.js exporta crearChampi(columna, fila) = {tipo: 'champi', x: columna*16, y: fila*16 - 16, ancho: 16, alto: 16, vx: 1, vy: 0, enSuelo: false, vivo: true} y actualizarChampi(c, mapa): como el goomba (gravedad, moverX dándose la vuelta al chocar, moverY) pero hacia la derecha.

- src/tamano.js exporta crecer(jugador) (si no es grande: grande true, alto 32, y - 16; si ya es grande, igual) y recibirGolpe(jugador) → si es grande: {jugador: pequeño (grande false, alto 16, y + 16, invencible 120), muere: false}; si es pequeño y invencible > 0: {jugador, muere: false}; si no: {jugador, muere: true}; y bajarInvencible(jugador) (invencible - 1 sin bajar de 0).

## 16. Champiñón en el juego y ladrillos que se rompen

- Edita src/paso.js (sin cambiar la firma): si golpearBloque da sale 'champi', añade crearChampi (src/champi.js) a partida.objetos (crea el array si no existe); actualizarChampi a cada objeto; si el jugador solapa un champi lo quita, llama a crecer (src/tamano.js) y suma 1000 puntos; en vez de morir directamente al chocar con un enemigo usa recibirGolpe (src/tamano.js); cada paso bajarInvencible. En src/render.js dibuja los objetos tipo 'champi' en rojo '#e45c10' y, si el jugador es invencible, que parpadee (no lo pintes en los pasos con Math.floor(invencible / 4) % 2 === 1).

- src/ladrillo.js exporta romperLadrillo(mapa, columna, fila, grande): si el tile es 'B' y grande es true → {mapa nuevo con '.' en ese sitio, roto: true, puntos: 50}; si no → {mapa igual, roto: false, puntos: 0}; y trozosLadrillo(columna, fila) = 4 trozos [{x, y, vx, vy}] que salen de las esquinas del tile con vx -1, 1, -1, 1 y vy -6, -6, -3, -3.

## 17. Koopa y caparazón

- src/koopa.js exporta crearKoopa({x, y}) = {tipo: 'koopa', x, y: y - 8, ancho: 16, alto: 24, vx: -0.5, vy: 0, enSuelo: false, vivo: true, modo: 'andando'} y actualizarKoopa(k, mapa): en 'andando' y 'caparazon_rodando' se mueve como el goomba (gravedad, moverX dándose la vuelta al chocar, moverY); en 'caparazon' está quieto (vx 0) pero cae con gravedad.

- src/caparazon.js exporta pisarKoopa(koopa, jugador): si modo es 'andando' → modo 'caparazon', alto 16, y + 8, vx 0, puntos 100; si es 'caparazon' → modo 'caparazon_rodando', vx 4 si el jugador está a la izquierda del centro del koopa y -4 si está a la derecha, puntos 400; si es 'caparazon_rodando' → modo 'caparazon', vx 0, puntos 100. Devuelve {koopa, puntos}. Y caparazonGolpea(caparazon, enemigo) = true si el caparazón rueda (modo 'caparazon_rodando'), el enemigo está vivo, no es el mismo y solapan (src/rect.js).

## 18. Koopas en el juego y sprites

- Edita src/partida.js y src/paso.js (sin cambiar firmas): los enemigos 'koopa' se crean con crearKoopa (src/koopa.js) y se mueven con actualizarKoopa; en los choques con un koopa se usa pisarKoopa (src/caparazon.js) en vez de matarlo; un caparazón quieto que el jugador toca de lado se lanza (como pisarlo); un caparazón rodando mata a los enemigos que golpea (caparazonGolpea) sumando 500 puntos cada uno y daña al jugador si lo toca de lado.

- src/sprites.js exporta SPRITES con dibujos de pixel art como arrays de strings de 16 caracteres (un carácter por píxel, '.' transparente, y una letra por color) para 'jugador' (12 de ancho de dibujo centrado en 16, 16 de alto: gorra roja, cara, peto azul), 'goomba' (16×16, marrón con ojos) y 'moneda' (16×16), una PALETA {letra: color} y pixelesSprite(nombre) que devuelve la lista [{x, y, color}] de píxeles no transparentes.

## 19. Dibujo con sprites y sonido

- Edita src/render.js (sin cambiar la firma de dibujar): el jugador, los goombas y las monedas se pintan con pixelesSprite (src/sprites.js), un fillRect de 1×1 por píxel (espejado en x si jugador.mirando es -1); si el jugador es grande, se pinta el sprite estirado al doble de alto.

- src/sonido.js exporta NOTAS, una tabla pura {salto: [{frecuencia, duracion}], moneda: [...], pisar: [...], champi: [...], muerte: [...], meta: [...]} con frecuencias en Hz entre 100 y 2000 y duraciones en segundos entre 0.03 y 0.5 (moneda: [{frecuencia: 988, duracion: 0.08}, {frecuencia: 1319, duracion: 0.3}], como la de Mario), y crearSonido(contextoAudio) que devuelve tocar(nombre), que con un OscillatorNode de onda 'square' toca las notas una detrás de otra (no se prueba).

## 20. Sonido en el juego y eventos

- Edita src/paso.js (sin cambiar la firma): la partida nueva lleva eventos, un array con lo que pasó en ese paso ('salto', 'moneda', 'pisar', 'champi', 'muerte', 'meta'), vacío si no pasó nada.

- Edita src/main.js: crea un AudioContext al primer keydown (los navegadores no dejan antes), crea tocar con crearSonido (src/sonido.js) y, tras cada paso, llama a tocar por cada evento de partida.eventos.

## 21. Correr y vida extra

- Edita src/entrada.js (sin cambiar firmas): la entrada lleva también correr ('ShiftLeft', 'ShiftRight' y 'KeyJ'), false en crearEntrada. src/movimiento.js añade VEL_CORRER = 3.5 y velocidadConCorrer(vx, entrada), que es como velocidadHorizontal pero con tope 3.5 si entrada.correr es true. Usa velocidadConCorrer en src/jugador.js en vez de velocidadHorizontal.

- src/vida-extra.js exporta contarMoneda(partida): contadorMonedas + 1, y al llegar a 100 vuelve a 0 y vidas + 1.

## 22. Moneda que salta del bloque y puntos flotantes

- src/efectos.js exporta crearMonedaSalto(columna, fila) = {tipo: 'moneda_salto', x: columna*16, y: fila*16 - 16, vy: -6, vida: 30} y actualizarEfecto(e) (primero y = y + vy, luego vy = vy + 0.5, y vida - 1) y vivos(efectos) (los que tienen vida > 0).

- src/flotantes.js exporta crearFlotante(x, y, texto) = {x, y, texto, vida: 45} y actualizarFlotante(f) (y - 1, vida - 1).

## 23. Estrella de invencibilidad

- src/estrella.js exporta crearEstrella(columna, fila) = {tipo: 'estrella', x: columna*16, y: fila*16 - 16, ancho: 16, alto: 16, vx: 1.5, vy: -5, enSuelo: false, vivo: true} y actualizarEstrella(e, mapa): gravedad, moverX dándose la vuelta al chocar, moverY y, si toca suelo, vy = -5 (va botando).

- src/poderes.js exporta darEstrella(jugador) (estrella = 600 pasos), conEstrella(jugador) (estrella > 0) y bajarEstrella(jugador) (estrella - 1 sin bajar de 0).

## 24. Flor de fuego y bolas de fuego

- src/flor.js exporta crearFlor(columna, fila) = {tipo: 'flor', x: columna*16, y: fila*16 - 16, ancho: 16, alto: 16, vivo: true} (no se mueve) y darFuego(jugador) (si es grande: fuego true; si es pequeño: crecer de src/tamano.js).

- src/fuego.js exporta lanzarFuego(jugador) = {tipo: 'fuego', x: jugador.x + (jugador.mirando > 0 ? jugador.ancho : -8), y: jugador.y + 4, ancho: 8, alto: 8, vx: 4 * jugador.mirando, vy: 0, vivo: true, botes: 0} y actualizarFuego(f, mapa): gravedad, moverX (si choca en x, vivo false), moverY (si toca suelo, vy -4 y botes + 1; con 4 botes, vivo false).

## 25. Planta piraña

- src/pirana.js exporta crearPirana(columna, fila) = {tipo: 'pirana', x: columna*16 + 8, yBase: fila*16, y: fila*16, ancho: 16, alto: 24, fase: 0, vivo: true} y actualizarPirana(p, jugadorX): fase + 1 y vuelve a 0 a los 240; con fase < 60 sube (y = yBase - fase * 0.4), de 60 a 119 está arriba (y = yBase - 24), de 120 a 179 baja (y = yBase - 24 + (fase - 120) * 0.4), de 180 a 239 está escondida (y = yBase); si está escondida y el jugador está a menos de 24 px en x de la planta, no sale (fase se queda en 180).

- src/tuberias.js exporta bocasTuberia(mapa): lista de {columna, fila} de cada boca de tubería (un 'T' cuyo tile de arriba no es 'T' y cuyo tile de la izquierda no es 'T').

## 26. Decorado de fondo

- src/fondo.js exporta decorado(anchoMapaPx): lista fija (sin azar) de nubes {tipo: 'nube', x, y} cada 192 px empezando en x 64 (mientras x < anchoMapaPx) con y alternando 24 y 40, y colinas {tipo: 'colina', x, y: 160} cada 384 px empezando en x 0; y posicionParalaje(x, camara, factor) = x - camara * factor (nubes 0.5, colinas 0.75).

- Edita src/render.js (sin cambiar la firma): antes de los tiles pinta el decorado con paralaje (nubes blancas de 32×16, colinas '#00a800' de 48×32 escalonadas y un arbusto '#80d010' junto a cada colina).

## 27. Nivel 3 subterráneo

- src/niveles.js: añade a NIVELES un tercer nivel diseñado por vosotros de 64 columnas y 14 filas, subterráneo: techo de ladrillos 'B' en la fila 0, suelo '#' en las filas 12 y 13 con 3 huecos de 2 o 3 columnas, columnas de ladrillos a distintas alturas, 10 monedas 'o', 2 bloques '?', 1 'M', 6 'E' y 1 'K', la 'J' en la columna 2 fila 11 y la 'F' en la columna 61 fila 11 sobre suelo.

- src/temas.js exporta temaNivel(indice) = {cielo: '#000000', suelo: '#0070ec', ladrillo: '#0070ec'} para el índice 2 y {cielo: '#5c94fc', suelo: '#c84c0c', ladrillo: '#a0522d'} para los demás. Usa temaNivel en src/render.js.

## 28. Pantalla de título y récord

- src/titulo.js exporta textoTitulo(record) = ['SUPERSALTO', '1 JUGADOR', 'RÉCORD ' + String(record).padStart(6, '0'), 'pulsa Espacio']; y en src/control.js, con estado 'titulo', Espacio recién pulsado empieza la partida (crearPartida).

- src/record.js exporta nuevoRecord(record, puntos) = Math.max(record, puntos) y esRecord(record, puntos) = puntos > record (lógica pura; localStorage solo en src/main.js y dentro de try/catch). En src/main.js el juego empieza en la pantalla de título y al llegar a 'fin' o 'victoria' guarda el récord.

## 29. Golpe de bloque y enemigos encima

- src/rebote.js exporta crearRebote(columna, fila) = {columna, fila, paso: 0}, avanzar(rebote) (paso + 1) y desplazamiento(rebote): 0 si paso es 0 o 8 o más (un 0 de verdad, no -0), -paso si paso va de 1 a 4 y -(8 - paso) si va de 5 a 7.

- src/golpe-abajo.js exporta enemigosEncima(enemigos, columna, fila): los enemigos vivos cuya parte de abajo (y + alto) está entre fila*16 - 2 y fila*16 + 2 y que se solapan en x con el tile (columna*16 a columna*16 + 16). En src/paso.js, al golpear un bloque desde abajo, esos enemigos mueren (+100), como en Mario.
