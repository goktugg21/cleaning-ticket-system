/**
 * P-10 B1/B2 — the Extra work list's chip words are the ticket's own
 * words, and each tab opens on the chip with work to do.
 *
 * The owner: "Don't tickets have their own statuses? Why aren't you
 * using them?" So the Approved tab's chips point at the
 * `common:ticket_status.*` keys the ticket itself shows, and the shared
 * `common:phase.ew.*` values every badge and banner reads carry the
 * SAME word in both locales — pinned against the real bundles, so a
 * future edit to one side without the other fails here, not on a
 * screen.
 */
import { describe, expect, it } from "vitest";

import enCommon from "../i18n/en/common.json";
import nlCommon from "../i18n/nl/common.json";
import enStaffSlots from "../i18n/en/staff_slots.json";
import nlStaffSlots from "../i18n/nl/staff_slots.json";
import type { ExtraWorkDisplayPhase } from "../api/types";
import {
  ALL_CHIP,
  DEFAULT_CHIP,
  EXTRA_WORK_TABS,
  SUB_CHIPS,
  TAB_OF_PHASE,
  chipFromParam,
  deepLinkTarget,
} from "./extraWorkTabs";

// The bundles are flat `{ "dotted.key": "word" }` files; their inferred
// literal types are too wide/narrow to assign directly, so they go
// through `unknown` and are read as strings.
type Bundle = Record<string, string>;
const common: Record<"en" | "nl", Bundle> = {
  en: enCommon as unknown as Bundle,
  nl: nlCommon as unknown as Bundle,
};
const staffSlots: Record<"en" | "nl", Bundle> = {
  en: enStaffSlots as unknown as Bundle,
  nl: nlStaffSlots as unknown as Bundle,
};
const LOCALES = ["en", "nl"] as const;

/** The five phases whose word is a ticket status word (P-10 B1). */
const TICKET_WORD_OF_PHASE: ReadonlyArray<[ExtraWorkDisplayPhase, string]> = [
  ["SCHEDULED", "ticket_status.acknowledged"],
  ["IN_EXECUTION", "ticket_status.in_progress"],
  ["WAITING_MANAGER_CHECK", "ticket_status.waiting_manager_review"],
  ["WAITING_COMPLETION_APPROVAL", "ticket_status.waiting_customer_approval"],
  ["DONE", "ticket_status.approved"],
];

describe("the Approved tab's chips are the ticket's own status words", () => {
  const approvedChips = SUB_CHIPS.approved.filter((chip) => chip !== ALL_CHIP);

  it("every narrowing chip on Approved resolves in the common namespace", () => {
    expect(approvedChips.length).toBeGreaterThan(0);
    for (const chip of approvedChips) {
      expect(chip.labelKey.startsWith("common:")).toBe(true);
      const key = chip.labelKey.slice("common:".length);
      for (const locale of LOCALES) {
        expect(common[locale][key], `${locale} ${key}`).toBeTruthy();
      }
    }
  });

  it("the four ticket-status chips point at ticket_status.* keys, in the order the work moves", () => {
    const ticketChips = approvedChips.filter((chip) =>
      chip.labelKey.startsWith("common:ticket_status."),
    );
    expect(ticketChips.map((chip) => chip.labelKey)).toEqual([
      "common:ticket_status.acknowledged",
      "common:ticket_status.in_progress",
      "common:ticket_status.waiting_manager_review",
      "common:ticket_status.waiting_customer_approval",
    ]);
    // The manager's check sits between In progress and the customer.
    expect(approvedChips.map((chip) => chip.key)).toEqual([
      "not_planned",
      "scheduled",
      "in_progress",
      "manager_check",
      "customer_check",
    ]);
  });

  it("the Not planned yet chip is the schedule's zone word, through the shared phase key", () => {
    const chip = approvedChips.find((c) => c.key === "not_planned");
    expect(chip?.labelKey).toBe("common:phase.ew.WAITING_PLANNING");
    for (const locale of LOCALES) {
      expect(common[locale]["phase.ew.WAITING_PLANNING"]).toBe(
        staffSlots[locale]["agenda.undated_title"],
      );
    }
  });

  it("the Finished tab's DONE chip asks the operator's question, To invoice (B2)", () => {
    const done = SUB_CHIPS.finished.find((chip) => chip.phases?.includes("DONE"));
    expect(done?.labelKey).toBe("tabs.chip_to_invoice");
  });

  it("each chip narrows to exactly the phase its word names", () => {
    for (const [phase, key] of TICKET_WORD_OF_PHASE) {
      const tab = TAB_OF_PHASE[phase];
      expect(tab === "approved" || tab === "finished").toBe(true);
      const chips = SUB_CHIPS[tab as "approved" | "finished"].filter((chip) =>
        chip.phases?.includes(phase),
      );
      expect(chips, phase).toHaveLength(1);
      // B2 — the Finished tab's DONE chip is the operator's question
      // ("To invoice"); the row badge beside it carries the status word.
      expect(chips[0].labelKey).toBe(phase === "DONE" ? "tabs.chip_to_invoice" : `common:${key}`);
    }
  });
});

