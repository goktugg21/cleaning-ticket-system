import { describe, expect, it } from "vitest";

import { howOpen, rememberHow } from "./howStore";
import type { StorageLike } from "./howStore";

function fakeStorage(): StorageLike & { data: Record<string, string> } {
  const data: Record<string, string> = {};
  return {
    data,
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => {
      data[key] = value;
    },
  };
}

describe("howStore — the fold's memory (P-14 A3: closed by default)", () => {
  it("starts closed the first time", () => {
    expect(howOpen(fakeStorage(), "invoices")).toBe(false);
  });
  it("open is remembered, per page", () => {
    const storage = fakeStorage();
    rememberHow(storage, "invoices", true);
    expect(howOpen(storage, "invoices")).toBe(true);
    expect(howOpen(storage, "hours")).toBe(false);
  });
  it("closing deliberately forgets open", () => {
    const storage = fakeStorage();
    rememberHow(storage, "invoices", true);
    rememberHow(storage, "invoices", false);
    expect(howOpen(storage, "invoices")).toBe(false);
  });
  it("the pre-A3 stored 'closed' still reads as closed", () => {
    const storage = fakeStorage();
    storage.data["guide.how.invoices"] = "closed";
    expect(howOpen(storage, "invoices")).toBe(false);
  });
  it("tolerates a missing storage and garbage content", () => {
    expect(howOpen(null, "invoices")).toBe(false);
    rememberHow(null, "invoices", true); // must not throw
    const storage = fakeStorage();
    storage.data["guide.how.invoices"] = "garbage";
    expect(howOpen(storage, "invoices")).toBe(false);
  });
  it("a throwing storage reads as closed", () => {
    const storage: StorageLike = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(howOpen(storage, "invoices")).toBe(false);
    rememberHow(storage, "invoices", true); // must not throw
  });
});
