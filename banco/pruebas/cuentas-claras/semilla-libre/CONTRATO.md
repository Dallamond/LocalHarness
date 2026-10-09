# Contrato de «Cuentas claras» (modalidad libre)

Es lo que la web tiene que cumplir al final: nombres de archivo, funciones exportadas, firmas, textos y números.
Se corrige con un examen oculto que importa estos módulos y busca trozos en el HTML que devuelven, así que los
nombres, las firmas, las clases y los atributos son obligatorios. **Cómo llegar hasta aquí lo decidís
vosotros**: el orden, los tests (los escribís vosotros, con valores concretos) y cómo partir el trabajo.

## 1. Dinero y fechas

- src/dinero.js exporta aCentimos(valor) y formatear(centimos). aCentimos: si valor es un número → Math.round(valor * 100); si es texto, quita '€' y los espacios, admite un signo '+' o '-' delante y: si lleva ',' los '.' son separadores de miles (se quitan) y la ',' es la coma decimal; si no lleva ',' y tiene forma de miles (/^\d{1,3}(\.\d{3})+$/) los '.' se quitan; si no, el '.' es el decimal. Como mucho 2 decimales. Devuelve céntimos enteros; cualquier otra cosa lanza Error('importe no válido'). formatear(centimos) = '1.234,56 €' (miles con punto, coma decimal, dos decimales, espacio y €; '-3,00 €' si es negativo).

- src/fechas.js exporta diasDelMes(mes 'AAAA-MM') (bisiestos: divisible entre 4 y no entre 100, o entre 400), esFechaValida(texto) (forma 'AAAA-MM-DD' y fecha real), mesDe(fecha) = los 7 primeros caracteres, sumarMeses(mes, n) (n puede ser negativo) y nombreMes(mes) = 'octubre 2026'.

## 2. Movimientos y HTML seguro

- src/movimientos.js exporta CATEGORIAS = ['comida', 'casa', 'transporte', 'ocio', 'salud', 'ropa', 'ingresos', 'otros'], crearMovimiento(datos, id), ordenar(lista), anadir(lista, mov), borrar(lista, id) y editar(lista, id, cambios). crearMovimiento recibe {fecha, concepto, importe, categoria} y devuelve {id, fecha, concepto (sin espacios a los lados), centimos: aCentimos(importe) de src/dinero.js, categoria (si no viene, 'otros')}; lanza Error 'fecha no válida' (esFechaValida de src/fechas.js), 'falta concepto' (vacío tras quitar espacios), 'categoría no válida' (no está en CATEGORIAS), 'importe cero' (centimos 0) o el de aCentimos. ordenar devuelve una lista NUEVA por fecha de más nueva a más vieja y, con la misma fecha, por id de mayor a menor; anadir = ordenar con el nuevo; borrar quita ese id; editar mezcla cambios en el de ese id (sin cambiar el id) y reordena. Ninguna toca la lista que recibe.

- src/html.js exporta escapar(texto): cambia & < > " ' por &amp; &lt; &gt; &quot; &#39;; null o undefined dan ''; un número se convierte a texto.

## 3. Filtros y rutas

- src/filtros.js exporta normalizar(texto) (minúsculas y sin tildes: normalize('NFD') y quitar /[̀-ͯ]/g) y filtrar(lista, filtro) con filtro {mes, categoria, texto, tipo}, todos opcionales: mes → mesDe(fecha) igual (src/fechas.js); categoria igual; tipo 'gasto' (centimos < 0), 'ingreso' (> 0) o 'todos' (por defecto); texto → normalizar(concepto) contiene normalizar(texto). Conserva el orden.

- src/rutas.js exporta VISTAS = ['resumen', 'movimientos', 'nuevo', 'presupuestos', 'importar'], leerRuta(hash) y crearRuta(vista, params). leerRuta quita '#' y '/' del principio, separa por '?', la vista vacía es 'resumen', los parámetros salen de URLSearchParams como objeto normal, y una vista que no está en VISTAS da {vista: 'no-encontrada', params: {}}. crearRuta da '#/' + vista y, si hay parámetros no vacíos, '?' con las claves ordenadas alfabéticamente y encodeURIComponent en clave y valor.

## 4. Resumen del mes y almacén

- src/resumen.js exporta resumenMes(lista, mes) = {mes, ingresos (suma de los positivos), gastos (suma de los negativos, en positivo), saldo = ingresos - gastos, porCategoria: [{categoria, centimos}] solo de gastos y en positivo, de mayor a menor y con empate por nombre de categoría, numero: cuántos movimientos tiene ese mes}; saldoHasta(lista, mes) = suma de centimos de todos los movimientos de ese mes o anteriores; evolucion(lista, mes, n) = los n meses que acaban en mes, del más viejo al más nuevo, cada uno {mes, ingresos, gastos, saldo} (usa sumarMeses de src/fechas.js).

