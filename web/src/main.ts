import { createApp } from "vue";
import "@fontsource-variable/figtree";
import "@fontsource/jetbrains-mono/400.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/app.css";
import App from "./App.vue";
import { applyLook, connect } from "./api";
import { router } from "./router";

applyLook();
connect();
createApp(App).use(router).mount("#app");
