# «Supersalto», modalidad libre: 8 hitos grandes en vez de 40 parches detallados

Mide planificación: el contrato (CONTRATO.md, en la semilla) dice QUÉ tiene que existir al final; cómo partirlo,
en qué orden y con qué tests lo decide el agente. Se corrige con el mismo examen oculto que la modalidad guiada.

Una línea «- texto» por parche. Lo que no empiece por «- » se ignora.
- Hito 1 · Motor. Lee ENCARGO.md y CONTRATO.md enteros. Implementa las secciones 1 a 4 del contrato (mapa, rectángulos, física, cámara, niveles y colisiones) con tus propios tests en tests/ (números concretos, mapas pequeños escritos en el test). Antes de escribir código, apunta en docs/PLAN.md cómo vas a repartir el contrato en los 8 hitos.
- Hito 2 · Jugador. Implementa las secciones 5 a 7 del contrato (entrada, movimiento, salto, monedas, jugador y bloques) con tus propios tests. Revisa que lo del hito 1 sigue cumpliendo el contrato.
- Hito 3 · Enemigos y partida. Implementa las secciones 8 a 10 del contrato (goombas, marcador, combate, vidas, partida y dibujo) con tus propios tests.
- Hito 4 · Juego jugable. Implementa las secciones 11 a 14 del contrato (paso, página, bandera, fin de nivel, pantallas, pausa y reinicio). Al acabar, index.html tiene que abrir un juego que se puede jugar del principio al final del nivel 1. Añade un test que dé 3000 pasos con los niveles reales sin romperse.
- Hito 5 · Champiñón y koopas. Implementa las secciones 15 a 18 del contrato con tus propios tests.
- Hito 6 · Sprites, sonido y extras. Implementa las secciones 19 a 23 del contrato con tus propios tests.
- Hito 7 · Más contenido. Implementa las secciones 24 a 29 del contrato con tus propios tests.
- Hito 8 · Revisión final. Relee CONTRATO.md sección por sección y comprueba cada nombre, firma y número contra src/; busca imports rotos, código de Node en el navegador y funciones que modifican lo que reciben. Arregla lo que falle sin cambiar firmas y deja todos los tests pasando.
