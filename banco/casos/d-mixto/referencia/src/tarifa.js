// Tarifa de aparcamiento (ver docs/ESPEC.md). Importes en céntimos.
export const redondearCent = (x) => Math.round(x);
export const tarifaNoche = (minutos) => 50 + 12 * minutos;
export const tarifaDia = (minutos) => 100 + 20 * minutos;
