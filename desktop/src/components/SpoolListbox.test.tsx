// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import type { ProviderSpool } from "@/api";
import SpoolListbox from "./SpoolListbox";

afterEach(cleanup);

const spools: ProviderSpool[] = [
  { id: 133, label: "Sunlu ABS", vendor: "Sunlu", material: "ABS", subtype: null, color: "#000000", remaining_g: null },
  { id: 124, label: "Yoopai PLA", vendor: "Yoopai", material: "PLA", subtype: "Matte", color: "#FF0000", remaining_g: 250, remaining_quality: "estimated" },
  { id: 134, label: "Sunlu ABS", vendor: "Sunlu", material: "ABS", subtype: null, color: "#000000", remaining_g: null },
];

function Harness({ list = spools, start = null }: { list?: ProviderSpool[]; start?: number | string | null }) {
  const [v, setV] = useState<number | string | null>(start);
  return (
    <div className="dark">
      <SpoolListbox spools={list} value={v} onChange={setV} ariaLabel="Spool for slot 1" />
      <output data-testid="chosen">{String(v)}</output>
    </div>
  );
}

const trigger = () => screen.getByRole("combobox", { name: "Spool for slot 1" });
const open = () => fireEvent.click(trigger());
const optionTexts = () => screen.getAllByRole("option").map((o) => o.textContent);

describe("SpoolListbox", () => {
  it("is not a native select, so the operating system cannot draw it light-on-light", () => {
    const { container } = render(<Harness />);
    open();
    expect(container.querySelector("select")).toBeNull();
    expect(container.querySelector("option")).toBeNull();
    expect(screen.getByRole("listbox")).toBeTruthy();
  });

  it("takes its colours from the theme tokens, never a hard-coded light surface", () => {
    const { container } = render(<Harness />);
    open();
    const html = container.innerHTML;
    expect(html).toContain("bg-card");
    expect(html).toContain("text-foreground");
    expect(html).toContain("border-border");
    expect(html).not.toMatch(/bg-white|text-black|bg-gray-|#fff\b|#ffffff/i);
  });

  it("lists spools sorted, each with vendor, colour name, #id and weight in words", () => {
    render(<Harness />);
    open();
    expect(optionTexts()).toEqual([
      "— nothing mapped —",
      "Sunlu ABS — Black · #133 · weight unknown",
      "Sunlu ABS — Black · #134 · weight unknown",
      "Yoopai PLA Matte — Red · #124 · 250 g estimated",
    ]);
  });

  it("two similar spools are told apart by their ids", () => {
    render(<Harness />);
    open();
    const texts = optionTexts();
    expect(texts.filter((t) => t?.startsWith("Sunlu ABS — Black"))).toHaveLength(2);
    expect(new Set(texts).size).toBe(texts.length);
  });

  it("narrows as you type", () => {
    render(<Harness />);
    open();
    fireEvent.change(screen.getByLabelText("Find a spool"), { target: { value: "red matte" } });
    expect(optionTexts()).toEqual(["— nothing mapped —", "Yoopai PLA Matte — Red · #124 · 250 g estimated"]);
    fireEvent.change(screen.getByLabelText("Find a spool"), { target: { value: "#134" } });
    expect(optionTexts()).toEqual(["— nothing mapped —", "Sunlu ABS — Black · #134 · weight unknown"]);
    fireEvent.change(screen.getByLabelText("Find a spool"), { target: { value: "zzz" } });
    expect(screen.getByText(/No spool matches/)).toBeTruthy();
  });

  it("works from the keyboard: arrows, Enter to choose, Escape to leave", () => {
    render(<Harness />);
    open();
    const input = screen.getByLabelText("Find a spool");
    fireEvent.keyDown(input, { key: "ArrowDown" });   // first spool
    fireEvent.keyDown(input, { key: "ArrowDown" });   // second spool
    expect(screen.getAllByRole("option")[2].className).toContain("bg-muted");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("chosen").textContent).toBe("134");
    expect(screen.queryByRole("listbox")).toBeNull();

    open();
    fireEvent.keyDown(screen.getByLabelText("Find a spool"), { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByTestId("chosen").textContent).toBe("134");   // unchanged
  });

  it("opens from the keyboard on the trigger and can clear the choice", () => {
    render(<Harness start={124} />);
    fireEvent.keyDown(trigger(), { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeTruthy();
    const input = screen.getByLabelText("Find a spool");
    fireEvent.keyDown(input, { key: "Home" });         // "nothing mapped"
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("chosen").textContent).toBe("null");
  });

  it("a click chooses a spool and shows it, swatch plus words, on the closed control", () => {
    render(<Harness />);
    open();
    fireEvent.mouseDown(screen.getByRole("option", { name: /Yoopai PLA Matte/ }));
    expect(screen.getByTestId("chosen").textContent).toBe("124");
    expect(trigger().textContent).toContain("Yoopai PLA Matte — Red · #124 · 250 g estimated");
    expect(trigger().querySelector("[aria-hidden='true']")).not.toBeNull();
  });

  it("round-trips string ids unchanged", () => {
    render(<Harness list={[{ id: "A1", label: "Test spool", remaining_g: 500 }]} />);
    open();
    fireEvent.mouseDown(screen.getByRole("option", { name: /Test spool/ }));
    expect(screen.getByTestId("chosen").textContent).toBe("A1");
  });

  it("handles 100+ spools: sorted, searchable, and the unmatched rows are not drawn", () => {
    const many: ProviderSpool[] = Array.from({ length: 130 }, (_, i) => ({
      id: i + 1, label: `s${i}`, vendor: ["Acme", "Sunlu", "Yoopai"][i % 3], material: ["PLA", "ABS"][i % 2],
      color: ["#FF0000", "#00FF00", "#0000FF"][i % 3], remaining_g: null,
    }));
    render(<Harness list={many} />);
    open();
    expect(screen.getAllByRole("option")).toHaveLength(131);        // 130 + "nothing mapped"
    expect(optionTexts()[1]).toContain("Acme");                      // sorted: Acme first
    fireEvent.change(screen.getByLabelText("Find a spool"), { target: { value: "yoopai abs" } });
    const rows = optionTexts().slice(1);
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(40);
    expect(rows.every((t) => t?.includes("Yoopai ABS"))).toBe(true);
  });
});
