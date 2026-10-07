# Lista de parches para «Bitácora del taller» (autopiloto)

Una línea «- texto» por parche, en orden. Cada uno trae su entrada de blog poética (lo dice ENCARGO.md).
Puedes editarla antes de lanzar: lo que no empiece por «- » se ignora.

- Modo noche: un interruptor en la cabecera que cambia a una paleta oscura de taller de noche (madera oscura, tinta clara) y se recuerda en localStorage; los tests comprueban que el botón existe y que styles.css define la paleta oscura.
- Pie de página común en todas las páginas (portada, libro y blog) con el número del último parche leído del CHANGELOG mediante JavaScript, y un test que comprueba que todas las páginas tienen el pie.
- Sección «Herramientas del taller» en la portada: seis tarjetas (gubia, formón, cepillo, pluma, tintero, lija) con un párrafo poético corto cada una y una ilustración hecha solo con CSS o SVG en línea, sin imágenes externas.
- Página «Glosario» (glosario.html) con 15 términos de carpintería y escritura definidos en tono poético, ordenados alfabéticamente, con un buscador que filtra en vivo; test de que hay 15 términos y el buscador existe.
- Portada del blog mejorada: cada entrada muestra fecha, título y los dos primeros versos del poema; añade un enlace «Entrada anterior / siguiente» dentro de cada parche-NNN.html y un test que comprueba esos enlaces.
- Página «Taller abierto» (taller.html) con un formulario de contacto accesible (nombre, correo, mensaje) que valida en el navegador y muestra un mensaje de agradecimiento sin enviar nada; tests de que los campos tienen label y required.
- Animación sutil de «tinta que se seca»: los títulos h1 y h2 aparecen con un trazo de tinta al cargar, respetando prefers-reduced-motion; test de que la regla de reduced-motion existe.
- Libro, capítulo dos: añade al libro un segundo capítulo de al menos 800 palabras que continúe el relato del primero, con índice de capítulos al principio del libro.
- Accesibilidad: enlace «Saltar al contenido», foco visible en todos los botones y enlaces, atributos lang y aria correctos, y un test que revisa que cada página tiene un único h1 y el enlace de salto.
- Galería «Piezas terminadas» (galeria.html): doce piezas inventadas del taller con nombre, madera, medidas y una frase poética, en una rejilla que en el móvil pasa a una columna; un clic abre la ficha ampliada en un diálogo accesible.
- Calendario de estaciones: una sección en la portada que cambia el saludo y un detalle de color según la estación del año actual (primavera, verano, otoño, invierno), con tests de la función que calcula la estación.
- Página «Sobre el taller» (sobre.html): la historia inventada del taller y de su artesana en tono de crónica poética (500–700 palabras), con una línea del tiempo de cinco momentos clave.
- Rendimiento y orden: une los estilos repetidos en variables CSS comunes, elimina reglas que no se usan y comprueba con un test que todas las páginas enlazan la misma hoja de estilos base.
- Antología: página blog/antologia.html que reúne todos los poemas del blog en una sola lectura continua, generada con JavaScript a partir de la lista de entradas, con un test de que enlaza todos los parches.
- Mapa del sitio (mapa.html) con todas las páginas y una frase de cada una, enlazado desde el pie; test que comprueba que cada .html de la raíz y del blog aparece en el mapa.
- Libro, capítulo tres y final: cierra el relato en al menos 800 palabras y añade al final del libro un colofón con los parches en los que se escribió cada capítulo.
- Revisión general: repasa todas las páginas buscando enlaces rotos, textos de relleno, faltas de ortografía y estilos incoherentes; arréglalo y deja un test que recorra todos los enlaces internos y compruebe que existen.
- Parche de cierre de la jornada: una entrada de blog especial, más larga (20–30 versos), que repase en verso todo lo construido hoy, y una portada actualizada que la destaque.
