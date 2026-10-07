<script setup lang="ts">
// Antes de arrancar un GGUF: elegir contexto, caché, capas/expertos en GPU, hilos, muestreo… con la memoria que
// ocupará calculada en vivo y la orden exacta de llama-server. Se puede arrancar solo esta vez o guardarlo.
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import {
  SERVER_ROLE_LABEL, post, type Estimate, type LlamaDevice, type LocalModel, type LocalServer, type ModelLaunch,
  type ModelRating,
} from "../api";

const props = defineProps<{
  model: LocalModel;
  rating?: ModelRating;
  saved?: ModelLaunch;
  defaults: { ctx: number; ngl: number };
  busy?: boolean;
  server?: LocalServer; // en qué servidor local (GPU) se arranca; la memoria es la de sus GPU
  devices?: LlamaDevice[];
}>();
const emit = defineEmits<{
  close: [];
  launch: [options: ModelLaunch, save: boolean];
  save: [options: ModelLaunch];
}>();

const meta = computed(() => props.rating?.meta ?? {});
const suggested = computed(() => props.rating?.rating?.suggested);
const ctxTrain = computed(() => meta.value.ctx_train ?? 131072);
const nLayer = computed(() => meta.value.n_layer ?? 99);

const blank = (): ModelLaunch => ({
  ctx: null, ngl: null, flash_attn: "auto", cache_k: "f16", cache_v: "f16", threads: null, batch: null,
  ubatch: null, parallel: null, n_cpu_moe: null, temp: null, top_p: null, top_k: null, min_p: null,
  repeat_penalty: null, reasoning_budget: null, mlock: false, no_mmap: false, extra: "",
  device: "", split_mode: "", tensor_split: "", main_gpu: null,
});
const o = reactive<ModelLaunch>(blank());
function apply(src: ModelLaunch | undefined) {
  Object.assign(o, blank(), JSON.parse(JSON.stringify(src ?? {})));
}

type Preset = { id: string; label: string; hint: string; opts: () => ModelLaunch };
const presets = computed<Preset[]>(() => {
  const sug = suggested.value?.options ?? {};
  const base = { ...sug, flash_attn: "on" as const };
  const list: Preset[] = [];
  if (suggested.value) list.push({ id: "rec", label: "Recomendado para tu PC", hint: suggested.value.why ?? "", opts: () => sug });
  if (props.saved && Object.keys(props.saved).length)
    list.push({ id: "saved", label: "Lo guardado", hint: "Tu configuración propia de este modelo", opts: () => props.saved! });
  list.push(
    { id: "agent", label: "Agente (contexto largo)", hint: "Máximo contexto con caché en q8_0 para leer repos enteros",
      opts: () => ({ ...base, ctx: Math.min(ctxTrain.value, 65536), cache_k: "q8_0", cache_v: "q8_0" }) },
    { id: "fast", label: "Rápido", hint: "Contexto corto, todo en GPU: respuestas al momento",
      opts: () => ({ ...base, ctx: 8192, cache_k: "f16", cache_v: "f16", ngl: 99, n_cpu_moe: null }) },
    { id: "low", label: "Ahorro de VRAM", hint: "Caché en q4_0 y menos contexto para dejar GPU libre",
      opts: () => ({ ...base, ctx: 16384, cache_k: "q4_0", cache_v: "q4_0" }) },
    { id: "plain", label: "Valores generales", hint: "Lo de «Dónde están las cosas», sin nada propio", opts: () => ({}) },
  );
  return list;
});
const preset = ref("");
function choose(p: Preset) {
  preset.value = p.id;
  apply(p.opts());
}

onMounted(() => {
  const first = props.saved && Object.keys(props.saved).length ? "saved" : suggested.value ? "rec" : "plain";
  const p = presets.value.find((x) => x.id === first);
  if (p) choose(p);
  window.addEventListener("keydown", onKey);
});
onUnmounted(() => window.removeEventListener("keydown", onKey));
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") emit("close");
}

const TEXT_KEYS = ["extra", "flash_attn", "device", "split_mode", "tensor_split"];
// solo las claves con valor (lo vacío = lo decide llama.cpp o los valores generales)
const clean = computed<ModelLaunch>(() => {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    if (v === null || v === "" || v === false || v === undefined) continue;
    if (k === "flash_attn" && v === "auto") continue;
    if ((k === "cache_k" || k === "cache_v") && v === "f16") continue;
    out[k] = typeof v === "string" && !TEXT_KEYS.includes(k) && !k.startsWith("cache") ? Number(v) : v;
  }
  return out as ModelLaunch;
});

