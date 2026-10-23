// @vitest-environment jsdom
import React, { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PaneTabs } from "@/components/job/PaneTabs";

function Harness() {
  const [active, setActive] = useState("a");
  const [typed, setTyped] = useState("");
  return (
    <PaneTabs label="Job settings" active={active} onChange={setActive} tabs={[
      { id: "a", label: "One", el: <input aria-label="kept" value={typed} onChange={(e) => setTyped(e.target.value)} /> },
      { id: "b", label: "Two", badge: "chosen", el: <p>second</p> },
      { id: "c", label: "Three", el: <p>third</p> },
    ]} />
  );
}
afterEach(cleanup);

describe("PaneTabs", () => {
  it("only the selected tab is in the Tab order, and it owns a visible panel", () => {
    render(<Harness />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.getAttribute("tabindex"))).toEqual(["0", "-1", "-1"]);
    expect(screen.getByRole("tabpanel").textContent).toBe("");
    expect(screen.getByRole("tabpanel", { hidden: true, name: "One" })).toBeTruthy();
  });

  it("arrow keys wrap, Home and End jump, and the focused tab is the selected one", () => {
    render(<Harness />);
    const [one, two, three] = screen.getAllByRole("tab");
    one.focus();
    fireEvent.keyDown(one, { key: "ArrowRight" });
    expect(document.activeElement).toBe(two);
    expect(two.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(two, { key: "End" });
    expect(document.activeElement).toBe(three);
    fireEvent.keyDown(three, { key: "ArrowRight" });
    expect(document.activeElement).toBe(one);
    fireEvent.keyDown(one, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(three);
    fireEvent.keyDown(three, { key: "Home" });
    expect(document.activeElement).toBe(one);
  });

  it("browser shortcuts are left alone", () => {
    render(<Harness />);
    const [one, two] = screen.getAllByRole("tab");
    one.focus();
    fireEvent.keyDown(one, { key: "ArrowRight", altKey: true });
    expect(document.activeElement).toBe(one);
    expect(two.getAttribute("aria-selected")).toBe("false");
  });

  it("an unselected panel stays mounted, so what was typed in it is not lost", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("kept"), { target: { value: "spool 4" } });
    fireEvent.click(screen.getByRole("tab", { name: /Two/ }));
    expect(screen.getByText("second")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /One/ }));
    expect((screen.getByLabelText("kept") as HTMLInputElement).value).toBe("spool 4");
  });

  it("a lazy tab is not mounted until it is first opened, and stays mounted after", () => {
    const mounts = vi.fn();
    function Probe() { React.useEffect(() => { mounts(); }, []); return <p>probe</p>; }
    function Lazy() {
      const [active, setActive] = useState("a");
      return <PaneTabs label="x" active={active} onChange={setActive} tabs={[
        { id: "a", label: "One", el: <p>first</p> }, { id: "b", label: "Two", lazy: true, el: <Probe /> }]} />;
    }
    render(<Lazy />);
    expect(mounts).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("tab", { name: "Two" }));
    expect(mounts).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("tab", { name: "One" }));
    fireEvent.click(screen.getByRole("tab", { name: "Two" }));
    expect(mounts).toHaveBeenCalledTimes(1);
  });

  it("shows a badge beside the label", () => {
    render(<Harness />);
    expect(screen.getByRole("tab", { name: /Two/ }).textContent).toContain("chosen");
  });
});
