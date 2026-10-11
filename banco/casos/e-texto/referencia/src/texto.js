// Utilidades de texto.
export function slug(s) {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function capitalizar(s) {
  return s
    .split(" ")
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1).toLowerCase() : p))
    .join(" ");
}

export function truncar(s, n) {
  return s.length <= n ? s : `${s.slice(0, n - 1)}…`;
}