// estimación en vivo (con pausa para no llamar en cada tecla)
const est = ref<Estimate | null>(null);
const budget = ref<{ usable_vram_gb: number; vram_gb: number; usable_ram_gb: number; gpu: string | null } | null>(null);
const command = ref<string[] | null>(null);
const estErr = ref("");
let t: ReturnType<typeof setTimeout>;
watch(clean, () => {
  clearTimeout(t);
  t = setTimeout(async () => {
    try {
      const r = await post<{ estimate: Estimate; budget: any; command: string[] | null }>("/api/llama/estimate",
        { path: props.model.path, options: clean.value, server: props.server?.id });
      est.value = r.estimate;
      budget.value = r.budget;
      command.value = r.command;
      estErr.value = "";
    } catch (e) {
      estErr.value = (e as Error).message;
    }
  }, 250);
}, { deep: true, immediate: true });

const total = computed(() => Math.max(budget.value?.vram_gb || 0, est.value?.vram_gb || 0, 1));
const pct = (gb: number) => `${Math.max(0, (gb / total.value) * 100)}%`;
const FIT: Record<string, { text: string; cls: string }> = {
  gpu: { text: "Cabe entero en la GPU", cls: "ok" },
  mixto: { text: "Parte en la CPU (más lento)", cls: "warn" },
  cpu: { text: "Solo CPU", cls: "warn" },
  no: { text: "No cabe: bajará mucho o fallará al cargar", cls: "crit" },
};
const cmdText = computed(() => (command.value ?? []).map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(" "));
const kvQuantNoFa = computed(() => o.flash_attn === "off" && o.cache_v && o.cache_v !== "f16");
const ctxSteps = [4096, 8192, 16384, 24576, 32768, 49152, 65536, 98304, 131072, 262144];
const ctxOptions = computed(() => ctxSteps.filter((c) => c <= ctxTrain.value));
const showAdvanced = ref(false);

// GPU: la del servidor por defecto; se puede cambiar para esta vez (o juntar varias)
const devName = (id: string) => props.devices?.find((d) => d.id === id);
const gpuText = (dev: string) =>
  dev ? dev.split(",").map((id) => `${id} ${devName(id)?.name.replace(/^NVIDIA GeForce /, "") ?? ""}`.trim()).join(" + ")
    : "la que elija llama.cpp";
