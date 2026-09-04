import { describe, expect, it } from "vitest";

import { takeHighlight, withHighlight } from "./highlight";

describe("takeHighlight", () => {
  it("consumes the param and reports the change", () => {
    const params = new URLSearchParams("tab=drafts&highlight=17");
    expect(takeHighlight(params)).toEqual({ id: "17", changed: true });
    expect(params.toString()).toBe("tab=drafts");
  });

  it("absent param changes nothing", () => {
    const params = new URLSearchParams("tab=drafts");
    expect(takeHighlight(params)).toEqual({ id: null, changed: false });
    expect(params.toString()).toBe("tab=drafts");
  });

  it("an empty value is stripped but highlights nothing", () => {
    const params = new URLSearchParams("highlight=");
    expect(takeHighlight(params)).toEqual({ id: null, changed: true });
    expect(params.toString()).toBe("");
  });
});

describe("withHighlight", () => {
  it("appends with ? or & as the path needs", () => {
    expect(withHighlight("/invoices", 17)).toBe("/invoices?highlight=17");
    expect(withHighlight("/invoices?tab=drafts", 17)).toBe(
      "/invoices?tab=drafts&highlight=17",
    );
  });
});
