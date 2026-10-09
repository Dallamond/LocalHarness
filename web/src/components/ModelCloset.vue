<script setup lang="ts">
// Armario de modelos (PLAN-MODELOS-LOCALES P1-P4, P17): qué sabe hacer cada GGUF, dónde cabe, cambiarlo en caliente
// en una GPU, unir o separar las GPU y el banco de pruebas con números reales.
import { computed, onMounted, ref } from "vue";
import Card from "./Card.vue";
import { api, post } from "../api";

interface Fit { fit: string | null; vram_gb: number | null; tps_est: number | null }
interface Profile {
  path: string; name: string; size_gb: number; caps: string[]; auto_caps: string[]; manual: boolean;
  mmproj: string; draft: { model?: string } | null; load_s: number | null; fits: Record<string, Fit>;
}
interface BenchRow { model: string; topology: string; read_tps: number | null; write_tps: number | null;
  draft_accept: number | null; at: number }
interface Server { id: string; name: string; device: string; model_name: string | null; status: { state: string } }

const props = defineProps<{ servers: Server[] }>();
const emit = defineEmits<{ changed: [] }>();

const profiles = ref<Profile[]>([]);
const caps = ref<Record<string, string>>({});
const topology = ref("separado");
const bench = ref<BenchRow[]>([]);
const busy = ref("");
const msg = ref("");
const err = ref("");

async function load() {
  try {
    const r = await api<{ profiles: Profile[]; caps: Record<string, string>; topology: string }>("/api/llama/profiles");
    profiles.value = r.profiles;
    caps.value = r.caps;
    topology.value = r.topology;
    bench.value = (await api<{ results: BenchRow[] }>("/api/llama/bench")).results;
  } catch (e) {
    err.value = (e as Error).message;
  }
}
onMounted(load);

async function run(label: string, fn: () => Promise<unknown>, done: string) {
  busy.value = label;
  err.value = msg.value = "";
  try {
    await fn();
    msg.value = done;
    emit("changed");
    await load();
  } catch (e) {
    err.value = (e as Error).message;
  } finally {
    busy.value = "";
  }
}

const toggleCap = (p: Profile, c: string) => {
  const next = p.caps.includes(c) ? p.caps.filter((x) => x !== c) : [...p.caps, c];
  run("caps", () => api("/api/llama/profiles", { method: "PUT", body: JSON.stringify({ path: p.path, caps: next }) }),
    `${p.name}: capacidades guardadas`);
};
const resetCaps = (p: Profile) =>
  run("caps", () => api("/api/llama/profiles", { method: "PUT", body: JSON.stringify({ path: p.path, caps: null }) }),
    `${p.name}: capacidades deducidas otra vez`);
const swap = (p: Profile, s: Server) =>
  run(`swap-${p.path}-${s.id}`, () => post("/api/llama/swap", { server: s.id, path: p.path }),
    `${s.name} ahora tiene ${p.name}`);
const join = (p: Profile) =>
  run("topo", () => post("/api/llama/topology", { mode: "unido", path: p.path }), `GPU unidas con ${p.name}`);
const split = () => run("topo", () => post("/api/llama/topology", { mode: "separado" }), "Un modelo por GPU otra vez");
const runBench = () => run("bench", () => post("/api/llama/bench", {}), "Banco de pruebas hecho");

const loadedIn = (p: Profile) => props.servers.filter((s) => s.model_name && p.name.startsWith(s.model_name));
const fitsIn = (p: Profile, s: Server) => !s.device || p.fits[s.device]?.fit === "gpu";
const onlyJoined = (p: Profile) => p.fits.unido?.fit === "gpu" && !Object.entries(p.fits).some(([k, f]) => k !== "unido" && f.fit === "gpu");
const sorted = computed(() => [...profiles.value].sort((a, b) => b.size_gb - a.size_gb));
const when = (t: number) => new Date(t * 1000).toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
</script>