- src/almacen.js exporta CLAVE = 'cuentas-claras', estadoVacio() = {version: 1, movimientos: [], presupuestos: {}, siguienteId: 1}, cargar(almacen) y guardar(almacen, estado). almacen es cualquier objeto con getItem(clave) y setItem(clave, texto), como localStorage (en los tests, uno falso con un Map). guardar escribe JSON.stringify(estado) en CLAVE; cargar lo lee y, si no hay nada, el JSON está roto, version no es 1 o movimientos no es un array, devuelve estadoVacio().

## 5. CSV

- src/csv.js exporta CABECERA = 'fecha;concepto;importe;categoria', importeCsv(centimos) ('-12,50', '0,05', '1234,00': coma decimal, sin miles ni €), aCsv(lista) (cabecera y una línea por movimiento en el orden recibido, separadas por '\n' y con '\n' al final; el concepto va entre comillas dobles si lleva ';', '"' o salto de línea, y sus comillas se duplican), partirLinea(linea) (separa por ';' respetando las comillas) y deCsv(texto, primerId = 1) = {movimientos, errores}. deCsv quita el BOM (﻿), parte por /\r?\n/, salta las líneas vacías, la primera no vacía tiene que ser la cabecera (sin distinguir mayúsculas; si no, devuelve {movimientos: [], errores: [{linea, motivo: 'cabecera no válida'}]}), y cada línea se convierte con crearMovimiento de src/movimientos.js con ids seguidos desde primerId (solo los válidos consumen id). Una línea con menos de 4 campos da el error 'faltan columnas'; si crearMovimiento lanza, el motivo es su mensaje. linea es el número de línea del archivo empezando en 1.

## 6. Presupuestos y estado de la app

- src/presupuestos.js exporta estadoPresupuestos(presupuestos, lista, mes): presupuestos es {categoria: limite en céntimos}; para cada categoría con limite > 0 devuelve {categoria, limite, gastado (gastos de esa categoría en ese mes, en positivo), restante = limite - gastado, porcentaje = Math.round(gastado * 100 / limite), estado: 'ok' si porcentaje < 80, 'aviso' si va de 80 a 100 (100 incluido) y 'pasado' si pasa de 100}, ordenado por porcentaje de mayor a menor y con empate por categoría.

- src/estado.js exporta reducir(estado, accion), pura (no toca el estado que recibe), con estado = el de estadoVacio de src/almacen.js. Acciones: {tipo: 'anadir', datos} → crearMovimiento(datos, siguienteId), anadir a la lista y siguienteId + 1; {tipo: 'borrar', id}; {tipo: 'editar', id, datos} → crearMovimiento(datos, id) sustituye al de ese id y se reordena; {tipo: 'presupuesto', categoria, importe} → presupuestos[categoria] = aCentimos(importe), y si importe es '' o da 0, se borra la categoría; {tipo: 'importar', texto} → deCsv(texto, siguienteId) de src/csv.js, añade los válidos, reordena y siguienteId suma cuántos entraron; otro tipo lanza Error('acción desconocida'). Los errores de crearMovimiento se dejan pasar.

## 7. Navegación y tabla de movimientos

- src/navegacion.js exporta navegacion(vistaActual): '<nav>' con un enlace <a href="crearRuta(v)"> por cada vista de VISTAS (src/rutas.js), con texto 'Resumen', 'Movimientos', 'Nuevo', 'Presupuestos' e 'Importar', y aria-current="page" solo en la actual.

- src/vista-movimientos.js exporta tablaMovimientos(lista): si está vacía, '<p class="vacio">No hay movimientos</p>'; si no, '<table class="movimientos">' con cabecera y un '<tr data-id="ID">' por movimiento en el orden recibido con la fecha, el concepto escapado (escapar de src/html.js), la categoría, el importe con formatear (src/dinero.js) y un '<button type="button" data-borrar="ID">Borrar</button>'.

## 8. Gráfico y vista de presupuestos

- src/grafico.js exporta graficoBarras(evolucion) (la lista de evolucion de src/resumen.js): '<svg class="grafico" viewBox="0 0 ANCHO 100">' con, por cada mes, '<rect class="ingresos" ...>' y '<rect class="gastos" ...>' (en ese orden, con data-mes, x, y, width y height); la barra más alta de todo el gráfico mide height 100 y las demás Math.round(valor * 100 / maximo); y = 100 - height; si todo es 0, las alturas son 0.

