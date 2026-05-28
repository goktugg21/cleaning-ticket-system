import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { getCustomer, listCustomerContacts } from "../../api/admin";
import type { Contact, CustomerAdmin } from "../../api/types";

/**
 * Sprint 28 Batch 12 — Building Manager read-only customer contacts.
 *
 * Renders the contact list for a single customer the BM is allowed to
 * see. Scope is enforced server-side via the new
 * `IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer`
 * permission gate (Batch 12 extension on `views_contacts.py`): GET
 * passes for BM when the customer is in `scope_customers_for(BM)`;
 * POST / PATCH / DELETE remain 403.
 *
 * No Add / Edit / Delete affordances. Click a row to reveal a
 * read-only detail panel (in-page; no modal — the admin
 * `CustomerContactsPage` modal pattern is edit-bound and not
 * appropriate for the read-only BM experience).
 */
export function BuildingManagerCustomerContactsPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");
  const numericId = useMemo(() => {
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      // Sprint 28 Batch 12 — mirror `CustomerContactsPage.tsx` (Batch
      // 4) pattern: defer the synchronous setState into a microtask
      // to keep the effect body free of cascading-render lint hits.
      queueMicrotask(() => {
        if (!cancelled) setError(t("bm_customer_contacts.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    // Sprint 28 Batch 12 — existing baseline pattern; synchronous
    // loading=true before the async fetch resolves so the page
    // never flashes an empty state.
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    Promise.all([
      getCustomer(numericId),
      listCustomerContacts(numericId),
    ])
      .then(([customerData, contactList]) => {
        if (cancelled) return;
        setCustomer(customerData);
        setContacts(contactList);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, t]);

  const selectedContact = useMemo(
    () => contacts.find((c) => c.id === selectedId) ?? null,
    [contacts, selectedId],
  );

  return (
    <div className="admin-page" data-testid="bm-customer-contacts-page">
      <header className="admin-page-head">
        <div>
          {customer ? (
            <Link
              to={`/admin/customers/${customer.id}`}
              className="admin-back-link"
              data-testid="bm-customer-contacts-back"
            >
              <ChevronLeft size={14} strokeWidth={2.5} />
              {t("bm_customer_contacts.back", { name: customer.name })}
            </Link>
          ) : null}
          <h1 className="admin-page-title">
            {t("bm_customer_contacts.title")}
          </h1>
          <p
            className="admin-page-sub"
            data-testid="bm-customer-contacts-readonly-hint"
          >
            {t("bm_customer_contacts.readonly_hint")}
          </p>
        </div>
      </header>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && contacts.length === 0 ? (
        <p className="muted">{t("loading")}</p>
      ) : (
        <div className="card">
          {contacts.length === 0 ? (
            <p
              className="muted"
              data-testid="bm-customer-contacts-empty"
            >
              {t("bm_customer_contacts.empty")}
            </p>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>{t("customer_contacts.col_name")}</th>
                  <th>{t("customer_contacts.col_email")}</th>
                  <th>{t("customer_contacts.col_phone")}</th>
                  <th>{t("customer_contacts.col_role_label")}</th>
                </tr>
              </thead>
              <tbody data-testid="bm-customer-contacts-tbody">
                {contacts.map((contact) => (
                  <tr
                    key={contact.id}
                    data-testid={`bm-contact-row-${contact.id}`}
                    onClick={() => setSelectedId(contact.id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>{contact.full_name}</td>
                    <td>{contact.email || "—"}</td>
                    <td>{contact.phone || "—"}</td>
                    <td>{contact.role_label || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {selectedContact && (
            <div
              className="card"
              style={{ marginTop: 16 }}
              data-testid="bm-contact-detail-panel"
            >
              <div className="section-head">
                <div className="section-head-title">
                  {selectedContact.full_name}
                </div>
              </div>
              <dl className="readonly-grid">
                <dt>{t("customer_contacts.col_email")}</dt>
                <dd>{selectedContact.email || "—"}</dd>
                <dt>{t("customer_contacts.col_phone")}</dt>
                <dd>{selectedContact.phone || "—"}</dd>
                <dt>{t("customer_contacts.col_role_label")}</dt>
                <dd>{selectedContact.role_label || "—"}</dd>
                {selectedContact.notes && (
                  <>
                    <dt>{t("bm_customer_contacts.notes_label")}</dt>
                    <dd style={{ whiteSpace: "pre-wrap" }}>
                      {selectedContact.notes}
                    </dd>
                  </>
                )}
              </dl>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