<template>
  <Card title="Armario de modelos" :subtitle="topology === 'unido'
    ? 'GPU unidas: un solo modelo repartido entre las dos'
    : 'Qué sabe hacer cada modelo y dónde cabe. Claude y el planificador piden capacidades; aquí eliges cuál las da.'">
    <template #actions>
      <button v-if="topology === 'unido'" class="btn btn--small" :disabled="!!busy" @click="split">Separar las GPU</button>
      <button class="btn btn--small" :disabled="!!busy" @click="runBench">{{ busy === "bench" ? "Midiendo…" : "Banco de pruebas" }}</button>
    </template>
    <p v-if="msg" class="hint ok">{{ msg }}</p>
    <p v-if="err" class="hint bad">{{ err }}</p>
    <p v-if="busy && busy.startsWith('swap')" class="hint">Cambiando de modelo… espera a que acabe lo que esté haciendo y carga el nuevo.</p>

    <ul class="closet">
      <li v-for="p in sorted" :key="p.path" class="closet__item">
        <div class="closet__head">
          <strong>{{ p.name }}</strong>
          <span class="muted small">{{ p.size_gb }} GB<template v-if="p.load_s"> · carga en {{ Math.round(p.load_s) }} s</template></span>
          <span v-for="s in loadedIn(p)" :key="s.id" class="loaded">en {{ s.name }}</span>
        </div>
        <div class="closet__caps">
          <button v-for="(text, c) in caps" :key="c" type="button" class="cap" :class="{ on: p.caps.includes(c), auto: p.auto_caps.includes(c) }"
                  :title="p.auto_caps.includes(c) ? 'Deducido del modelo' : 'Puesto a mano'" :disabled="!!busy" @click="toggleCap(p, c)">
            {{ text }}
          </button>
          <button v-if="p.manual" type="button" class="link small" :disabled="!!busy" @click="resetCaps(p)">deducir</button>
        </div>
        <div class="closet__fits small">
          <span v-for="(f, where) in p.fits" :key="where" class="fit" :class="`fit--${f.fit}`">
            {{ where === "unido" ? "las dos unidas" : where }}: {{ f.fit === "gpu" ? "cabe" : f.fit === "mixto" ? "con RAM" : "no cabe" }}<template
              v-if="f.tps_est"> · ~{{ f.tps_est }} tok/s</template>
          </span>
          <span v-if="p.mmproj" class="fit">visión: {{ p.mmproj.split(/[\\/]/).pop() }}</span>
          <span v-if="p.draft?.model" class="fit">borrador: {{ p.draft.model.split(/[\\/]/).pop() }}</span>
        </div>
        <div class="closet__actions">
          <button v-for="s in servers" :key="s.id" class="btn btn--small" :disabled="!!busy || !fitsIn(p, s) || loadedIn(p).includes(s)"
                  :title="fitsIn(p, s) ? `Cambiar el modelo de ${s.name}` : 'No cabe entero en esa GPU'" @click="swap(p, s)">
            Cargar en {{ s.name }}
          </button>
          <button v-if="servers.length > 1 && p.fits.unido" class="btn btn--small" :disabled="!!busy || p.fits.unido.fit !== 'gpu'"
                  :title="onlyJoined(p) ? 'Solo cabe con las dos GPU' : 'Cabe en una sola: unidas irá más lento (la 1060 marca el paso)'" @click="join(p)">
            Unir las GPU para este
          </button>
        </div>
      </li>
    </ul>

    <details v-if="bench.length" class="benchbox" open>
      <summary>Banco de pruebas ({{ bench.length }})</summary>
      <table class="bench">
        <thead><tr><th>Modelo</th><th>Dónde</th><th>Lee</th><th>Escribe</th><th>Borrador</th><th>Cuándo</th></tr></thead>
        <tbody>
          <tr v-for="b in bench" :key="b.model + b.topology">
            <td>{{ b.model.split(/[\\/]/).pop()?.replace(/\.gguf$/i, "") }}</td><td>{{ b.topology }}</td>
            <td>{{ b.read_tps ?? "—" }} tok/s</td><td><strong>{{ b.write_tps ?? "—" }}</strong> tok/s</td>
            <td>{{ b.draft_accept != null ? Math.round(b.draft_accept * 100) + " % aceptado" : "—" }}</td><td class="muted">{{ when(b.at) }}</td>
          </tr>
        </tbody>
      </table>
    </details>
  </Card>
</template>

<style scoped>
.closet { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 10px; }
.closet__item { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 14px; background: var(--panel-2, transparent); }
.closet__head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.loaded { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--accent-soft, rgba(80, 160, 120, .15)); }
.closet__caps, .closet__fits, .closet__actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; align-items: center; }
.cap { font-size: 12px; padding: 2px 10px; border-radius: 999px; border: 1px dashed var(--line); background: none; color: var(--muted); cursor: pointer; }
.cap.on { border-style: solid; color: var(--text); background: var(--accent-soft, rgba(80, 160, 120, .15)); }
.cap.on.auto { border-color: transparent; }
.fit { padding: 1px 8px; border-radius: 999px; border: 1px solid var(--line); }
.fit--gpu { border-color: rgba(80, 160, 120, .5); }
.fit--no { opacity: .55; }
.ok { color: var(--ok, #3a8f5c); }
.bad { color: var(--crit, #c0392b); }
.benchbox { margin-top: 14px; }
.bench { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
.bench th, .bench td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--line); }
@media (max-width: 640px) { .bench { font-size: 12px; } .bench th:nth-child(6), .bench td:nth-child(6) { display: none; } }
</style>
