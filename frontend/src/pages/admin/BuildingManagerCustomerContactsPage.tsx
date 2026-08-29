import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { getCustomer, listCustomerContacts } from "../../api/admin";
import { CustomerSubPageHeader } from "./customer/CustomerSubPageHeader";
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
    <div data-testid="bm-customer-contacts-page">
      {/* Sprint 180 §1 — the shared header, same swap as the other two
          building-manager pages. The back link is conditional here (it
          needs the customer's name), which `PageHeader` supports by
          taking `backLink` as an optional prop. */}
      <CustomerSubPageHeader
        customerName={customer ? customer.name : ""}
        isActive={customer?.is_active ?? true}
        tab="people"
        subTab="contacts"
        facts={
          <span data-testid="bm-customer-contacts-readonly-hint">
            {t("bm_customer_contacts.readonly_hint")}
          </span>
        }
      />

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
            /* Sprint 180 §1 — `data-table` inside `table-wrap`, the house
               pair, replacing the undefined `admin-table`. */
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  {/* Sprint 179B §5 — these four headers rendered their
                      KEY on screen: `customer_contacts.col_*` was never
                      in any bundle. The `field_*` twins are in `common`,
                      carry the exact wording this page wants, and are
                      what the admin twin of this screen already uses as
                      headers — so this reads word for word like the page
                      it mirrors instead of adding four synonyms beside
                      four existing keys. */}
                  <tr>
                    <th>{t("customer_contacts.field_full_name")}</th>
                    <th>{t("customer_contacts.field_email")}</th>
                    <th>{t("customer_contacts.field_phone")}</th>
                    <th>{t("customer_contacts.field_role_label")}</th>
                  </tr>
                </thead>
                <tbody data-testid="bm-customer-contacts-tbody">
                  {contacts.map((contact) => (
                    <tr
                      key={contact.id}
                      data-testid={`bm-contact-row-${contact.id}`}
                      className="admin-row-clickable"
                      onClick={() => setSelectedId(contact.id)}
                    >
                      <td className="td-subject">{contact.full_name}</td>
                      <td>
                        {contact.email || (
                          <span className="muted-empty">—</span>
                        )}
                      </td>
                      <td>
                        {contact.phone || (
                          <span className="muted-empty">—</span>
                        )}
                      </td>
                      <td>
                        {contact.role_label || (
                          <span className="muted-empty">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
              {/* Sprint 180 §1 — the house read-only field rows, same
                  swap as the customer detail page: `readonly-grid` was
                  a `<dl>` with no rule behind it, so its labels and
                  values stacked as plain text. */}
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customer_contacts.field_email")}
                </div>
                <div
                  className={`detail-field-value${
                    selectedContact.email ? "" : " muted-empty"
                  }`}
                >
                  {selectedContact.email || "—"}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customer_contacts.field_phone")}
                </div>
                <div
                  className={`detail-field-value${
                    selectedContact.phone ? "" : " muted-empty"
                  }`}
                >
                  {selectedContact.phone || "—"}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customer_contacts.field_role_label")}
                </div>
                <div
                  className={`detail-field-value${
                    selectedContact.role_label ? "" : " muted-empty"
                  }`}
                >
                  {selectedContact.role_label || "—"}
                </div>
              </div>
              {selectedContact.notes && (
                <div className="detail-field-row">
                  <div className="detail-field-label">
                    {t("bm_customer_contacts.notes_label")}
                  </div>
                  <div
                    className="detail-field-value"
                    style={{ whiteSpace: "pre-wrap" }}
                  >
                    {selectedContact.notes}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