- src/vista-presupuestos.js exporta vistaPresupuestos(estados) (la lista de estadoPresupuestos): por cada uno '<div class="presupuesto ESTADO" data-categoria="CATEGORIA">' con el nombre, '<progress value="P" max="100">' con P = Math.min(porcentaje, 100) y el texto 'gastado de limite (porcentaje %)' con formatear; si no hay ninguno, '<p class="vacio">Sin presupuestos</p>'; y siempre un '<form id="form-presupuesto">' con un select name="categoria" (todas las categorías menos 'ingresos') y un input name="importe".

## 9. Resumen y formulario

- src/vista-resumen.js exporta vistaResumen(estado, mes): '<section class="resumen" data-mes="MES">' con un h1 con nombreMes (src/fechas.js), los ingresos, gastos y saldo de resumenMes (src/resumen.js) con formatear, un '<li data-categoria="C">' por categoría de porCategoria (en ese orden) y el graficoBarras (src/grafico.js) de evolucion(movimientos, mes, 6).

- src/formulario.js exporta formularioMovimiento(datos = {}, errores = []): '<form id="form-movimiento">' con un '<p class="error">' (escapado) por error, input type="date" name="fecha", input name="concepto", input name="importe" (inputmode="decimal"), un select name="categoria" con un option por cada CATEGORIAS (src/movimientos.js) y selected en datos.categoria, los value con datos escapados, y un botón Guardar.

## 10. Página y estilos

- index.html: '<!doctype html>', '<html lang="es">', meta charset utf-8 y meta name="viewport", título 'Cuentas claras', '<link rel="stylesheet" href="estilos.css">', '<main id="app"></main>' y '<script type="module" src="src/main.js"></script>'.

- estilos.css: colores en variables de :root, modo oscuro con '@media (prefers-color-scheme: dark)', la nav con enlaces redondeados y el aria-current resaltado, la tabla a todo el ancho, los gastos en rojo y los ingresos en verde (clases gasto/ingreso y los rect del gráfico), y un '@media (max-width: 600px)' para móvil.

## 11. La app en marcha

- src/main.js (no se prueba en node: es lo único que toca el navegador): estado = cargar(localStorage) (src/almacen.js); pintar() lee leerRuta(location.hash) (src/rutas.js) y escribe en document.getElementById('app').innerHTML navegacion(vista) + la vista: 'resumen' → vistaResumen(estado, params.mes o el mes de hoy); 'movimientos' → tablaMovimientos(filtrar(estado.movimientos, params)); 'nuevo' → formularioMovimiento con los errores del último envío; 'presupuestos' → vistaPresupuestos(estadoPresupuestos(...)); 'no-encontrada' → un aviso. Escucha 'hashchange' (repinta), 'submit' en #app con preventDefault (form-movimiento → reducir 'anadir' y va a '#/movimientos'; si lanza, guarda el mensaje y repinta el formulario; form-presupuesto → 'presupuesto') y 'click' en [data-borrar] → 'borrar'. Cada cambio pasa por reducir (src/estado.js) y guarda con guardar(localStorage, estado).

## 12. Importar, exportar y filtros en pantalla

- src/vista-importar.js exporta vistaImportar(resultado): '<section class="importar">' con, si resultado no es null, '<p class="aviso">Añadidos N movimientos</p>' y una lista con 'línea L: motivo' (motivo escapado) por error; siempre un '<form id="form-importar">' con '<textarea name="csv">' y un '<button type="button" id="exportar">Exportar CSV</button>'.

- src/vista-filtros.js exporta formularioFiltros(filtro = {}): '<form id="form-filtros">' con input type="month" name="mes", un select name="categoria" (primera opción value="" 'todas' y luego CATEGORIAS), un select name="tipo" (todos, gasto, ingreso) e input type="search" name="texto", con los valores de filtro puestos (selected y value escapado). Luego, en src/main.js: 'importar' pinta vistaImportar con el resultado del último envío de form-importar (deCsv para contar y reducir 'importar' para añadir); el botón #exportar descarga aCsv(estado.movimientos) como 'cuentas.csv' con un Blob y un enlace temporal; 'movimientos' pinta formularioFiltros(params) encima de la tabla y form-filtros cambia el hash con crearRuta('movimientos', datos del formulario).

## 13. Pulido de la interfaz

- estilos.css: tarjetas para las cifras del resumen (ingresos, gastos, saldo) en fila que pasan a columna en móvil; tabla con filas alternas y los importes alineados a la derecha; barras de presupuesto de color según el estado (ok verde, aviso ámbar, pasado rojo); foco visible en enlaces, botones y campos (:focus-visible).

- Accesibilidad en las vistas sin cambiar firmas: cada input y select va dentro de un <label> con texto; la tabla lleva <thead> con <th>; el svg del gráfico lleva role="img" y aria-label.
