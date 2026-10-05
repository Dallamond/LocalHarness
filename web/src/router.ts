import { createRouter, createWebHistory } from "vue-router";
import HomeView from "./views/HomeView.vue";
import SettingsView from "./views/SettingsView.vue";
import ChatView from "./views/ChatView.vue";
import ModelsView from "./views/ModelsView.vue";
import TaskView from "./views/TaskView.vue";
import PlansView from "./views/PlansView.vue";
import PlanView from "./views/PlanView.vue";
import InboxView from "./views/InboxView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/inicio" },
    { path: "/inicio", component: HomeView, meta: { title: "Inicio" } },
    { path: "/chat", component: ChatView, meta: { title: "Chat" } },
    { path: "/chat/:id", component: ChatView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Chat" } },
    { path: "/modelos", component: ModelsView, meta: { title: "Modelos locales" } },
    { path: "/tareas", redirect: "/chat" },
    { path: "/tareas/:id", component: TaskView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Ejecución" } },
    { path: "/ajustes", component: SettingsView, meta: { title: "Ajustes" } },
    { path: "/proyectos", redirect: { path: "/ajustes", query: { s: "proyectos" } } },
    { path: "/planes", component: PlansView, meta: { title: "Planes" } },
    { path: "/planes/:id", component: PlanView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Plan" } },
    { path: "/bandeja", component: InboxView, meta: { title: "Pendiente de ti" } },
  ],
});

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) ?? ""} · LocalHarness`;
});
