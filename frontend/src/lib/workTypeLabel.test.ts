/** P-15 4.5(b) — the pattern dialog's default kind of work, pinned:
 *  the company's fixed-work entry, never "Extra work", never a bare
 *  first option. */
import { describe, expect, it } from "vitest";

import { defaultWorkTypeId } from "./workTypeLabel";

describe("defaultWorkTypeId", () => {
  it("picks the fixed-work slot wherever it sits in the list", () => {
    expect(
      defaultWorkTypeId([
        { id: 4, standard_slot: "extra_work" },
        { id: 9, standard_slot: "fixed_work" },
        { id: 2, standard_slot: "machine" },
      ]),
    ).toBe(9);
  });

  it("never falls back to the first option", () => {
    expect(
      defaultWorkTypeId([
        { id: 4, standard_slot: "extra_work" },
        { id: 2, standard_slot: "" },
      ]),
    ).toBeNull();
  });

  it("an empty catalog has no default", () => {
    expect(defaultWorkTypeId([])).toBeNull();
  });
});
