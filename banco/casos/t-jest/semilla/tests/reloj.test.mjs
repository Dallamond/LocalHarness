import { formatear, aSegundos } from "../src/reloj.js";

describe("reloj", () => {
  it("formatea minutos y segundos", () => {
    expect(formatear(75)).toBe("01:15");
    expect(formatear(0)).toBe("00:00");
  });
  it("formatea más de una hora en minutos", () => {
    expect(formatear(3725)).toBe("62:05");
  });
  it("pasa de texto a segundos", () => {
    expect(aSegundos("02:30")).toBe(150);
  });
});
