import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { notifyResourceChanged, useResourceSync, type ResourceKind } from "./resourceSync";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

// This is the one piece of pure-ish, safety-relevant frontend logic this
// milestone's audit repeatedly flagged as worth testing once a runner
// existed (see PHASE_6A_CROSS_PAGE_STATE_SYNCHRONIZATION_SUMMARY.md
// section 4): the resource-kind strings are plain, unchecked at
// runtime, and a typo here would silently break cross-tab sync with no
// build error. These tests exercise the real localStorage/storage-event/
// visibility mechanism, not a mock of it.

let container: HTMLDivElement;
let root: Root;

function mountUseResourceSync(kinds: ResourceKind[], onStale: () => void) {
  function Host() {
    useResourceSync(kinds, onStale);
    return null;
  }
  act(() => {
    root.render(createElement(Host));
  });
}

beforeEach(() => {
  localStorage.clear();
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

describe("notifyResourceChanged", () => {
  it("writes a timestamped key to localStorage under the resource kind", () => {
    notifyResourceChanged("agents");
    const value = localStorage.getItem("pr:resource-changed:agents");
    expect(value).not.toBeNull();
    expect(Number(value)).not.toBeNaN();
  });

  it("never throws even if localStorage access fails", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked by private browsing");
    });
    expect(() => notifyResourceChanged("policies")).not.toThrow();
    spy.mockRestore();
  });
});

describe("useResourceSync", () => {
  it("does not fire on mount by itself", () => {
    const onStale = vi.fn();
    mountUseResourceSync(["agents"], onStale);
    expect(onStale).not.toHaveBeenCalled();
  });

  it("fires when a storage event arrives for a subscribed kind", () => {
    const onStale = vi.fn();
    mountUseResourceSync(["agents"], onStale);
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "pr:resource-changed:agents", newValue: "123" })
      );
    });
    expect(onStale).toHaveBeenCalledTimes(1);
  });

  it("ignores a storage event for a kind it did not subscribe to", () => {
    const onStale = vi.fn();
    mountUseResourceSync(["agents"], onStale);
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "pr:resource-changed:policies", newValue: "123" })
      );
    });
    expect(onStale).not.toHaveBeenCalled();
  });

  it("fires when the tab regains visibility", () => {
    const onStale = vi.fn();
    mountUseResourceSync(["decisions"], onStale);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(onStale).toHaveBeenCalledTimes(1);
  });

  it("debounces rapid repeated triggers within the minimum refresh interval", () => {
    const onStale = vi.fn();
    mountUseResourceSync(["agents"], onStale);
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "pr:resource-changed:agents", newValue: "1" })
      );
      window.dispatchEvent(
        new StorageEvent("storage", { key: "pr:resource-changed:agents", newValue: "2" })
      );
      window.dispatchEvent(
        new StorageEvent("storage", { key: "pr:resource-changed:agents", newValue: "3" })
      );
    });
    // All three arrive well inside MIN_REFRESH_INTERVAL_MS (3000ms) of
    // each other, so only the first should actually call onStale -- this
    // is what prevents a refetch storm from rapid alt-tabbing.
    expect(onStale).toHaveBeenCalledTimes(1);
  });

  it("cleans up its listeners on unmount", () => {
    const onStale = vi.fn();
    mountUseResourceSync(["agents"], onStale);
    act(() => {
      root.unmount();
    });
    act(() => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: "pr:resource-changed:agents", newValue: "1" })
      );
    });
    expect(onStale).not.toHaveBeenCalled();
  });
});
