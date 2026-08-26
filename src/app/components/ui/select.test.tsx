import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Select } from "./select";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
});

// Final Product Polish (found via browser QA): PolicyListPage's "Sort
// by" select passes `style={{ padding: "6px 10px", ... }}` -- a
// shorthand. Select's own first implementation spread the caller's
// style AFTER its `paddingRight: 30` (reserving room for the chevron
// icon), so the shorthand's `padding` silently reset paddingRight back
// to 10px when React applied the merged style object to the DOM,
// leaving the icon overlapping the select's own text with no reserved
// space. Fixed by spreading the caller's style FIRST, then applying
// appearance/paddingRight after -- those three properties must always
// win, regardless of how the caller expressed its own padding.
describe("Select", () => {
  it("keeps chevron padding even when the caller sets a padding shorthand", () => {
    act(() => {
      root.render(
        createElement(
          Select,
          { value: "a", onChange: () => {}, style: { padding: "6px 10px", backgroundColor: "red" } },
          createElement("option", { value: "a" }, "A")
        )
      );
    });
    const select = container.querySelector("select") as HTMLSelectElement;
    expect(select.style.paddingRight).toBe("30px");
    // The caller's own colors/other properties still apply.
    expect(select.style.backgroundColor).toBe("red");
  });

  it("renders a visible chevron icon overlay", () => {
    act(() => {
      root.render(
        createElement(
          Select,
          { value: "a", onChange: () => {} },
          createElement("option", { value: "a" }, "A")
        )
      );
    });
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
