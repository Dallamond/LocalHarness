import { createRouter, createWebHistory } from "vue-router";
import SetupView from "./views/SetupView.vue";
import TasksView from "./views/TasksView.vue";
import TaskView from "./views/TaskView.vue";
import PlansView from "./views/PlansView.vue";
import PlanView from "./views/PlanView.vue";
import InboxView from "./views/InboxView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/bandeja" },
    { path: "/tareas", component: TasksView, meta: { title: "Tareas" } },
    { path: "/tareas/:id", component: TaskView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Ejecución" } },
    { path: "/proyectos", component: SetupView, meta: { title: "Proyectos y agentes" } },
    { path: "/planes", component: PlansView, meta: { title: "Planes" } },
    { path: "/planes/:id", component: PlanView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Plan" } },
    { path: "/bandeja", component: InboxView, meta: { title: "Pendiente de ti" } },
  ],
});

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) ?? ""} · LocalHarness`;
});
