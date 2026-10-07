import { createRouter, createWebHistory } from "vue-router";
const OfficeView = () => import("./views/OfficeView.vue"); // three.js va en su propio trozo
import SettingsView from "./views/SettingsView.vue";
import ChatView from "./views/ChatView.vue";
import ModelsView from "./views/ModelsView.vue";
import TaskView from "./views/TaskView.vue";
import PlansView from "./views/PlansView.vue";
import PlanView from "./views/PlanView.vue";
import AnalyticsView from "./views/AnalyticsView.vue";
import WorkView from "./views/WorkView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/oficina" },
    { path: "/inicio", redirect: "/oficina" },
    { path: "/oficina", component: OfficeView, meta: { title: "Oficina", full: true } },
    { path: "/chat", component: ChatView, meta: { title: "Chat" } },
    { path: "/chat/:id", component: ChatView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Chat" } },
    { path: "/modelos", component: ModelsView, meta: { title: "Modelos locales" } },
    { path: "/analiticas", component: AnalyticsView, meta: { title: "Analíticas" } },
    { path: "/trabajo", component: WorkView, meta: { title: "Trabajo" } },
    { path: "/tareas", redirect: "/chat" },
    { path: "/tareas/:id", component: TaskView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Ejecución" } },
    { path: "/ajustes", component: SettingsView, meta: { title: "Ajustes" } },
    { path: "/proyectos", redirect: { path: "/ajustes", query: { s: "proyectos" } } },
    { path: "/planes", component: PlansView, meta: { title: "Planes" } },
    { path: "/planes/:id", component: PlanView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Plan" } },
    // Planes y «Pendiente de ti» ya no están en el menú (la bandeja vive en la Oficina); las rutas siguen para los enlaces
    { path: "/bandeja", redirect: "/trabajo" }, // la vieja «Pendiente de ti»: ahora es la vista Trabajo
  ],
});

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) ?? ""} · LocalHarness`;
});
