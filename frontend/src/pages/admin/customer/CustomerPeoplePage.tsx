// SoT Addendum A.2 — People consolidation page.
//
// ONE page that lists a customer's people, each row carrying a TYPE
// badge (Contact / Employee / User). The three concepts stay DISTINCT:
//   * Contact — a communication-only person (phone book). No login.
//   * Employee — a User who holds per-building access (or is a
//     company-wide CCA). The "access" facet.
//   * User — an authenticated principal (a customer membership).
// A single person can carry MORE THAN ONE badge (a User with building
// access is both User + Employee; a linked Contact is Contact + User).
//
// Sources merged here (deduped on the user-id bridge):
//   * listCustomerUsers   → memberships → User principals (carry
//                           is_company_admin + the per-row actions).
//   * listCustomerEmployees → the collapsed effective customer access
//                           role (now CCA-flag-aware) → the access facet.
//   * listCustomerContacts → Contact rows; Contact.user bridges a linked
//                           contact onto its user so it isn't a duplicate.
//
// Interaction is DRILL-IN, not accordion: clicking a row opens a modal
// to manage that person, then you leave.
//   * A User row → CustomerUserManageModal (company-admin toggle +
//     per-building access editor + permission overrides), reusing the
//     proven ContactPermissionsPanel lifecycle.
//   * A non-user Contact row → a hint pointing at the Contacts page for
//     the detail + promote flow (Contacts are not Users; promotion is a
//     separate explicit flow that lives on that page).
//
// View-first: the page lands read-only; the modal is the only mutable
// surface. "No data dumps": >10 people surfaces a search box.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  getCustomer,
  listCustomerContacts,
  listCustomerEmployees,
  listCustomerUsers,
} from "../../../api/admin";
import type {
  Contact,
  CustomerAccessRole,
  CustomerAdmin,
  CustomerEmployee,
  CustomerUserMembership,
} from "../../../api/types";
import { AccessRoleBadge } from "../../../components/AccessRoleBadge";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";
import { CustomerUserManageModal } from "./CustomerUserManageModal";

// One merged person. `userId` is the bridge identity when the person is
// a User (membership) or a linked Contact; a standalone Contact keys on
// its contact id instead. `kinds` drives the type badges.
interface PersonRow {
  // Stable React key + identity. "user:<id>" for a principal, or
  // "contact:<id>" for a non-user contact.
  key: string;
  // The user id when this person is (or links to) a User; null for a
  // standalone non-user contact.
  userId: number | null;
  // The contact id when a Contact row exists for this person.
  contactId: number | null;
  name: string;
  email: string;
  isUser: boolean;
  isEmployee: boolean;
  isContact: boolean;
  isCompanyAdmin: boolean;
  accessRole: CustomerAccessRole | null;
}

function buildPeople(
  members: CustomerUserMembership[],
  employees: CustomerEmployee[],
  contacts: Contact[],
): PersonRow[] {
  const byUserId = new Map<number, PersonRow>();

  // 1. Users (memberships) — the principal facet.
  for (const m of members) {
    byUserId.set(m.user_id, {
      key: `user:${m.user_id}`,
      userId: m.user_id,
      contactId: null,
      name: m.user_full_name || m.user_email,
      email: m.user_email,
      isUser: true,
      isEmployee: m.is_company_admin === true,
      isContact: false,
      isCompanyAdmin: m.is_company_admin === true,
      accessRole: m.is_company_admin ? "CUSTOMER_COMPANY_ADMIN" : null,
    });
  }

  // 2. Employees — the access facet. The effective access role is now
  //    CCA-flag-aware on the backend, so a company-wide CCA reports
  //    CUSTOMER_COMPANY_ADMIN here too. A non-null role marks the
  //    Employee badge.
  for (const e of employees) {
    const existing = byUserId.get(e.id);
    if (existing) {
      existing.isEmployee = existing.isEmployee || e.customer_access_role !== null;
      if (e.customer_access_role) existing.accessRole = e.customer_access_role;
    } else {
      byUserId.set(e.id, {
        key: `user:${e.id}`,
        userId: e.id,
        contactId: null,
        name: e.full_name || e.email,
        email: e.email,
        isUser: true,
        isEmployee: e.customer_access_role !== null,
        isContact: false,
        isCompanyAdmin: e.customer_access_role === "CUSTOMER_COMPANY_ADMIN",
        accessRole: e.customer_access_role,
      });
    }
  }

  // 3. Contacts — the communication facet. A linked contact (user set)
  //    merges onto its user via the bridge; a standalone contact becomes
  //    its own row keyed on the contact id.
  const standalone: PersonRow[] = [];
  for (const c of contacts) {
    if (c.user !== null && byUserId.has(c.user)) {
      const existing = byUserId.get(c.user)!;
      existing.isContact = true;
      existing.contactId = c.id;
    } else {
      standalone.push({
        key: `contact:${c.id}`,
        userId: c.user,
        contactId: c.id,
        name: c.full_name || c.email,
        email: c.email,
        isUser: c.user !== null,
        isEmployee: false,
        isContact: true,
        isCompanyAdmin: false,
        accessRole: null,
      });
    }
  }

  const merged = [...byUserId.values(), ...standalone];
  merged.sort((a, b) => a.name.localeCompare(b.name));
  return merged;
}

