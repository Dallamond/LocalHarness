<script setup lang="ts">
// Consumo en vivo (Modelos locales): CPU y RAM del PC, cada GPU, el proceso de llama-server y DÓNDE está cargado
// el modelo (capas y MB en GPU o en RAM, leídos del log de llama-server). Se refresca cada 2 s.
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";

interface Usage {
  state: string; model: string | null; psutil: boolean;
  system: { cpu_pct: number | null; per_core: number[]; cores: number | null; ram_total_gb: number | null; ram_used_gb: number | null; ram_pct: number | null; swap_used_gb: number | null };
  gpus: { index: number; name: string; mem_used_mb: number | null; mem_total_mb: number | null; util: number | null; temp: number | null }[];
  process: { pid: number; rss_gb: number; cpu_pct: number; threads: number; vram_mb?: number | null } | null;
  placement: { layers_gpu: number | null; layers_total: number | null; gpu_mb: number; ram_mb: number;
    devices: { device: string; gpu: boolean; total_mb: number; parts: Record<string, number> }[] } | null;
}

const u = ref<Usage | null>(null);
let timer: ReturnType<typeof setInterval>;
async function load() {
  u.value = await api<Usage>("/api/llama/usage").catch(() => u.value);
}
onMounted(() => { load(); timer = setInterval(load, 2000); });
onUnmounted(() => clearInterval(timer));

const color = (v: number) => (v > 0.85 ? "var(--crit)" : v > 0.6 ? "var(--warn)" : "var(--ok)");
const gb = (mb: number | null | undefined) => (mb == null ? "—" : `${(mb / 1024).toFixed(1)} GB`);
const running = computed(() => !!u.value && u.value.state !== "off");
const where = computed(() => {
  const p = u.value?.placement;
  if (!p) return null;
  const total = p.gpu_mb + p.ram_mb || 1;
  const layersPct = p.layers_total ? p.layers_gpu! / p.layers_total : null;
  const text = layersPct === null ? (p.gpu_mb ? "En GPU y RAM" : "En RAM (CPU)")
    : layersPct >= 1 ? "Todo en la GPU" : layersPct === 0 ? "Todo en RAM (CPU): irá lento" : "Repartido entre GPU y RAM";
  return { ...p, gpuFrac: p.gpu_mb / total, text, layersPct };
});
const coreMax = computed(() => Math.max(1, ...(u.value?.system.per_core ?? [0])));
</script>

