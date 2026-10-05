import { createRouter, createWebHistory } from "vue-router";
import SetupView from "./views/SetupView.vue";
import TasksView from "./views/TasksView.vue";
import TaskView from "./views/TaskView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/tareas" },
    { path: "/tareas", component: TasksView, meta: { title: "Tareas" } },
    { path: "/tareas/:id", component: TaskView, props: (r) => ({ id: Number(r.params.id) }), meta: { title: "Ejecución" } },
    { path: "/proyectos", component: SetupView, meta: { title: "Proyectos y agentes" } },
  ],
});

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) ?? ""} · LocalHarness`;
});