describe("the shared phase.ew.* values carry the same word as the ticket status (both locales)", () => {
  for (const [phase, key] of TICKET_WORD_OF_PHASE) {
    for (const locale of LOCALES) {
      it(`${locale}: phase.ew.${phase} === ${key}`, () => {
        const word = common[locale][key];
        expect(word).toBeTruthy();
        expect(common[locale][`phase.ew.${phase}`]).toBe(word);
      });
    }
  }

  it("the ticket's own IN_EXECUTION phase word is the In progress status word too", () => {
    for (const locale of LOCALES) {
      expect(common[locale]["phase.ticket.IN_EXECUTION"]).toBe(
        common[locale]["ticket_status.in_progress"],
      );
    }
  });

  it("the deleted parallel words are gone from the phase keys", () => {
    const banned = {
      en: ["Busy", "Planned", "To plan", "Done, check it"],
      nl: ["Bezig", "Nog plannen", "Klaar, controleer"],
    };
    for (const locale of LOCALES) {
      for (const key of Object.keys(common[locale]).filter((k) => k.startsWith("phase.ew."))) {
        expect(banned[locale], `${locale} ${key}`).not.toContain(common[locale][key]);
      }
      expect(banned[locale]).not.toContain(common[locale]["phase.ticket.IN_EXECUTION"]);
    }
  });
});

describe("WAITING_MANAGER_CHECK is placed", () => {
  it("sits on the Approved tab and deep-links to its own chip", () => {
    expect(TAB_OF_PHASE.WAITING_MANAGER_CHECK).toBe("approved");
    expect(deepLinkTarget("WAITING_MANAGER_CHECK")).toEqual({
      bucket: "approved",
      chip: "manager_check",
    });
  });
});

describe("each tab opens on the chip with work to do (P-10 B2)", () => {
  it("names a chip of its own tab, and All stays one click away", () => {
    for (const tab of EXTRA_WORK_TABS) {
      const keys = SUB_CHIPS[tab].map((chip) => chip.key);
      expect(keys, tab).toContain(DEFAULT_CHIP[tab]);
      expect(keys, tab).toContain(ALL_CHIP.key);
    }
  });

  it("Approved opens on Not planned yet, To price on All, With the customer on Waiting, Finished on the DONE chip", () => {
    expect(DEFAULT_CHIP).toEqual({
      "to-price": "all",
      "with-customer": "waiting",
      approved: "not_planned",
      finished: "to_invoice",
    });
  });

  it("a missing or unknown ?chip= means the default; a known one is itself", () => {
    expect(chipFromParam("approved", null)).toBeNull();
    expect(chipFromParam("approved", "")).toBeNull();
    expect(chipFromParam("approved", "declined")).toBeNull();
    expect(chipFromParam("approved", "in_progress")).toBe("in_progress");
    expect(chipFromParam("approved", "all")).toBe("all");
    expect(chipFromParam("with-customer", "declined")).toBe("declined");
  });

  it("a ?status= deep link still preselects the matching chip", () => {
    expect(deepLinkTarget("CUSTOMER_REJECTED")).toEqual({
      bucket: "with-customer",
      chip: "declined",
    });
    expect(deepLinkTarget("CUSTOMER_APPROVED")).toEqual({
      bucket: "approved",
      chip: "not_planned",
    });
    expect(deepLinkTarget("IN_PROGRESS")).toEqual({ bucket: "approved", chip: "in_progress" });
    expect(deepLinkTarget("CANCELLED")).toEqual({ bucket: "cancelled", chip: null });
    expect(deepLinkTarget("nonsense")).toBeNull();
  });
});