const allDevices = computed(() => (props.devices ?? []).map((d) => d.id).join(","));
const effectiveDevice = computed(() => o.device || props.server?.device || "");
const multi = computed(() => effectiveDevice.value.includes(","));
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="dialog" role="dialog" aria-modal="true" :aria-label="`Arrancar ${model.name}`">
      <header class="head">
        <div>
          <h3>Arrancar {{ model.name }}</h3>
          <p class="muted small">
            {{ model.size_gb.toFixed(1) }} GB<template v-if="model.quant"> · {{ model.quant }}</template>
            <template v-if="meta.arch"> · {{ meta.arch }}</template>
            <template v-if="meta.n_layer"> · {{ meta.n_layer }} capas</template>
            <template v-if="meta.ctx_train"> · contexto máx. {{ Math.round(meta.ctx_train / 1024) }}k</template>
            <template v-if="meta.moe"> · MoE</template>
          </p>
          <p v-if="server" class="small where">
            en <strong>{{ server.name }}</strong> ({{ SERVER_ROLE_LABEL[server.role] }}) · {{ gpuText(effectiveDevice) }} ·
            puerto {{ server.port }}
          </p>
        </div>
        <button class="btn btn--ghost btn--small" aria-label="Cerrar" @click="emit('close')">✕</button>
      </header>

      <div class="presets">
        <button v-for="p in presets" :key="p.id" type="button" class="preset" :class="{ on: preset === p.id }"
                :title="p.hint" @click="choose(p)">{{ p.label }}</button>
      </div>

      <!-- memoria -->
      <section class="mem">
        <div class="bar" :title="`VRAM total ${budget?.vram_gb ?? '?'} GB`">
          <span class="seg seg--w" :style="{ width: pct(est?.weights_gpu_gb ?? 0) }" />
          <span class="seg seg--kv" :style="{ width: pct(est?.kv_gpu_gb ?? est?.kv_gb ?? 0) }" />
          <span class="seg seg--o" :style="{ width: pct(est?.overhead_gb ?? 0) }" />
          <i v-if="budget" class="limit" :style="{ left: pct(budget.usable_vram_gb) }" />
        </div>
        <div class="legend small">
          <span><b class="sw sw--w" />pesos {{ est?.weights_gpu_gb ?? "…" }} GB</span>
          <span><b class="sw sw--kv" />caché KV {{ est?.kv_gb ?? "…" }} GB</span>
          <span><b class="sw sw--o" />cálculo {{ est?.overhead_gb ?? "…" }} GB</span>
          <span class="grow" />
          <strong>{{ est?.vram_gb ?? "…" }} / {{ budget?.vram_gb ?? "?" }} GB VRAM</strong>
        </div>
        <p v-if="est" class="fit small" :class="`fit--${FIT[est.fit ?? 'gpu']?.cls}`">
          {{ FIT[est.fit ?? "gpu"]?.text }}
          <template v-if="est.weights_cpu_gb > 0.05"> · {{ est.ram_gb }} GB en RAM</template>
          <template v-if="est.tps_est"> · ~{{ est.tps_est }} tok/s estimados</template>
        </p>
        <p v-if="estErr" class="error small">{{ estErr }}</p>
      </section>

      <form class="grid" @submit.prevent="emit('launch', clean, false)">
        <label class="field">
          <span class="label">Contexto (tokens)</span>
          <input v-model.number="o.ctx" type="number" min="512" :max="ctxTrain" step="1024" :placeholder="String(defaults.ctx)" list="ctx-steps" />
          <datalist id="ctx-steps"><option v-for="c in ctxOptions" :key="c" :value="c" /></datalist>
          <span class="hint">Lo que cabe en la conversación (prompt + repo + respuesta).</span>
        </label>
        <label class="field">
          <span class="label">Caché KV</span>
          <div class="row">
            <select v-model="o.cache_k" aria-label="Tipo de caché K">
              <option value="f16">f16</option><option value="q8_0">q8_0</option><option value="q4_0">q4_0</option>
            </select>
            <select v-model="o.cache_v" aria-label="Tipo de caché V">
              <option value="f16">f16</option><option value="q8_0">q8_0</option><option value="q4_0">q4_0</option>
            </select>
          </div>
          <span class="hint">q8_0 = la mitad de memoria casi sin perder calidad.</span>
        </label>
        <label class="field">
          <span class="label">Capas en GPU</span>
          <input v-model.number="o.ngl" type="number" min="0" :max="999" :placeholder="String(defaults.ngl)" />
          <span class="hint">{{ nLayer }} capas; 99 = todas.</span>
        </label>
        <label v-if="meta.moe" class="field">
          <span class="label">Capas de expertos en CPU</span>
          <input v-model.number="o.n_cpu_moe" type="number" min="0" :max="nLayer" placeholder="0" />
          <span class="hint">MoE: sacar expertos a la RAM apenas resta velocidad.</span>
        </label>
        <label class="field">
          <span class="label">Flash attention</span>
          <select v-model="o.flash_attn"><option value="auto">auto</option><option value="on">sí</option><option value="off">no</option></select>
          <span v-if="kvQuantNoFa" class="hint warnc">La caché V cuantizada necesita flash attention.</span>
        </label>
        <label class="field">
          <span class="label">Conversaciones a la vez</span>
          <input v-model.number="o.parallel" type="number" min="1" max="16" placeholder="auto" />
          <span class="hint">El contexto se reparte entre ellas.</span>
        </label>

        <h4 class="wide">Muestreo <span class="muted small">(por defecto del servidor; la temperatura de cada agente manda)</span></h4>
        <label class="field"><span class="label">Temperatura</span><input v-model.number="o.temp" type="number" min="0" max="2" step="0.05" placeholder="0.8" /></label>
        <label class="field"><span class="label">top_p</span><input v-model.number="o.top_p" type="number" min="0" max="1" step="0.05" placeholder="0.95" /></label>
        <label class="field"><span class="label">top_k</span><input v-model.number="o.top_k" type="number" min="0" step="1" placeholder="40" /></label>
        <label class="field"><span class="label">min_p</span><input v-model.number="o.min_p" type="number" min="0" max="1" step="0.01" placeholder="0.05" /></label>
        <label class="field"><span class="label">Penalización por repetir</span><input v-model.number="o.repeat_penalty" type="number" min="0.8" max="2" step="0.01" placeholder="1.0" /></label>
        <label v-if="meta.thinking" class="field">
          <span class="label">Pensamiento</span>
          <select v-model.number="o.reasoning_budget">
            <option :value="null">por defecto</option><option :value="-1">sin límite</option><option :value="0">apagado</option>
          </select>
          <span class="hint">Apagado = mucho más rápido, peor en problemas difíciles.</span>
        </label>
        <p v-if="rating?.catalog?.sampling" class="wide hint">
          La ficha de {{ rating.catalog.name }} recomienda:
          {{ Object.entries(rating.catalog.sampling).map(([k, v]) => `${k} ${v}`).join(" · ") }}
        </p>

        <button type="button" class="btn btn--ghost btn--small wide adv" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? "▾" : "▸" }} Avanzado
        </button>
        <template v-if="showAdvanced">
          <label v-if="devices && devices.length > 1" class="field">
            <span class="label">GPU (-dev)</span>
            <select v-model="o.device">
              <option value="">la del servidor ({{ gpuText(server?.device ?? "") }})</option>
              <option v-for="d in devices" :key="d.id" :value="d.id">{{ gpuText(d.id) }} · {{ Math.round(d.total_mb / 1024) }} GB</option>
              <option :value="allDevices">todas juntas ({{ Math.round(devices.reduce((n, d) => n + d.total_mb, 0) / 1024) }} GB)</option>
            </select>
            <span class="hint">Juntas caben modelos más grandes; va al paso de la más lenta.</span>
          </label>
          <template v-if="multi">
            <label class="field">
              <span class="label">Reparto (-sm)</span>
              <select v-model="o.split_mode"><option value="">por capas (normal)</option><option value="row">por filas</option><option value="none">solo una</option></select>
            </label>
            <label class="field">
              <span class="label">Proporción (-ts)</span>
              <input v-model="o.tensor_split" class="code" placeholder="2,1 = el doble en la primera" />
              <span class="hint">Vacío = según la memoria de cada una.</span>
            </label>
          </template>
          <label class="field"><span class="label">Hilos de CPU</span><input v-model.number="o.threads" type="number" min="1" placeholder="auto" /></label>
          <label class="field"><span class="label">Lote (-b)</span><input v-model.number="o.batch" type="number" min="32" step="256" placeholder="2048" /></label>
          <label class="field"><span class="label">Microlote (-ub)</span><input v-model.number="o.ubatch" type="number" min="32" step="128" placeholder="512" /></label>
          <label class="check"><input v-model="o.mlock" type="checkbox" /> Bloquear en RAM (--mlock)</label>
          <label class="check"><input v-model="o.no_mmap" type="checkbox" /> Sin mmap (carga todo al principio)</label>
          <label class="field wide"><span class="label">Argumentos extra</span><input v-model="o.extra" class="code" placeholder="--rope-scaling yarn --yarn-orig-ctx 32768" /></label>
        </template>

        <details v-if="cmdText" class="wide cmd">
          <summary class="small">Orden que se lanzará</summary>
          <code>{{ cmdText }}</code>
        </details>

        <footer class="wide actions">
          <button type="button" class="btn btn--small" :disabled="busy" @click="emit('save', clean)">Solo guardar</button>
          <span class="grow" />
          <button type="button" class="btn btn--small" :disabled="busy" @click="emit('launch', clean, true)">Arrancar y guardar</button>
          <button class="btn btn--primary" :disabled="busy">{{ busy ? "Arrancando…" : "Arrancar" }}</button>
        </footer>
      </form>
    </div>
  </div>
