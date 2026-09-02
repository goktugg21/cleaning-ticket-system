import { describe, expect, it } from "vitest";

import type { Contract } from "../../api/contracts.types";
import {
  amountPerPeriod,
  contractSentence,
  locationsText,
  monthYear,
} from "./contractSentence";

// The house stub: key + params, so the assertions pin KEY CHOICE and
// the params handed over — never the final prose, which is the
// bundles' own concern (nl/en lockstep is checked separately).
const t = (key: string, params?: Record<string, unknown>) =>
  `${key}|${JSON.stringify(params ?? {})}`;

const building = (id: number, name: string) => ({ id, name });

const base: Contract = {
  id: 1,
  company: 1,
  company_name: "Osius",
  customer: 3,
  customer_name: "B Amsterdam",
  contract_type: null,
  contract_type_name: null,
  contract_type_standard_slot: "",
  contract_no: "C-2026-0001",
  start_date: "2026-01-15",
  end_date: null,
  lifecycle: "ACTIVE",
  status: "ACTIVE",
  description: "",
  notes: "",
  billing_period: "MONTHLY",
  billing_day: 1,
  billing_type: "ADVANCE",
  payment_terms_days: 30,
  start_proration: false,
  buildings: [building(1, "B1"), building(2, "B2")],
  active_revision: null,
  monthly_amount: "850.00",
  yearly_amount: "10200.00",
  total_hours: "40.00",
  line_count: 3,
  projects: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("contractSentence", () => {
  it("zero lines wins over every branch, draft or not", () => {
    const expected = 'sentence.no_lines|{"customer":"B Amsterdam"}';
    expect(contractSentence({ ...base, line_count: 0 }, t, "en")).toBe(expected);
    expect(
      contractSentence(
        { ...base, line_count: 0, status: "DRAFT", lifecycle: "DRAFT" },
        t,
        "en",
      ),
    ).toBe(expected);
  });

  it("an active contract says who pays what for which lines where", () => {
    const s = contractSentence(base, t, "en");
    expect(s).toMatch(/^sentence\.pays\|/);
    expect(s).toContain('"customer":"B Amsterdam"');
    expect(s).toContain("sentence.line_count");
    expect(s).toContain('\\"count\\":3');
    expect(s).toContain('"locations":"B1 + B2"');
    expect(s).toContain("sentence.amount_MONTHLY");
    expect(s.endsWith(".")).toBe(true);
  });

  it("an open-ended contract must not claim an end", () => {
    const s = contractSentence(base, t, "en");
    expect(s).toContain('sentence.from|{"start":"Jan 2026"}');
    expect(s).not.toContain("sentence.from_to");
  });

  it("an end date makes the period run from start to end", () => {
    const s = contractSentence({ ...base, end_date: "2026-12-31" }, t, "en");
    expect(s).toContain('sentence.from_to|{"start":"Jan 2026","end":"Dec 2026"}');
    expect(s).not.toContain("sentence.from|");
  });

  it("names the billing day and whether the money moves before or after", () => {
    expect(contractSentence(base, t, "en")).toContain(
      'sentence.invoiced_ADVANCE|{"day":1}',
    );
    expect(
      contractSentence({ ...base, billing_type: "ARREARS", billing_day: 28 }, t, "en"),
    ).toContain('sentence.invoiced_ARREARS|{"day":28}');
  });

  it("a draft states the same facts and ends with the nothing-is-invoiced clause", () => {
    const s = contractSentence(
      { ...base, status: "DRAFT", lifecycle: "DRAFT" },
      t,
      "en",
    );
    expect(s).toMatch(/^sentence\.pays\|/);
    expect(s).toContain("sentence.invoiced_ADVANCE");
    expect(s.endsWith(" — sentence.draft_clause|{}.")).toBe(true);
  });

  it("a draft whose lines carry no money never claims the customer pays € 0.00", () => {
    const s = contractSentence(
      { ...base, status: "DRAFT", lifecycle: "DRAFT", monthly_amount: "0.00" },
      t,
      "en",
    );
    expect(s).toMatch(/^sentence\.has_lines\|/);
    expect(s).not.toContain("sentence.pays");
    expect(s).not.toContain("sentence.amount_MONTHLY");
    expect(s.endsWith(" — sentence.draft_clause|{}.")).toBe(true);
  });

  it("an active contract at € 0.00 still says so — that is the truth", () => {
    const s = contractSentence({ ...base, monthly_amount: "0.00" }, t, "en");
    expect(s).toMatch(/^sentence\.pays\|/);
  });
});

describe("amountPerPeriod", () => {
  it("speaks in the contract's own rhythm", () => {
    expect(amountPerPeriod(base, t, "en")).toMatch(/^sentence\.amount_MONTHLY\|/);
    expect(
      amountPerPeriod({ ...base, billing_period: "QUARTERLY" }, t, "en"),
    ).toMatch(/^sentence\.amount_QUARTERLY\|/);
    expect(
      amountPerPeriod({ ...base, billing_period: "YEARLY" }, t, "en"),
    ).toMatch(/^sentence\.amount_YEARLY\|/);
  });

  it("prefers the revision in force over the normalised figure", () => {
    const s = amountPerPeriod(
      {
        ...base,
        active_revision: {
          id: 9,
          label: "Initial",
          effective_from: "2026-01-15",
          amount: "900.00",
          hours: "40.00",
          line_count: 3,
        },
      },
      t,
      "en",
    );
    expect(s).toContain("900");
    expect(s).not.toContain("850");
  });
});

describe("locationsText", () => {
  it("joins up to three names and folds the rest", () => {
    expect(locationsText({ ...base, buildings: [] }, t)).toBe(
      "sentence.no_locations|{}",
    );
    expect(
      locationsText(
        { ...base, buildings: [building(1, "A"), building(2, "B"), building(3, "C")] },
        t,
      ),
    ).toBe("A + B + C");
    expect(
      locationsText(
        {
          ...base,
          buildings: [1, 2, 3, 4, 5].map((n) => building(n, `B${n}`)),
        },
        t,
      ),
    ).toBe('B1 + B2 + sentence.more_locations|{"count":3}');
  });
});

describe("monthYear", () => {
  it("prints short month and year, and never throws on junk", () => {
    expect(monthYear("2026-01-15", "en")).toBe("Jan 2026");
    expect(monthYear(null, "en")).toBe("");
    expect(monthYear("not-a-day", "en")).toBe("");
  });
});
