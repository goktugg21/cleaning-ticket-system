import { describe, expect, it } from "vitest";

import {
  announceDone,
  clearDone,
  takeDone,
  type DoneAnnouncement,
} from "./doneBannerStore";

function fakeStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => map.get(k) ?? null,
    key: (i: number) => [...map.keys()][i] ?? null,
    removeItem: (k: string) => void map.delete(k),
    setItem: (k: string, v: string) => void map.set(k, v),
  };
}

const a: DoneAnnouncement = {
  title: "Draft made for B Amsterdam — €384.78.",
  body: "Nothing is sent. Next: check it, then issue.",
  actionLabel: "Check the draft",
  actionTo: "/invoices/17",
};

describe("doneBannerStore", () => {
  it("survives exactly one reload", () => {
    const s = fakeStorage();
    announceDone(s, "invoices", a);
    // First mount after the reload: still there.
    expect(takeDone(s, "invoices")).toEqual(a);
    // Second reload: gone.
    expect(takeDone(s, "invoices")).toBeNull();
    expect(s.getItem("guide.done.invoices")).toBeNull();
  });

  it("dismiss clears it before any reload", () => {
    const s = fakeStorage();
    announceDone(s, "hours", a);
    clearDone(s, "hours");
    expect(takeDone(s, "hours")).toBeNull();
  });

  it("page keys do not bleed into each other", () => {
    const s = fakeStorage();
    announceDone(s, "invoices", a);
    expect(takeDone(s, "contracts")).toBeNull();
    expect(takeDone(s, "invoices")).toEqual(a);
  });

  it("dispatches the DONE_EVENT for mounted hooks when a window exists", () => {
    const events: unknown[] = [];
    (globalThis as { window?: unknown }).window = {
      dispatchEvent: (event: unknown) => {
        events.push(event);
        return true;
      },
    };
    try {
      announceDone(fakeStorage(), "invoices", a);
      expect(events.length).toBe(1);
    } finally {
      delete (globalThis as { window?: unknown }).window;
    }
  });

  it("tolerates a missing storage and garbage content", () => {
    expect(takeDone(null, "invoices")).toBeNull();
    announceDone(null, "invoices", a); // no throw
    const s = fakeStorage();
    s.setItem("guide.done.invoices", "{not json");
    expect(takeDone(s, "invoices")).toBeNull();
    s.setItem("guide.done.invoices", JSON.stringify({ nonsense: true }));
    expect(takeDone(s, "invoices")).toBeNull();
    expect(s.getItem("guide.done.invoices")).toBeNull();
  });
});
