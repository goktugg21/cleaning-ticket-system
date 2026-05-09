/**
 * Sprint 16 — demo user fixtures.
 *
 * Mirrors backend/accounts/management/commands/seed_demo_data.py.
 * If the seed changes, update this file too (or refactor both to
 * read from a shared JSON fixture — left as a follow-up).
 */
export const DEMO_PASSWORD = "Demo12345!";

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
}

export const DEMO_USERS: Record<string, DemoUser> = {
  super: {
    email: "super@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "SUPER_ADMIN",
    buildings: ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
    fullName: "Super Admin",
  },
  companyAdmin: {
    email: "admin@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "COMPANY_ADMIN",
    buildings: ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
    fullName: "Company Admin",
  },
  managerAll: {
    email: "gokhan@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
    fullName: "Gokhan Koçak",
  },
  managerB1: {
    email: "murat@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: ["B1 Amsterdam"],
    fullName: "Murat Uğurlu",
  },
  managerB2: {
    email: "isa@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: ["B2 Amsterdam"],
    fullName: "İsa Uğurlu",
  },
  customerAll: {
    email: "tom@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: ["B1 Amsterdam", "B2 Amsterdam", "B3 Amsterdam"],
    fullName: "Tom Verbeek",
  },
  customerB1B2: {
    email: "iris@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: ["B1 Amsterdam", "B2 Amsterdam"],
    fullName: "Iris",
  },
  customerB3: {
    email: "amanda@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: ["B3 Amsterdam"],
    fullName: "Amanda",
  },
};