<template>
  <section class="card pad use">
    <div class="head">
      <h3 class="card-title">Consumo en vivo</h3>
      <span class="muted small">{{ running ? `llama-server · ${u?.model?.split(/[\\/]/).pop() ?? ""}` : "llama-server apagado" }}</span>
    </div>
    <div v-if="u" class="grid">
      <!-- PC -->
      <div class="box">
        <b class="t"><i class="fa-solid fa-microchip" /> CPU</b>
        <div class="big">{{ u.system.cpu_pct != null ? `${Math.round(u.system.cpu_pct)} %` : "—" }}<small>{{ u.system.cores }} hilos</small></div>
        <div class="meter"><i :style="{ width: `${u.system.cpu_pct ?? 0}%`, background: color((u.system.cpu_pct ?? 0) / 100) }" /></div>
        <div v-if="u.system.per_core.length" class="cores" :title="u.system.per_core.map((c) => `${Math.round(c)} %`).join(' · ')">
          <i v-for="(c, k) in u.system.per_core" :key="k" :style="{ height: `${Math.max(6, (c / coreMax) * 100)}%`, background: color(c / 100) }" />
        </div>
      </div>
      <div class="box">
        <b class="t"><i class="fa-solid fa-memory" /> RAM</b>
        <div class="big">{{ u.system.ram_used_gb ?? "—" }}<small>de {{ u.system.ram_total_gb ?? "—" }} GB</small></div>
        <div class="meter"><i :style="{ width: `${u.system.ram_pct ?? 0}%`, background: color((u.system.ram_pct ?? 0) / 100) }" /></div>
        <small v-if="u.system.swap_used_gb" class="muted">{{ u.system.swap_used_gb }} GB en disco (swap): falta RAM</small>
      </div>
      <div v-for="g in u.gpus" :key="g.index" class="box">
        <b class="t" :title="g.name"><i class="fa-solid fa-display" /> GPU {{ g.index }} · {{ g.name.replace(/NVIDIA (GeForce )?/, "") }}</b>
        <div class="big">{{ gb(g.mem_used_mb) }}<small>de {{ gb(g.mem_total_mb) }} · {{ g.util ?? "—" }} % uso · {{ g.temp ?? "—" }} °C</small></div>
        <div class="meter"><i :style="{ width: `${((g.mem_used_mb ?? 0) / (g.mem_total_mb || 1)) * 100}%`, background: color((g.mem_used_mb ?? 0) / (g.mem_total_mb || 1)) }" /></div>
      </div>
      <div v-if="!u.gpus.length" class="box">
        <b class="t"><i class="fa-solid fa-display" /> GPU</b>
        <p class="muted small">Sin datos: nvidia-smi no está (AMD/Intel o sin GPU NVIDIA).</p>
      </div>
    </div>

    <!-- llama-server -->
    <div v-if="u && running" class="srv">
      <div class="box">
        <b class="t"><i class="fa-solid fa-server" /> Proceso llama-server</b>
        <template v-if="u.process">
          <div class="kv">
            <span>RAM <b>{{ u.process.rss_gb.toFixed(1) }} GB</b></span>
            <span>CPU <b>{{ Math.round(u.process.cpu_pct) }} %</b><small> (100 % = 1 hilo)</small></span>
            <span>VRAM <b>{{ u.process.vram_mb != null ? gb(u.process.vram_mb) : where ? gb(where.gpu_mb) : "—" }}</b></span>
            <span>Hilos <b>{{ u.process.threads }}</b></span>
          </div>
        </template>
        <p v-else class="muted small">{{ u.psutil ? "No encuentro el proceso (¿arrancado fuera de LocalHarness?)." : "Instala psutil para medirlo: Actualizar.bat lo hace." }}</p>
      </div>
      <div class="box">
        <b class="t"><i class="fa-solid fa-location-dot" /> Dónde está cargado el modelo</b>
        <template v-if="where">
          <div class="big">{{ where.text }}<small v-if="where.layers_total">{{ where.layers_gpu }} de {{ where.layers_total }} capas en GPU</small></div>
          <div class="split" :title="`GPU ${gb(where.gpu_mb)} · RAM ${gb(where.ram_mb)}`">
            <i class="g" :style="{ width: `${where.gpuFrac * 100}%` }" /><i class="r" :style="{ width: `${(1 - where.gpuFrac) * 100}%` }" />
          </div>
          <div class="legend"><span><i class="g" />GPU {{ gb(where.gpu_mb) }}</span><span><i class="r" />RAM {{ gb(where.ram_mb) }}</span></div>
          <table class="dev">
            <tr v-for="d in where.devices" :key="d.device">
              <td><i :class="d.gpu ? 'g' : 'r'" />{{ d.device }}</td>
              <td>{{ Object.entries(d.parts).map(([k, v]) => `${k} ${gb(v)}`).join(" · ") }}</td>
              <td class="n">{{ gb(d.total_mb) }}</td>
            </tr>
          </table>
        </template>
        <p v-else class="muted small">Aún no lo sé: aparece cuando llama-server termina de cargar (solo si lo arrancaste desde aquí).</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.pad { padding: 16px 18px; }
.head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; }
.head .card-title { margin: 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }
.srv { display: grid; grid-template-columns: 1fr 1.5fr; gap: 10px; margin-top: 10px; }
.box { background: var(--panel-raised); border-radius: 14px; padding: 10px 12px; display: grid; gap: 6px; align-content: start; min-width: 0; }
.t { font-size: 12px; color: var(--ink-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.t i { margin-right: 4px; }
.big { font-size: 20px; font-weight: 800; font-variant-numeric: tabular-nums; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.big small { font-size: 11.5px; font-weight: 600; color: var(--ink-faint); }
.meter { height: 8px; border-radius: 4px; background: var(--meter); overflow: hidden; }
.meter i { display: block; height: 100%; border-radius: 4px; transition: width 0.6s; }
.cores { display: flex; align-items: flex-end; gap: 2px; height: 26px; }
.cores i { flex: 1; border-radius: 2px; min-width: 2px; transition: height 0.6s; }
.kv { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; font-size: 12.5px; color: var(--ink-dim); }
.kv b { color: var(--ink); font-variant-numeric: tabular-nums; }
.split { display: flex; gap: 2px; height: 14px; border-radius: 5px; overflow: hidden; background: var(--meter); }
.split i { display: block; height: 100%; }
.g { background: #0891b2; }
.r { background: #a16207; }
.legend { display: flex; gap: 14px; font-size: 12px; color: var(--ink-dim); }
.legend i, .dev td i { display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
.dev { width: 100%; font-size: 11.5px; border-collapse: collapse; }
.dev td { padding: 3px 4px; border-top: 1px solid var(--line); color: var(--ink-dim); }
.dev td:first-child { font-family: var(--font-mono); white-space: nowrap; color: var(--ink); }
.dev .n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
@media (max-width: 900px) { .srv { grid-template-columns: 1fr; } }
</style>
