/**
 * P-15 §1.2 — no hidden delete behind a pencil, pinned as vocabulary.
 *
 * P-14's S1/S2 family: on seven admin lists an "Edit" pencil was the
 * only door to a bulk toolbar holding Delete/Deactivate, and nothing
 * said so. The fix is ONE shared label — the `EditModeToggle` reads
 * `common:edit_mode.edit` — renamed to say what the mode IS ("Select
 * rows"), plus honest bulk-action words: Customers/Buildings call
 * their action what it does (Deactivate — the server archives), and
 * only Contracts (the one true hard delete of the seven) says Delete,
 * with its WhatHappens pre-read.
 *
 * This test pins the WORDS, in both locales, so a later sprint cannot
 * quietly re-label the toggle "Edit" or re-overstate a deactivate as
 * a delete. It reads the bundles the app ships, not a copy.
 */
import { describe, expect, it } from "vitest";

import enCommon from "../i18n/en/common.json";
import nlCommon from "../i18n/nl/common.json";
import enContracts from "../i18n/en/contracts.json";
import nlContracts from "../i18n/nl/contracts.json";

const en = enCommon as unknown as Record<string, string>;
const nl = nlCommon as unknown as Record<string, string>;

describe("the pencil says what the mode is", () => {
  it("the shared toggle reads Select rows in both locales", () => {
    expect(en["edit_mode.edit"]).toBe("Select rows");
    expect(nl["edit_mode.edit"]).toBe("Rijen selecteren");
    // Services' private pair says the same thing.
    expect(en["services.list_edit_start"]).toBe("Select rows");
    expect(nl["services.list_edit_start"]).toBe("Rijen selecteren");
  });

  it("a deactivate is never called a delete", () => {
    for (const bundle of [en, nl]) {
      for (const key of ["customers.bulk_delete", "buildings.bulk_delete"]) {
        const label = bundle[key].toLowerCase();
        expect(label).not.toContain("delete");
        expect(label).not.toContain("verwijder");
      }
    }
    expect(en["customers.bulk_delete"]).toBe("Deactivate");
    expect(nl["customers.bulk_delete"]).toBe("Deactiveren");
    expect(en["buildings.bulk_delete"]).toBe("Deactivate");
    expect(nl["buildings.bulk_delete"]).toBe("Deactiveren");
  });

  it("the contracts delete carries its WhatHappens pre-read", () => {
    const enTable = (enContracts as { table: Record<string, string> }).table;
    const nlTable = (nlContracts as { table: Record<string, string> }).table;
    // What goes, what stays.
    expect(enTable.whatBulkDelete).toContain("permanently");
    expect(enTable.whatBulkDelete).toContain("invoices already made stay");
    expect(nlTable.whatBulkDelete).toContain("definitief");
    expect(nlTable.whatBulkDelete).toContain("facturen blijven");
    // The money-bearing row says why it cannot be picked.
    expect(enTable.rowHasInvoices).toContain("cannot be deleted");
    expect(nlTable.rowHasInvoices).toContain("kan niet worden verwijderd");
  });
});
