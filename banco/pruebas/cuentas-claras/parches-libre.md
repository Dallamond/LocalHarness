# «Cuentas claras», modalidad libre: 6 hitos grandes en vez de 18 parches detallados

Mide planificación: el contrato (CONTRATO.md, en la semilla) dice QUÉ tiene que existir al final; cómo partirlo,
en qué orden y con qué tests lo decide el agente. Se corrige con el mismo examen oculto que la modalidad guiada.

Una línea «- texto» por parche. Lo que no empiece por «- » se ignora.
- Hito 1 · Lógica base. Lee ENCARGO.md y CONTRATO.md enteros. Antes de escribir código, apunta en docs/PLAN.md cómo vas a repartir el contrato en los 6 hitos. Implementa las secciones 1 a 4 del contrato (dinero, fechas, movimientos, HTML seguro, filtros, rutas, resumen y almacén) con tus propios tests en tests/ (valores concretos).
- Hito 2 · Datos. Implementa las secciones 5 y 6 del contrato (CSV, presupuestos y reducir) con tus propios tests; uno de ellos importa docs/ejemplo.csv y comprueba a mano las cifras de septiembre de 2026.
- Hito 3 · Vistas. Implementa las secciones 7 a 9 del contrato (navegación, tabla, gráfico, presupuestos, resumen y formulario) con tus propios tests sobre el HTML que devuelven.
- Hito 4 · La web en marcha. Implementa las secciones 10 y 11 del contrato (index.html, estilos.css y src/main.js). Al acabar, sirviendo la carpeta, la web tiene que dejar apuntar un movimiento y verlo en el resumen.
- Hito 5 · Importar, exportar, filtros y pulido. Implementa las secciones 12 y 13 del contrato con tus propios tests.
- Hito 6 · Revisión final. Relee CONTRATO.md sección por sección y comprueba cada nombre, firma, clase, atributo y número contra src/; busca imports rotos, texto sin escapar, código de Node en src/ y funciones que modifican lo que reciben. Arregla lo que falle sin cambiar firmas y deja todos los tests pasando.
