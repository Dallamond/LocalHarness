# Autopiloto 100 % local de «Bitácora del taller»

Lo hace el «Jefe local», sin Claude. Elige los archivos el modelo rápido; planifica y revisa el fuerte; los bloques
se reparten entre los dos. Empieza por lo que dejó a medias el autopiloto 2, que se paró al acabarse la cuota de
Claude. Con `--continuo`, cuando se acaba la lista el modelo fuerte propone los parches siguientes y los añade al
final de este archivo, así que se pueden leer, corregir o borrar.

Una línea «- texto» por parche. Lo que no empiece por «- » se ignora.

- Atajos de teclado: atajos.js con «/» que enfoca el buscador o lleva a buscar.html, «n» que cambia el modo noche, «?» que abre un diálogo accesible con la lista de atajos y Escape que lo cierra. No actúa si el foco está en un input o textarea. Exporta accionPara(tecla, enFormulario) como función pura que devuelve 'buscar', 'noche', 'ayuda', 'cerrar' o null. tests/atajos.test.mjs prueba accionPara con todas las combinaciones y que index.html carga atajos.js.
- Colores en variables: sustituye los colores hex repetidos en styles.css por variables --color-* definidas una vez en :root de base.css, también para el modo noche. tools/colores.mjs exporta hexFuera(css), que devuelve los hex que quedan fuera de :root y de los bloques de noche. tests/colores.test.mjs prueba hexFuera con un CSS de ejemplo y exige que en styles.css queden 3 hex fuera como mucho.
- Calendario de parches: calendario.js exporta agruparPorDia(entradas), que recibe [{numero, fecha, resumen}] como las de changelog.js y devuelve [{fecha, parches: [...]}] ordenado de la fecha más nueva a la más antigua. calendario.html lo muestra como una tabla accesible (caption, th scope) con el número de parches de cada día. tests/calendario.test.mjs prueba agruparPorDia con 6 casos: lista vacía, un día, varios días, orden, fechas repetidas y entrada sin fecha.
- Peso de las páginas: tools/peso.mjs exporta pesoDe(html, leer), que suma los bytes de la página y de sus CSS y JS locales (link href y script src), y escribe peso.json con todas las páginas. tests/peso.test.mjs prueba pesoDe con un lector falso y exige que ninguna página real pase de 200 KB.
- Enlaces de la entrada anterior y siguiente en el blog generados solos: tools/navblog.mjs exporta enlacesNav(numeros, n), que devuelve {anterior, siguiente} (null en los extremos). Se ejecuta en pretest y pone esos enlaces en cada blog/parche-NNN.html entre las marcas <!-- auto:nav --> y <!-- /auto:nav -->. tests/navblog.test.mjs prueba enlacesNav con 5 casos: el primero, el último, uno del medio, una lista con huecos y una lista de uno.
