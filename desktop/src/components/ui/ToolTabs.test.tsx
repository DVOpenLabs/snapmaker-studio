// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { ToolTabs, type ToolTab } from "./ToolTabs";

afterEach(cleanup);

const make = (ids: string[]): ToolTab[] =>
  ids.map((id) => ({
    id, label: `Tab ${id}`,
    el: <div><h2>Heading {id}</h2><button type="button">Action {id}</button></div>,
  }));

const tab = (name: string) => screen.getByRole("tab", { name });
const press = (el: HTMLElement, key: string) => fireEvent.keyDown(el, { key });

describe("ToolTabs", () => {
  it("names the tab row and wires tab and panel together with ids", () => {
    render(<ToolTabs label="Example tools" tabs={make(["a", "b"])} />);
    expect(screen.getByRole("tablist", { name: "Example tools" })).toBeTruthy();
    const a = tab("Tab a");
    const panel = screen.getByRole("tabpanel");
    expect(a.id).toBeTruthy();
    expect(a.getAttribute("aria-controls")).toBe(panel.id);
    expect(panel.getAttribute("aria-labelledby")).toBe(a.id);
    expect(screen.getByRole("tabpanel", { name: "Tab a" })).toBe(panel);
  });

  it("only the selected tab has aria-controls, because inactive panels are not in the page", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b"])} />);
    expect(tab("Tab a").getAttribute("aria-controls")).toBeTruthy();
    expect(tab("Tab b").hasAttribute("aria-controls")).toBe(false);
  });

  it("ignores navigation keys pressed with Alt, Ctrl or Meta", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b", "c"])} />);
    tab("Tab a").focus();
    for (const init of [
      { key: "ArrowLeft", altKey: true }, { key: "Home", ctrlKey: true }, { key: "ArrowRight", metaKey: true },
      { key: "Enter", ctrlKey: true },
    ]) {
      const notPrevented = fireEvent.keyDown(tab("Tab a"), { ...init, cancelable: true });
      expect(notPrevented).toBe(true);                        // dispatchEvent returns false when preventDefault ran
      expect(document.activeElement).toBe(tab("Tab a"));
      expect(tab("Tab a").getAttribute("aria-selected")).toBe("true");
    }
  });

  it("keeps only the selected panel in the page", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b"])} />);
    expect(screen.queryByText("Heading a")).not.toBeNull();
    expect(screen.queryByText("Heading b")).toBeNull();
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  });

  it("puts only the selected tab in the Tab order, and the panel is not a tab stop", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b", "c"])} />);
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([0, -1, -1]);
    expect(screen.getByRole("tabpanel").tabIndex).toBe(-1);
  });

  it("moves focus with the arrow keys, wrapping at both ends, without switching the panel", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b", "c"])} />);
    tab("Tab a").focus();
    press(tab("Tab a"), "ArrowRight");
    expect(document.activeElement).toBe(tab("Tab b"));
    press(tab("Tab b"), "ArrowRight");
    press(tab("Tab c"), "ArrowRight");
    expect(document.activeElement).toBe(tab("Tab a"));
    press(tab("Tab a"), "ArrowLeft");
    expect(document.activeElement).toBe(tab("Tab c"));
    expect(tab("Tab a").getAttribute("aria-selected")).toBe("true");
    expect(tab("Tab c").getAttribute("aria-selected")).toBe("false");
    expect(screen.queryByText("Heading a")).not.toBeNull();
    expect(screen.queryByText("Heading c")).toBeNull();
  });

  it("moves the single tab stop with focus, leaving the selected tab as it was", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b", "c"])} />);
    tab("Tab a").focus();
    press(tab("Tab a"), "ArrowRight");
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    expect(screen.getAllByRole("tab").map((t) => t.getAttribute("aria-selected"))).toEqual(["true", "false", "false"]);
  });

  it("after arrowing to another tab and leaving the row, focus comes back to the selected tab", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b", "c"])} />);
    tab("Tab a").focus();
    press(tab("Tab a"), "ArrowRight");
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    act(() => { screen.getByRole("button", { name: "Action a" }).focus(); });     // focus leaves the row
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([0, -1, -1]);
    expect(tab("Tab a").getAttribute("aria-selected")).toBe("true");
  });

  it("Home and End jump to the first and last tab, and Up and Down do nothing", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b", "c"])} />);
    tab("Tab a").focus();
    press(tab("Tab a"), "End");
    expect(document.activeElement).toBe(tab("Tab c"));
    press(tab("Tab c"), "Home");
    expect(document.activeElement).toBe(tab("Tab a"));
    press(tab("Tab a"), "ArrowDown");
    press(tab("Tab a"), "ArrowUp");
    expect(document.activeElement).toBe(tab("Tab a"));
  });

  it("Enter selects the focused tab and shows its panel", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b"])} />);
    tab("Tab a").focus();
    press(tab("Tab a"), "ArrowRight");
    press(tab("Tab b"), "Enter");
    expect(tab("Tab b").getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByText("Heading b")).not.toBeNull();
    expect(screen.queryByText("Heading a")).toBeNull();
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(tab("Tab b").id);
  });

  it("Space selects the focused tab", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b"])} />);
    tab("Tab b").focus();
    press(tab("Tab b"), " ");
    expect(screen.queryByText("Heading b")).not.toBeNull();
  });

  it("a click selects the tab and makes it the tab stop", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b"])} />);
    fireEvent.click(tab("Tab b"));
    expect(screen.queryByText("Heading b")).not.toBeNull();
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([-1, 0]);
  });

  it("honors the initial tab", () => {
    render(<ToolTabs label="x" initial="b" tabs={make(["a", "b"])} />);
    expect(screen.queryByText("Heading b")).not.toBeNull();
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([-1, 0]);
  });

  it("renders nothing, without throwing, when there are no tabs", () => {
    const { container } = render(<ToolTabs label="x" tabs={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("uses the shared focus ring tokens on each tab", () => {
    render(<ToolTabs label="x" tabs={make(["a", "b"])} />);
    for (const t of screen.getAllByRole("tab")) {
      expect(t.className).toContain("focus-visible:ring-2");
      expect(t.className).toContain("focus-visible:ring-ring");
      expect(t.className).toContain("focus-visible:ring-offset-background");
      expect(t.className).toContain("focus-visible:outline-none");
    }
  });
});

function Removable({ ids }: { ids: string[] }) {
  return <ToolTabs label="x" tabs={make(ids)} />;
}

function Dropper() {
  const [ids, setIds] = useState(["a", "b"]);
  return (
    <div>
      <button type="button" onClick={() => setIds(["b"])}>drop a</button>
      <ToolTabs label="x" tabs={make(ids)} />
    </div>
  );
}

describe("ToolTabs when a tab disappears", () => {
  it("selects the first remaining tab when the selected tab is removed", () => {
    const { rerender } = render(<Removable ids={["a", "b", "c"]} />);
    rerender(<Removable ids={["b", "c"]} />);
    expect(tab("Tab b").getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByText("Heading b")).not.toBeNull();
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([0, -1]);
  });

  it("moves the tab stop to the selected tab when the focused tab is removed", () => {
    const { rerender } = render(<Removable ids={["a", "b", "c"]} />);
    tab("Tab a").focus();
    press(tab("Tab a"), "End");
    rerender(<Removable ids={["a", "b"]} />);
    expect(tab("Tab a").getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tab").map((t) => t.tabIndex)).toEqual([0, -1]);
    expect(document.activeElement).toBe(tab("Tab a"));
  });

  it("moves real focus to the new selected tab when the focused, selected tab is removed", () => {
    const { rerender } = render(<Removable ids={["a", "b"]} />);
    tab("Tab a").focus();
    rerender(<Removable ids={["b"]} />);
    expect(document.activeElement).toBe(tab("Tab b"));
  });

  it("moves focus to the selected tab when focus was inside a panel that is unmounted", () => {
    render(<Dropper />);
    const inside = screen.getByRole("button", { name: "Action a" });
    inside.focus();
    expect(document.activeElement).toBe(inside);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "drop a" })); });
    expect(document.activeElement).toBe(tab("Tab b"));
  });

  it("does not take focus back after the tabs went empty and came back", () => {
    function Toggle({ ids }: { ids: string[] }) {
      return (
        <div>
          <button type="button">outside</button>
          <ToolTabs label="x" tabs={make(ids)} />
        </div>
      );
    }
    const { rerender } = render(<Toggle ids={["a", "b"]} />);
    screen.getByRole("button", { name: "Action a" }).focus();
    rerender(<Toggle ids={[]} />);
    const outside = screen.getByRole("button", { name: "outside" });
    outside.focus();
    rerender(<Toggle ids={["a", "b"]} />);
    expect(document.activeElement).toBe(outside);
  });

  it("does not take focus from elsewhere on the page when a tab is removed", () => {
    render(<Dropper />);
    const drop = screen.getByRole("button", { name: "drop a" });
    drop.focus();
    fireEvent.click(drop);
    expect(document.activeElement).toBe(drop);
  });
});
