import { describe, expect, it } from "vitest";

import { atRiskRowHref, dueRowHref } from "./rowLink";
import { pickSeedCompany } from "./useCompanyScope";

describe("rowLink — the two Invoices tables' row targets (P-13 O3)", () => {
  it("an at-risk row opens the job: the spawned ticket, else the request", () => {
    expect(atRiskRowHref({ ticket_id: 497, extra_work_id: 151 })).toBe(
      "/tickets/497",
    );
    expect(atRiskRowHref({ ticket_id: null, extra_work_id: 151 })).toBe(
      "/extra-work/151",
    );
  });
  it("a due row opens the customer's own invoices surface", () => {
    expect(dueRowHref({ customer: 3 })).toBe("/admin/customers/3/invoices");
  });
});

describe("pickSeedCompany — the W2 chain, explicit", () => {
  const companies = [
    { id: 9, name: "Zeta Clean" },
    { id: 4, name: "Alpha Clean" },
  ];
  it("the company with something DUE wins", () => {
    const rows = [
      { company: 9, is_due: false, unbilled_count: 2 },
      { company: 4, is_due: true, unbilled_count: 1 },
    ];
    expect(pickSeedCompany(rows, companies)).toBe(4);
  });
  it("else the company with something waiting", () => {
    const rows = [
      { company: 9, is_due: false, unbilled_count: 0 },
      { company: 4, is_due: false, unbilled_count: 1 },
    ];
    expect(pickSeedCompany(rows, companies)).toBe(4);
  });
  it("else the first due row's company", () => {
    const rows = [{ company: 9, is_due: false, unbilled_count: 0 }];
    expect(pickSeedCompany(rows, companies)).toBe(9);
  });
  it("with no due rows at all, the first company by NAME — the page is never unresolved", () => {
    expect(pickSeedCompany([], companies)).toBe(4);
  });
  it("with nothing at all, null (the selector is not rendered anyway)", () => {
    expect(pickSeedCompany([], [])).toBeNull();
  });
});
