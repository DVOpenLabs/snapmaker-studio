import { describe, expect, it } from "vitest";
// @ts-expect-error @types/node is not installed; vitest runs on Node, and ?raw returns an empty string for CSS here
import { readFileSync } from "node:fs";

const css: string = readFileSync(new URL("../index.css", import.meta.url), "utf8");

// Pins the status/primary foreground tokens in index.css to WCAG AA for normal text, against the surfaces
// they are actually drawn on: the page, a card, a muted panel and Tailwind's /5../15 tints of the same colour.
const block = (sel: string) => css.match(new RegExp(`${sel}\\s*\\{([\\s\\S]*?)\\n  \\}`))![1];
const token = (b: string, name: string): [number, number, number] => {
  const m = b.match(new RegExp(`--${name}:\\s*(\\d+)\\s+(\\d+)%\\s+(\\d+)%`));
  if (!m) throw new Error(`token --${name} not found`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
};
const rgb = ([h, s, l]: [number, number, number]) => {
  s /= 100; l /= 100;
  const k = (n: number) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)].map((v) => v * 255);
};
const mix = (fg: number[], bg: number[], a: number) => fg.map((v, i) => v * a + bg[i] * (1 - a));
const lum = (c: number[]) => {
  const [r, g, b] = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a: number[], b: number[]) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

const themes = { light: block(":root"), dark: block("\\.dark") };

describe.each(Object.entries(themes))("%s theme text tokens", (_name, b) => {
  const surfaces = (fill: number[]) => {
    const page = rgb(token(b, "background")), card = rgb(token(b, "card")), muted = rgb(token(b, "muted"));
    return [page, card, muted, mix(fill, page, 0.05), mix(fill, card, 0.1), mix(fill, card, 0.15)];
  };
  it.each([
    ["ready", "ready-text", "ready"],
    ["risk", "risk-text", "risk"],
    ["repairable", "repairable-text", "repairable"],
    ["primary", "primary-text", "primary"],
  ])("%s text stays at 4.5:1 or better on its surfaces", (_label, textToken, fillToken) => {
    const fg = rgb(token(b, textToken));
    for (const bg of surfaces(rgb(token(b, fillToken)))) expect(ratio(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });
  it("the primary button label reads on the primary fill, also after the hover darkening", () => {
    const fill = rgb(token(b, "primary")), label = rgb(token(b, "primary-foreground"));
    expect(ratio(label, fill)).toBeGreaterThanOrEqual(4.5);
    if (_name === "light") expect(ratio(label.map((v) => v * 0.9), fill.map((v) => v * 0.9))).toBeGreaterThanOrEqual(4.5);
  });
});
