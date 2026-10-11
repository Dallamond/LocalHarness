import { anadir, borrar, completar, contar, filtrar } from "./tareas.js";
import { cargar, guardar } from "./almacen.js";
import { vistaLista } from "./vista.js";

let tareas = cargar(localStorage);
let filtro = "todas";
const $ = (id) => document.getElementById(id);

function pintar() {
  $("lista").innerHTML = vistaLista(filtrar(tareas, filtro));
  const c = contar(tareas);
  $("contador").textContent = `${c.pendientes} pendientes de ${c.total}`;
  guardar(localStorage, tareas);
}

$("formulario").addEventListener("submit", (e) => {
  e.preventDefault();
  try {
    tareas = anadir(tareas, $("texto").value, Date.now());
    $("texto").value = "";
  } catch { /* texto vacío: no se añade */ }
  pintar();
});
$("lista").addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (!li) return;
  const id = Number(li.dataset.id);
  tareas = e.altKey ? borrar(tareas, id) : completar(tareas, id);
  pintar();
});
$("filtro").addEventListener("change", (e) => {
  filtro = e.target.value;
  pintar();
});
pintar();
