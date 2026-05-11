/**
 * Sprint 21 v2 — two-company demo user fixtures.
 *
 * Mirrors backend/accounts/management/commands/seed_demo_data.py. If
 * the seed changes, update this file too (or refactor both to read
 * from a shared JSON fixture — left as a follow-up).
 *
 * Two demo companies:
 *   Company A — "Osius Demo"        (Amsterdam, B1/B2/B3)
 *                personas live under @b-amsterdam.demo
 *   Company B — "Bright Facilities" (Rotterdam, R1/R2)
 *                personas live under @bright-facilities.demo
 *   Super admin lives under @cleanops.demo
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
    | "STAFF"
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
    email: "superadmin@cleanops.demo",
    password: DEMO_PASSWORD,
    role: "SUPER_ADMIN",
    buildings: [...COMPANY_A_BUILDINGS, ...COMPANY_B_BUILDINGS],
    fullName: "Super Admin",
    company: "both",
  },

  // ----- Company A — Osius Demo -----
  companyAdmin: {
    email: "ramazan-admin-osius@b-amsterdam.demo",
    password: DEMO_PASSWORD,
    role: "COMPANY_ADMIN",
    buildings: COMPANY_A_BUILDINGS,
    fullName: "Ramazan Koçak",
    company: "A",
  },
  managerAll: {
    email: "gokhan-manager-osius@b-amsterdam.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: COMPANY_A_BUILDINGS,
    fullName: "Gokhan Koçak",
    company: "A",
  },
  managerB1: {
    email: "murat-manager-osius@b-amsterdam.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: ["B1 Amsterdam"],
    fullName: "Murat Uğurlu",
    company: "A",
  },
  managerB2: {
    email: "isa-manager-osius@b-amsterdam.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: ["B2 Amsterdam"],
    fullName: "İsa Uğurlu",
    company: "A",
  },
  customerAll: {
    email: "tom-customer-b-amsterdam@b-amsterdam.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: COMPANY_A_BUILDINGS,
    fullName: "Tom Verbeek",
    company: "A",
  },
  customerB1B2: {
    email: "iris-customer-b-amsterdam@b-amsterdam.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: ["B1 Amsterdam", "B2 Amsterdam"],
    fullName: "Iris",
    company: "A",
  },
  customerB3: {
    email: "amanda-customer-b-amsterdam@b-amsterdam.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: ["B3 Amsterdam"],
    fullName: "Amanda",
    company: "A",
  },
  // Sprint 23B — Osius field staff (STAFF role). Has
  // BuildingStaffVisibility on every Osius building so the
  // "Request assignment" demo flow can fire on any Osius ticket.
  staffOsius: {
    email: "ahmet-staff-osius@b-amsterdam.demo",
    password: DEMO_PASSWORD,
    role: "STAFF",
    buildings: COMPANY_A_BUILDINGS,
    fullName: "Ahmet Yıldız",
    company: "A",
  },

  // ----- Company B — Bright Facilities -----
  companyAdminB: {
    email: "sophie-admin-bright@bright-facilities.demo",
    password: DEMO_PASSWORD,
    role: "COMPANY_ADMIN",
    buildings: COMPANY_B_BUILDINGS,
    fullName: "Sophie van Dijk",
    company: "B",
  },
  managerB: {
    email: "bram-manager-bright@bright-facilities.demo",
    password: DEMO_PASSWORD,
    role: "BUILDING_MANAGER",
    buildings: COMPANY_B_BUILDINGS,
    fullName: "Bram de Jong",
    company: "B",
  },
  customerBCo: {
    email: "lotte-customer-bright@bright-facilities.demo",
    password: DEMO_PASSWORD,
    role: "CUSTOMER_USER",
    buildings: COMPANY_B_BUILDINGS,
    fullName: "Lotte Visser",
    company: "B",
  },
  // Sprint 23B — Bright field staff (STAFF role). Proves cross-
  // company isolation also applies to STAFF: this user cannot
  // reach Osius tickets even with BuildingStaffVisibility on
  // every R-building.
  staffBright: {
    email: "noah-staff-bright@bright-facilities.demo",
    password: DEMO_PASSWORD,
    role: "STAFF",
    buildings: COMPANY_B_BUILDINGS,
    fullName: "Noah Bakker",
    company: "B",
  },
};
