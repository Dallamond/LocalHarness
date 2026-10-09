# Encargo: «Supersalto», un Mario Bros casero hecho parche a parche

Proyecto del modo 100 % local de LocalHarness: dos modelos locales lo construyen desde cero, sin ayuda. Es un
juego de plataformas 2D al estilo de Super Mario Bros (NES): correr, saltar, pisar goombas, golpear bloques «?»,
coger el champiñón, recoger monedas y llegar a la bandera. Gráficos sencillos (rectángulos de colores) en un
canvas de 256×224, como la NES.

## Cómo se juega
- Se abre `index.html` con doble clic. Sin dependencias, sin build, sin servidor: HTML y JavaScript con módulos ES.
- Flechas o A/D para moverse, Espacio, W o Flecha arriba para saltar, P para pausa.

## Arquitectura (obligatoria)
1. **La lógica es pura** y vive en `src/`: funciones que reciben datos y devuelven datos NUEVOS (no modifican lo
   que reciben), sin DOM, sin canvas, sin `Math.random` y sin `Date.now`.
2. **El dibujo y la entrada van aparte**: `src/render.js` dibuja, `src/entrada.js` lee el teclado y `src/main.js`
   junta todo con `requestAnimationFrame` y un paso fijo de 1/60 s.
3. **Un tile mide 16 px** (`TILE` de `src/mapa.js`). Coordenadas en píxeles; columna = `Math.floor(x / 16)`.
4. **Los niveles son texto.** Los diseños están en `docs/nivel-1.txt` y `docs/nivel-2.txt` y se copian TAL CUAL
   (mismos caracteres, mismas filas) en `src/niveles.js`. Caracteres:
   `#` suelo · `B` ladrillo · `?` bloque con moneda · `M` bloque con champiñón · `T` tubería ·
   `o` moneda suelta · `E` goomba · `K` koopa · `J` inicio del jugador · `F` bandera · `.` aire.
   Sólidos: `#`, `B`, `?`, `M`, `T` y `U` (bloque ya usado).
5. **Ningún archivo pasa de 200 líneas**; si crece, se parte en módulos.
6. Nombres de funciones, variables y comentarios en castellano.
7. **No se cambia la firma de una función que ya existe.** Si hace falta algo más, se añade una función nueva.

## Reglas de los tests
1. Cada parche trae tests en `tests/*.test.mjs` (solo `node:test` y `node:assert/strict`, módulos ES) y deja
   **todos** los tests pasando con `npm test`.
2. **Los tests se fabrican sus propios mapas** con `crearMapa([...filas])` de `src/mapa.js` (mapas pequeños de
   pocas filas escritos en el propio test). Nunca dependen del contenido de `src/niveles.js`, salvo el test de
   niveles.
3. Un test comprueba números concretos (entrada → salida esperada), no solo «que no falle».
4. Lo que se dibuja no se prueba con imágenes: se prueba la lógica que decide qué se dibuja.

## Reglas de cada parche
1. Cada parche suele traer DOS módulos independientes (A y B). Se pueden escribir a la vez: el código de A no
   importa el de B ni al revés, y el test de A solo importa A (y lo que ya existía).
2. `CHANGELOG.md` lleva una línea por parche: `- Parche NNN · DD/MM/AAAA · qué cambió`.