export function CustomerPeoplePage() {
  const { id } = useParams();
  const { t } = useTranslation("common");

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [people, setPeople] = useState<PersonRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  // Drill-in modal target. Holds the user id + label for the modal.
  const [managing, setManaging] = useState<{
    userId: number;
    label: string;
  } | null>(null);

  async function loadPeople(customerId: number) {
    // Each non-membership read tolerates a 403/404 for the current
    // operator by collapsing to an empty result, mirroring the Overview
    // page's defensive parallel load.
    const [customerData, membersResp, employeesResp, contactsResp] =
      await Promise.all([
        getCustomer(customerId),
        listCustomerUsers(customerId).catch(() => ({
          count: 0,
          next: null,
          previous: null,
          results: [] as CustomerUserMembership[],
        })),
        listCustomerEmployees(customerId).catch(() => ({
          count: 0,
          next: null,
          previous: null,
          results: [] as CustomerEmployee[],
        })),
        listCustomerContacts(customerId).catch(() => [] as Contact[]),
      ]);
    return {
      customerData,
      people: buildPeople(
        membersResp.results,
        employeesResp.results,
        contactsResp,
      ),
    };
  }

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) {
          setError(t("bm_customer_detail.invalid_id"));
          setLoading(false);
        }
      });
      return () => {
        cancelled = true;
      };
    }
    (async () => {
      try {
        const { customerData, people: rows } = await loadPeople(numericId);
        if (cancelled) return;
        setCustomer(customerData);
        setPeople(rows);
        setError("");
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(getApiError(err));
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [numericId, t]);

  async function refresh() {
    if (numericId === null) return;
    try {
      const { people: rows } = await loadPeople(numericId);
      setPeople(rows);
      setError("");
    } catch (err) {
      setError(getApiError(err));
    }
  }

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;

  const filteredPeople = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return people;
    return people.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.email.toLowerCase().includes(q),
    );
  }, [people, search]);

  // "No data dumps": only show the search box once the list is long.
  const showSearch = people.length > 10;

  return (
    <div data-testid="customer-people-page">
      <CustomerSubPageHeader customerName={customerName} isActive={isActive} />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && !customer ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <>
          <p
            className="section-explainer"
            data-testid="customer-people-explainer"
          >
            {t("customer_people.explainer", { customer: customerName })}
          </p>

          <section
            className="card"
            data-testid="section-customer-people"
            style={{ padding: "20px 22px" }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                flexWrap: "wrap",
                marginBottom: 12,
              }}
            >
              <div>
                <h3 className="section-title" style={{ margin: 0 }}>
                  {t("customer_people.title")}
                </h3>
                <p className="muted small" style={{ margin: "4px 0 0" }}>
                  {t("customer_people.subtitle")}
                </p>
              </div>
              {showSearch && (
                <input
                  type="search"
                  className="field-input"
                  data-testid="customer-people-search"
                  placeholder={t("customer_people.search_placeholder")}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  style={{ maxWidth: 240, height: 36 }}
                  aria-label={t("customer_people.search_placeholder")}
                />
              )}
            </div>

            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("customer_people.col_name")}</th>
                    <th>{t("customer_people.col_email")}</th>
                    <th>{t("customer_people.col_type")}</th>
                    <th>{t("customer_people.col_access")}</th>
                    <th aria-label={t("admin.col_actions")} />
                  </tr>
                </thead>
                <tbody>
                  {filteredPeople.map((person) => (
                    <tr
                      key={person.key}
                      data-testid="customer-person-row"
                      data-person-key={person.key}
                    >
                      <td className="td-subject">{person.name || "—"}</td>
                      <td>{person.email || "—"}</td>
                      <td data-testid="customer-person-type">
                        <span
                          style={{
                            display: "flex",
                            gap: 6,
                            flexWrap: "wrap",
                          }}
                        >
                          {person.isContact && (
                            <span
                              className="badge badge-normal"
                              data-testid="customer-person-badge-contact"
                            >
                              {t("customer_people.badge_contact")}
                            </span>
                          )}
                          {person.isEmployee && (
                            <span
                              className="badge badge-approved"
                              data-testid="customer-person-badge-employee"
                            >
                              {t("customer_people.badge_employee")}
                            </span>
                          )}
                          {person.isUser && (
                            <span
                              className="badge badge-waiting_customer_approval"
                              data-testid="customer-person-badge-user"
                            >
                              {t("customer_people.badge_user")}
                            </span>
                          )}
                        </span>
                      </td>
                      <td data-testid="customer-person-access">
                        {person.isCompanyAdmin ? (
                          <span
                            data-testid="customer-person-company-admin"
                            style={{ display: "inline-flex" }}
                          >
                            <AccessRoleBadge accessRole="CUSTOMER_COMPANY_ADMIN" />
                          </span>
                        ) : person.accessRole ? (
                          <AccessRoleBadge accessRole={person.accessRole} />
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        {person.isUser && person.userId !== null ? (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            data-testid="customer-person-manage"
                            onClick={() =>
                              setManaging({
                                userId: person.userId as number,
                                label: person.name || person.email,
                              })
                            }
                          >
                            {t("customer_people.manage_button")}
                          </button>
                        ) : numericId !== null ? (
                          <Link
                            to={`/admin/customers/${numericId}/contacts`}
                            className="btn btn-ghost btn-sm"
                            data-testid="customer-person-open-contact"
                          >
                            {t("customer_people.open_contact_button")}
                          </Link>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {filteredPeople.length === 0 && (
              <p
                className="muted small"
                style={{ padding: "12px 0" }}
                data-testid="customer-people-empty"
              >
                {search.trim()
                  ? t("customer_people.empty_filtered")
                  : t("customer_people.empty")}
              </p>
            )}
          </section>
        </>
      )}

      {managing && numericId !== null && (
        <CustomerUserManageModal
          key={managing.userId}
          customerId={numericId}
          userId={managing.userId}
          userLabel={managing.label}
          onClose={() => setManaging(null)}
          onChanged={refresh}
        />
      )}
    </div>
  );
}
