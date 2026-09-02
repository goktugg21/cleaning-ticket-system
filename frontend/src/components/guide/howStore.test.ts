import { describe, expect, it } from "vitest";

import { howClosed, rememberHow } from "./howStore";
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

describe("howStore — the fold's memory (P-13 §D.24 rule 8)", () => {
  it("opens by default the first time", () => {
    expect(howClosed(fakeStorage(), "invoices")).toBe(false);
  });
  it("closed stays closed, per page", () => {
    const storage = fakeStorage();
    rememberHow(storage, "invoices", false);
    expect(howClosed(storage, "invoices")).toBe(true);
    expect(howClosed(storage, "hours")).toBe(false);
  });
  it("re-opening deliberately forgets closed", () => {
    const storage = fakeStorage();
    rememberHow(storage, "invoices", false);
    rememberHow(storage, "invoices", true);
    expect(howClosed(storage, "invoices")).toBe(false);
  });
  it("tolerates a missing storage and garbage content", () => {
    expect(howClosed(null, "invoices")).toBe(false);
    rememberHow(null, "invoices", false); // must not throw
    const storage = fakeStorage();
    storage.data["guide.how.invoices"] = "garbage";
    expect(howClosed(storage, "invoices")).toBe(false);
  });
  it("a throwing storage reads as never-closed", () => {
    const storage: StorageLike = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(howClosed(storage, "invoices")).toBe(false);
    rememberHow(storage, "invoices", false); // must not throw
  });
});