</template>

<style scoped>
.where {
  margin: 4px 0 0;
  color: var(--info);
}
.overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgb(0 0 0 / 0.45);
}
.dialog {
  width: min(760px, 100%);
  max-height: calc(100vh - 32px);
  overflow: auto;
  display: grid;
  gap: 14px;
  padding: 18px 20px;
  border-radius: var(--radius);
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
}
.head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.head h3 {
  margin: 0;
  overflow-wrap: anywhere;
}
.head p {
  margin: 2px 0 0;
}
.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.preset {
  padding: 5px 12px;
  border-radius: 99px;
  border: 1px solid var(--line);
  background: var(--panel-raised);
  color: var(--ink);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.preset.on {
  border-color: var(--accent);
  background: var(--accent-weak);
  color: var(--accent);
  font-weight: 600;
}
.mem {
  display: grid;
  gap: 6px;
}
.bar {
  position: relative;
  display: flex;
  height: 14px;
  border-radius: 99px;
  background: var(--panel-raised);
  overflow: hidden;
}
.seg {
  height: 100%;
  transition: width 0.3s ease;
}
.seg--w,
.sw--w {
  background: var(--accent);
}
.seg--kv,
.sw--kv {
  background: var(--info);
}
.seg--o,
.sw--o {
  background: var(--ink-faint);
}
.limit {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--crit);
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  align-items: center;
}
.sw {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
  margin-right: 5px;
  vertical-align: -1px;
}
.grow {
  flex: 1;
}
.fit {
  margin: 0;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
}
.fit--ok {
  background: var(--ok-weak);
  color: var(--ok);
}
.fit--warn {
  background: var(--warn-weak);
  color: var(--warn);
}
.fit--crit {
  background: var(--crit-weak);
  color: var(--crit);
}
.warnc {
  color: var(--warn);
}
.grid {
  display: grid;
  align-items: start;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px 14px;
}
.wide {
  grid-column: 1 / -1;
}
.grid h4 {
  margin: 6px 0 0;
}
.row {
  display: flex;
  gap: 6px;
}
.row select {
  flex: 1;
}
.check {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 14px;
}
.adv {
  justify-self: start;
}
.cmd code {
  display: block;
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--panel-raised);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}
</style>
