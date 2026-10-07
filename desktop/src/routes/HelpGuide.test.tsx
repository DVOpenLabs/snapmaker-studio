// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { USER_GUIDE_LABEL, USER_GUIDE_URL } from "@/lib/guide";

// The two panels that reach the network or the engine are not what is under test here.
vi.mock("@/components/SupportBundle", () => ({ SupportBundle: () => null }));
vi.mock("@/components/UpdateCheck", () => ({ UpdateCheck: () => null }));

import BeginnerWorkflow from "./BeginnerWorkflow";
import Help from "./Help";

afterEach(cleanup);
const page = (el: JSX.Element) => render(<MemoryRouter>{el}</MemoryRouter>);

describe("the guide link on Help and Get Started", () => {
  it("Help links to the step-by-step guide, opening outside the app", () => {
    page(<Help />);
    const a = screen.getByRole("link", { name: new RegExp(USER_GUIDE_LABEL) });
    expect(a.getAttribute("href")).toBe(USER_GUIDE_URL);
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("rel")).toContain("noreferrer");
  });

  it("Get Started links to it too", () => {
    page(<BeginnerWorkflow />);
    expect(screen.getByRole("link", { name: new RegExp(USER_GUIDE_LABEL) }).getAttribute("href")).toBe(USER_GUIDE_URL);
  });

  it("no longer says model downloads are not supported", () => {
    page(<Help />);
    expect(document.body.textContent).not.toMatch(/No downloads yet/);
    expect(document.body.textContent).toMatch(/Studio adds supported downloads to your Library/);
    cleanup();
    page(<BeginnerWorkflow />);
    expect(document.body.textContent).not.toMatch(/doesn't import for you/);
  });

  it("keeps the existing help content", () => {
    page(<Help />);
    expect(screen.getByText("The Doctors")).toBeTruthy();
    expect(screen.getByText(/Fix & diagnose tools/)).toBeTruthy();
  });
});
