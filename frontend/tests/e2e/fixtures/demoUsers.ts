/**
 * Sprint 21 — two-company demo user fixtures.
 *
 * Mirrors backend/accounts/management/commands/seed_demo_data.py. If
 * the seed changes, update this file too (or refactor both to read
 * from a shared JSON fixture — left as a follow-up).
 *
 * Two demo companies:
 *   Company A — "Osius Demo"        (Amsterdam, B1/B2/B3)
 *   Company B — "Bright Facilities" (Rotterdam, R1/R2)
 */
export const DEMO_PASSWORD = "Demo12345!";

export const COMPANY_A_NAME = "Osius Demo";
export const COMPANY_B_NAME = "Bright Facilities";

export const COMPANY_A_BUILDINGS = ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"];
export const COMPANY_B_BUILDINGS = ["R1 Rotterdam", "R2 Rotterdam"];

export interface DemoUser {
  email: string;
  password: string;
  role:
    | "SUPER_ADMIN"
    | "COMPANY_ADMIN"
    | "BUILDING_MANAGER"
    | "CUSTOMER_USER";
  // Buildings the user has access to (manager assignment OR per-customer
  // building access for customer users). Used by the scope tests to
  // assert what each demo persona should and should not see.
  buildings: string[];
  fullName: string;
  // Which demo company the user belongs to. "both" only applies to the
  // super admin who spans both companies.
  company: "A" | "B" | "both";
}

export const DEMO_USERS: Record<string, DemoUser> = {
  // ----- Super admin (spans both companies) -----
  super: {
    email: "super@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "SUPER_ADMIN",
    buildings: [...COMPANY_A_BUILDINGS, ...COMPANY_B_BUILDINGS],
    fullName: "Super Admin",
    company: "both",
  },

  // ----- Company A — Osius Demo -----
  companyAdmin: {
    email: "admin@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "COMPANY_ADMIN",
    buildings: COMPANY_A_BUILDINGS,
    fullName: "Company Admin",
    company: "A",
  },
  managerAll: {
    email: "gokhan@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: COMPANY_A_BUILDINGS,
    fullName: "Gokhan Koçak",
    company: "A",
  },
  managerB1: {
    email: "murat@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: ["B1 Amsterdam"],
    fullName: "Murat Uğurlu",
    company: "A",
  },
  managerB2: {
    email: "isa@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: ["B2 Amsterdam"],
    fullName: "İsa Uğurlu",
    company: "A",
  },
  customerAll: {
    email: "tom@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: COMPANY_A_BUILDINGS,
    fullName: "Tom Verbeek",
    company: "A",
  },
  customerB1B2: {
    email: "iris@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: ["B1 Amsterdam", "B2 Amsterdam"],
    fullName: "Iris",
    company: "A",
  },
  customerB3: {
    email: "amanda@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: ["B3 Amsterdam"],
    fullName: "Amanda",
    company: "A",
  },

  // ----- Company B — Bright Facilities -----
  companyAdminB: {
    email: "admin-b@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "COMPANY_ADMIN",
    buildings: COMPANY_B_BUILDINGS,
    fullName: "Sophie van Dijk",
    company: "B",
  },
  managerB: {
    email: "manager-b@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: COMPANY_B_BUILDINGS,
    fullName: "Bram de Jong",
    company: "B",
  },
  customerBCo: {
    email: "customer-b@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: COMPANY_B_BUILDINGS,
    fullName: "Lotte Visser",
    company: "B",
  },
};
