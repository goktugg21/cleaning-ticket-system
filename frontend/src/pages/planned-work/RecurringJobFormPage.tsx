// Sprint 11/12 frontend — RecurringJob create + edit (shared form).
//
// Bespoke submit/load skeleton (mirrors the useEntityForm shape) rather
// than the hook itself, because the backend serializes create/update
// RESPONSES with the WRITE serializer: no `id`, crew lists write-only.
// So create cannot route to a detail page (navigates to the list) and
// edit re-GETs the full read object via the api helper.
//
// Option sources reuse the established conventions:
//   - buildings / customers : GET /buildings/ + /customers/ (CreateTicketPage)
//   - default staff / managers : GET /buildings/<id>/eligible-crew/
// The eligible-crew endpoint is building-scoped and reachable by an
// in-scope BUILDING_MANAGER, so the crew pickers work for every provider
// role (it replaced the earlier listUsers({role}) workaround that 403'd
// BMs). Crew is fetched per selected building; the backend still validates
// per-building eligibility on write.
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  extractAdminFieldErrors,
  getBuildingEligibleCrew,
  listAllBuildings,
  listAllCustomers,
  listCustomerPriceFolders,
  listServiceCategories,
} from "../../api/admin";
import type { AdminFieldErrors, CrewUser } from "../../api/admin";
import {
  createRecurringJob,
  getRecurringJob,
  updateRecurringJob,
} from "../../api/plannedWork";
import type {
  RecurringJobFrequency,
  RecurringJobWindowInput,
  RecurringJobWritePayload,
  SelectablePricingMode,
} from "../../api/plannedWork.types";
import { listContracts } from "../../api/contracts";
import { listLabels } from "../../api/customerLabels";
import type {
  Building,
  Customer,
  CustomerLabel,
  CustomerPriceFolder,
  ServiceCategory,
} from "../../api/types";
import { useToast } from "../../components/ToastProvider";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { customerLabelName } from "../../lib/customerLabelName";
// This page wears seven `pw-*` classes (`pw-form-group*`, `pw-window*`)
// and, until now, imported the stylesheet that defines them NOWHERE. It
// looked right only because Vite emits one CSS bundle for the app, so
// the detail page's import happened to cover this page too. That is a
// coincidence of the current chunking, not a dependency: the day this
// route gets its own CSS chunk, the form loses its group borders and
// its window rows. Declared explicitly. Vite dedupes the second import.
import "../../styles/planned-work.css";

const FREQUENCIES: RecurringJobFrequency[] = ["WEEKLY", "BIWEEKLY", "MONTHLY"];
// W-PW1 — a recurring job is billed as a MEMBERSHIP through its contract
// line, so the form no longer asks how a job or a window is priced. The
// write serializer still REQUIRES `pricing_mode`, so a newly created job
// takes this value and nothing in the UI can change it. On edit the three
// pricing keys are omitted from the PATCH entirely, which leaves whatever
// the job already stores exactly as it is.
const MEMBERSHIP_PRICING_MODE: SelectablePricingMode = "CONTRACT_INCLUDED";
const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const;
/** FE-5 — the contract-line select's explicit "none" (see
 *  `effectiveContractLineId`). */
const NO_CONTRACT_LINE = "none";

// Per-window pricing dropdown: "" means "inherit the job's pricing" (the
// occurrence falls back to the job default); the two explicit modes
// override it for that window only.

interface WindowDraft {
  // Present for a window that already exists on the job (edit in place so
  // its materialized occurrences keep their PROTECTing FK); absent = new.
  id?: number;
  label: string;
  startTime: string; // HH:MM
}

function emptyWindow(): WindowDraft {
  return { label: "", startTime: "" };
}

function customerMatchesBuilding(customer: Customer, buildingId: number): boolean {
  return (
    customer.building === buildingId ||
    (customer.linked_building_ids?.includes(buildingId) ?? false)
  );
}

// Sprint 187 §6b — one stable empty array, so the derived
// `offeredCategories` below does not hand a new reference to its
// consumers on every render.
const EMPTY_CATEGORIES: ServiceCategory[] = [];

// W24 — the contract-line link, declared LOCALLY rather than on
// `api/plannedWork.types.ts`.
//
// The backend already carries the field on both sides of the wire
// (`RecurringJobSerializer.contract_line` + `contract_line_name` for
// the read, `RecurringJobWriteSerializer.contract_line` for the write,
// both landed in 18433e5). The canonical home for these two lines is
// `RecurringJob` / `RecurringJobWritePayload` in
// `api/plannedWork.types.ts` — that file belongs to another wave this
// round, so the shape is narrowed here instead of being widened there.
// NOT a permanent arrangement: fold both into plannedWork.types.ts and
// delete these two aliases when that file is free.
type ContractLineLinkRead = { contract_line: number | null };
type ContractLineLinkWrite = { contract_line?: number | null };

/** One offerable line: the line itself plus the contract it sits on,
 *  because a line name ("Dagelijkse schoonmaak") repeats across a
 *  customer's contracts and only the contract number separates them. */
interface ContractLineOption {
  id: number;
  lineName: string;
  contractNo: string;
}

/** The customer's offerable contract lines, tagged with the customer
 *  they were fetched FOR. Same shape (and same reason) as
 *  `customerFolders` below: an empty list that arrived is not the same
 *  fact as a list that has not arrived, and the save path must be able
 *  to tell them apart. */
interface ContractLineLists {
  customerId: number;
  rows: ContractLineOption[];
}

export function RecurringJobFormPage() {
  const { id } = useParams();
  const isCreate = id === undefined;
  const navigate = useNavigate();
  const { push } = useToast();
  const { t } = useTranslation(["planned_work", "common"]);

  // Option lists.
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  // Eligible crew for the SELECTED building (building-scoped endpoint).
  const [eligibleStaff, setEligibleStaff] = useState<CrewUser[]>([]);
  const [eligibleManagers, setEligibleManagers] = useState<CrewUser[]>([]);
  const [crewLoading, setCrewLoading] = useState(false);
  const [crewError, setCrewError] = useState(false);
  // True once a successful eligible-crew fetch has resolved for the
  // current building. Gates whether the crew lists are sent on submit:
  // if the fetch failed (or no building yet) we OMIT the crew keys so an
  // edit never wipes a job's existing crew on a transient error.
  const [crewLoaded, setCrewLoaded] = useState(false);

  // Form fields.
  const [building, setBuilding] = useState<number | "">("");
  const [customer, setCustomer] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [frequency, setFrequency] = useState<RecurringJobFrequency>("WEEKLY");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  // Recurring day-model: a weekday SET (WEEKLY/BIWEEKLY) + 1..N windows.
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [windows, setWindows] = useState<WindowDraft[]>([emptyWindow()]);
  /** FE-5 — the visits editor opens on request. The default single
   *  visit with no time needs no attention, so it reads as one fact. */
  const [windowsOpen, setWindowsOpen] = useState(false);
  const [defaultStaffIds, setDefaultStaffIds] = useState<number[]>([]);
  const [defaultManagerIds, setDefaultManagerIds] = useState<number[]>([]);

  // ---- Sprint 144 §2 — Department / Work type / Category ---------------
  // All three optional, all three bound to the SELECTED CUSTOMER (the
  // owner asked for the customer's own vocabulary, not a generic global
  // list). Selections are stored raw and DERIVED to "" when they do not
  // belong to the current customer — never resynced in an effect, which
  // is the pattern that produced the customer-lock regression Sprint 143
  // §1 had to undo (and which CLAUDE.md bans).
  const [departmentId, setDepartmentId] = useState("");
  const [workTypeId, setWorkTypeId] = useState("");
  // Prefixed, same shape as CreateExtraWorkPage: "" | "cat:<id>" | "fol:<id>".
  const [categoryChoice, setCategoryChoice] = useState("");
  // Tagged with the customer id so a list fetched for a previously
  // selected customer is never offered against the current one.
  const [labelLists, setLabelLists] = useState<{
    customerId: number;
    departments: CustomerLabel[];
    workTypes: CustomerLabel[];
  } | null>(null);
  // Sprint 187C — carries the company it was fetched FOR, mirroring
  // `customerFolders` below. Without that, an empty list cannot be told
  // apart from a list that has not arrived yet, and the save path treats
  // the two identically. See `categoriesLoaded` further down.
  const [companyCategories, setCompanyCategories] = useState<{
    companyId: number;
    rows: ServiceCategory[];
  } | null>(null);
  const [customerFolders, setCustomerFolders] = useState<{
    customerId: number;
    rows: CustomerPriceFolder[];
  } | null>(null);
  // W24 — the customer's contract lines, same customer-tagged shape.
  const [contractLines, setContractLines] =
    useState<ContractLineLists | null>(null);
  const [contractLineId, setContractLineId] = useState("");

  // Fallback labels so a building/customer outside the fetched page still
  // renders a sensible option in edit mode.
  const [loadedJobTitle, setLoadedJobTitle] = useState("");
  const [fallbackBuilding, setFallbackBuilding] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [fallbackCustomer, setFallbackCustomer] = useState<{
    id: number;
    name: string;
  } | null>(null);
  // W24 — the job's STORED contract line, kept even when the fetched
  // options do not contain it. A line that has since been superseded by
  // a newer contract revision is not on the active revision any more,
  // so it is not in the option list — and without this the select would
  // render blank and read as "no link", which is a lie about what is
  // stored. Same job as `fallbackBuilding` / `fallbackCustomer` above.
  // Tagged with the customer it belongs to, so switching the job's
  // customer drops it: a line is a line of ONE customer's contract, and
  // offering the old one against the new customer would be a
  // cross-customer option (the backend rejects it as
  // `contract_line_customer_mismatch` — the picker must not offer it in
  // the first place).
  const [fallbackContractLine, setFallbackContractLine] = useState<{
    id: number;
    name: string;
    customerId: number;
  } | null>(null);

  const [loading, setLoading] = useState(!isCreate);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<AdminFieldErrors>({});

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [buildingsResp, customersResp] = await Promise.all([
          listAllBuildings(),
          listAllCustomers(),
        ]);
        if (cancelled) return;
        setBuildings(buildingsResp);
        setCustomers(customersResp);

        // Eligible crew is loaded per-building by the [building] effect
        // below; in edit mode that effect fires once `building` is set
        // from the loaded job here.
        if (!isCreate && id !== undefined) {
          const job = await getRecurringJob(id);
          if (cancelled) return;
          // Apply the loaded job to form state. Inlined (rather than a
          // helper) so it sits after the await — keeping it out of the
          // effect's synchronous body and free of forward-reference lint.
          setLoadedJobTitle(job.title);
          setBuilding(job.building);
          setCustomer(job.customer);
          // Sprint 144 §2 — hydrate the three classifiers on EDIT.
          setDepartmentId(job.department ? String(job.department) : "");
          setWorkTypeId(job.work_type ? String(job.work_type) : "");
          setCategoryChoice(
            job.service_category
              ? `cat:${job.service_category}`
              : job.price_folder
                ? `fol:${job.price_folder}`
                : "",
          );
          setTitle(job.title);
          setDescription(job.description);
          setFrequency(job.frequency);
          setStartDate(job.start_date);
          setEndDate(job.end_date ?? "");
          setWeekdays(job.weekdays ?? []);
          setWindows(
            job.windows.length > 0
              ? job.windows.map((w) => ({
                  id: w.id,
                  label: w.label,
                  startTime: w.start_time?.slice(0, 5) ?? "",
                }))
              : [emptyWindow()],
          );
          setDefaultStaffIds(job.default_staff_ids);
          setDefaultManagerIds(job.default_manager_ids);
          setFallbackBuilding({ id: job.building, name: job.building_name });
          setFallbackCustomer({ id: job.customer, name: job.customer_name });
          // W24 — hydrate the contract-line link. The read cast is the
          // local-type arrangement documented at `ContractLineLinkRead`.
          const storedLine = (job as unknown as ContractLineLinkRead)
            .contract_line;
          setContractLineId(storedLine ? String(storedLine) : "");
          const storedLineName = (
            job as unknown as { contract_line_name: string | null }
          ).contract_line_name;
          setFallbackContractLine(
            storedLine
              ? {
                  id: storedLine,
                  name: storedLineName ?? String(storedLine),
                  customerId: job.customer,
                }
              : null,
          );
        }
      } catch (err) {
        if (!cancelled) setGeneralError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id, isCreate]);

  // Load the building-scoped eligible crew whenever the selected building
  // changes. Fires on a manual building pick AND on the initial edit load
  // (once the job's building is applied above). With no building selected
  // the lists clear and the pickers show a "select a building" placeholder.
  useEffect(() => {
    let cancelled = false;
    async function loadCrew() {
      if (building === "") {
        setEligibleStaff([]);
        setEligibleManagers([]);
        setCrewLoaded(false);
        setCrewError(false);
        setCrewLoading(false);
        return;
      }
      setCrewLoading(true);
      setCrewError(false);
      try {
        const crew = await getBuildingEligibleCrew(Number(building));
        if (cancelled) return;
        setEligibleStaff(crew.staff);
        setEligibleManagers(crew.managers);
        setCrewLoaded(true);
      } catch {
        if (cancelled) return;
        setEligibleStaff([]);
        setEligibleManagers([]);
        setCrewLoaded(false);
        setCrewError(true);
      } finally {
        if (!cancelled) setCrewLoading(false);
      }
    }
    loadCrew();
    return () => {
      cancelled = true;
    };
  }, [building]);

  const filteredCustomers = useMemo(() => {
    if (building === "") return customers;
    return customers.filter((c) => customerMatchesBuilding(c, Number(building)));
  }, [customers, building]);

  // Sprint 144 §2 — the customer's own label lists. Reuses the SAME
  // `listLabels` helper the Extra Work form uses; no second path.
  // Load-only (no setState in the effect body): a stale selection is
  // neutralised by the `effective*` derivations below.
  useEffect(() => {
    if (customer === "") return;
    const customerId = Number(customer);
    let cancelled = false;
    Promise.all([
      listLabels(customerId, "department", { is_active: true }).catch(
        () => [] as CustomerLabel[],
      ),
      listLabels(customerId, "work_type", { is_active: true }).catch(
        () => [] as CustomerLabel[],
      ),
    ]).then(([departments, workTypes]) => {
      if (!cancelled) {
        setLabelLists({ customerId, departments, workTypes });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [customer]);

  // The company's ACTIVE catalog categories. An archived category must
  // never be offerable.
  //
  // Sprint 187 §6b — and neither must ANOTHER provider's. Fetched once
  // with no company, this offered a SUPER_ADMIN every company's category
  // headings under "the company's categories", none of which can hold a
  // service this customer is priceable from. Re-fetched per customer
  // now, like the folders effect directly below it, because the company
  // is a property of the chosen customer and not of the page.
  const selectedCustomerCompany =
    customer === ""
      ? null
      : (customers.find((c) => c.id === Number(customer))?.company ?? null);
  // DERIVED, not stored: with no customer chosen there is no company, so
  // there are no company categories to offer. Clearing the state inside
  // the effect below would be a synchronous setState in an effect body,
  // which CLAUDE.md forbids and the lint baseline is already at.
  const categoriesLoaded =
    selectedCustomerCompany !== null &&
    companyCategories !== null &&
    companyCategories.companyId === selectedCustomerCompany;
  const offeredCategories = categoriesLoaded
    ? companyCategories.rows
    : EMPTY_CATEGORIES;
  useEffect(() => {
    if (selectedCustomerCompany === null) return;
    const companyId = selectedCustomerCompany;
    let cancelled = false;
    listServiceCategories({
      is_active: true,
      company: companyId,
    })
      .then((rows) => {
        if (!cancelled) setCompanyCategories({ companyId, rows });
      })
      .catch(() => {
        // Sprint 187C — a failed fetch stays UNLOADED rather than
        // becoming an empty loaded list. An empty loaded list would tell
        // the save path "this company genuinely has no categories", and
        // the job's stored one would be written away on the next save.
        if (!cancelled) setCompanyCategories(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedCustomerCompany]);

  // ...and the selected customer's ACTIVE folders.
  useEffect(() => {
    if (customer === "") return;
    const customerId = Number(customer);
    let cancelled = false;
    listCustomerPriceFolders(customerId, { is_active: true })
      .then((rows) => {
        if (!cancelled) setCustomerFolders({ customerId, rows });
      })
      .catch(() => {
        if (!cancelled) setCustomerFolders({ customerId, rows: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [customer]);

  // W24 — ...and the customer's contract lines, for the optional
  // "Contract line" picker.
  //
  // NO new endpoint. `GET /api/contracts/?customer=<id>` already
  // carries what the picker needs: the contract number on the header
  // and the ACTIVE revision's lines in `projects`. Its reader tier
  // (`IsContractReader` — SA / CA / BM) is exactly the tier that can
  // reach this form (`planned_work.permissions.IsProviderManager`), and
  // it already excludes `kind=EXTRA_WORK`, so a register's projected
  // lines can never be offered as something to plan.
  //
  // Paged EXHAUSTIVELY client-side (the Sprint 120 pattern) rather than
  // by loosening the list's `pagination_class` — Sprint 134/135's
  // lesson, that a shared list's pagination is a contract with the
  // callers that DO have prev/next UI, and this picker has none.
  useEffect(() => {
    if (customer === "") return;
    const customerId = Number(customer);
    let cancelled = false;
    async function loadLines(): Promise<ContractLineOption[]> {
      const rows: ContractLineOption[] = [];
      let page = 1;
      for (let i = 0; i < 100; i++) {
        const response = await listContracts({
          customer: customerId,
          page,
          page_size: 200,
        });
        for (const contract of response.results) {
          for (const line of contract.projects) {
            rows.push({
              id: line.id,
              lineName: line.name,
              contractNo: contract.contract_no,
            });
          }
        }
        if (!response.next) break;
        page += 1;
      }
      return rows;
    }
    loadLines()
      .then((rows) => {
        if (!cancelled) setContractLines({ customerId, rows });
      })
      .catch(() => {
        // Stays UNLOADED on failure, never an empty loaded list — the
        // Sprint 187C rule. An empty loaded list would tell the save
        // path "this customer genuinely has no contract lines", and a
        // job's stored link would be written away on the next save.
        if (!cancelled) setContractLines(null);
      });
    return () => {
      cancelled = true;
    };
  }, [customer]);

  // Guarded inline so TS narrows AND a list fetched for a previous
  // customer is never shown against the current one.
  const currentDepartments =
    labelLists && labelLists.customerId === Number(customer)
      ? labelLists.departments
      : [];
  const currentWorkTypes =
    labelLists && labelLists.customerId === Number(customer)
      ? labelLists.workTypes
      : [];
  const currentFolders =
    customerFolders && customerFolders.customerId === Number(customer)
      ? customerFolders.rows
      : [];
  // W24 — the same guard for the contract lines, plus the stored line
  // appended when the active revision no longer carries it (see
  // `fallbackContractLine`). Appended, not substituted: the operator
  // can still pick a live line, and the stored one stays visible until
  // they do.
  const fetchedContractLines =
    contractLines && contractLines.customerId === Number(customer)
      ? contractLines.rows
      : [];
  const currentContractLines: ContractLineOption[] =
    fallbackContractLine !== null &&
    fallbackContractLine.customerId === Number(customer) &&
    !fetchedContractLines.some((line) => line.id === fallbackContractLine.id)
      ? [
          ...fetchedContractLines,
          {
            id: fallbackContractLine.id,
            lineName: fallbackContractLine.name,
            contractNo: "",
          },
        ]
      : fetchedContractLines;

  // DERIVED, not resynced: an id that does not belong to the current
  // customer's list collapses to "" for both the dropdown value and the
  // payload, so switching customer cannot carry a selection across.
  const effectiveDepartmentId = currentDepartments.some(
    (d) => String(d.id) === departmentId,
  )
    ? departmentId
    : "";
  const effectiveWorkTypeId = currentWorkTypes.some(
    (w) => String(w.id) === workTypeId,
  )
    ? workTypeId
    : "";
  const effectiveCategoryChoice = categoryChoice.startsWith("fol:")
    ? currentFolders.some((f) => `fol:${f.id}` === categoryChoice)
      ? categoryChoice
      : ""
    : categoryChoice.startsWith("cat:")
      ? offeredCategories.some((c) => `cat:${c.id}` === categoryChoice)
        ? categoryChoice
        : ""
      : "";

  // Sprint 187C — the collapse above cannot tell "this id does not belong
  // to the chosen customer" (deliberate: a selection must not carry
  // across customers) from "the list it checks against has not arrived
  // yet". Sending an explicit null in the second case WIPES the job's
  // stored category on save, and §6b widened the window that makes it
  // reachable: the category fetch now waits for the customer to resolve
  // out of the sequential load chain, while `loading` has already gone
  // false and Save is clickable.
  //
  // So the keys are OMITTED until the lists they validate against are
  // loaded for the current selection — an omitted key leaves the stored
  // value untouched. This is the same rule the crew payload below states
  // for the same reason. On CREATE there is nothing to protect and both
  // lists resolve before anything is stored, so the keys are always sent.
  const foldersLoaded =
    customerFolders !== null && customerFolders.customerId === Number(customer);
  const categoryChoiceIsTrustworthy =
    id === undefined || (categoriesLoaded && foldersLoaded);
  const categoryPayload = categoryChoiceIsTrustworthy
    ? {
        service_category: effectiveCategoryChoice.startsWith("cat:")
          ? Number(effectiveCategoryChoice.slice(4))
          : null,
        price_folder: effectiveCategoryChoice.startsWith("fol:")
          ? Number(effectiveCategoryChoice.slice(4))
          : null,
      }
    : {};

  // W24 — the contract line gets the same three-part discipline the
  // classifiers above already have: DERIVED (never resynced), collapsed
  // to "" when the id does not belong to the current customer's lines,
  // and OMITTED from the payload until the list it is checked against
  // has actually loaded for this customer.
  // FE-5 — "default from contract": on CREATE, a customer with exactly
  // one contract line gets it filled in until the operator says
  // otherwise. `NO_CONTRACT_LINE` is the explicit "none"; "" is
  // "untouched", which is what lets the default apply.
  const effectiveContractLineId =
    contractLineId === NO_CONTRACT_LINE
      ? ""
      : currentContractLines.some((line) => String(line.id) === contractLineId)
        ? contractLineId
        : isCreate && contractLineId === "" && currentContractLines.length === 1
          ? String(currentContractLines[0].id)
          : "";
  const contractLinesLoaded =
    contractLines !== null && contractLines.customerId === Number(customer);
  const contractLinePayload: ContractLineLinkWrite =
    id === undefined || contractLinesLoaded
      ? {
          contract_line: effectiveContractLineId
            ? Number(effectiveContractLineId)
            : null,
        }
      : {};

  function toggleId(list: number[], value: number): number[] {
    return list.includes(value)
      ? list.filter((x) => x !== value)
      : [...list, value];
  }

  function handleBuildingChange(value: string) {
    const next = value === "" ? "" : Number(value);
    setBuilding(next);
    // Eligibility is per-building; drop a customer that no longer matches
    // and reset crew so stale picks can't ride along.
    if (next !== "" && customer !== "") {
      const stillValid = customers.some(
        (c) => c.id === customer && customerMatchesBuilding(c, Number(next)),
      );
      if (!stillValid) setCustomer("");
    }
    setDefaultStaffIds([]);
    setDefaultManagerIds([]);
  }

  const showWeekdays = frequency === "WEEKLY" || frequency === "BIWEEKLY";

  function validate(): boolean {
    const errs: AdminFieldErrors = {};
    if (building === "") errs.building = t("form.error_building_required");
    if (customer === "") errs.customer = t("form.error_customer_required");
    if (!title.trim()) errs.title = t("form.error_title_required");
    if (!startDate) errs.start_date = t("form.error_start_date_required");
    if (showWeekdays && weekdays.length === 0) {
      errs.weekdays = t("form.error_weekdays_required");
    }
    if (windows.length === 0) {
      errs.windows = t("form.error_windows_required");
    }
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function toggleWeekday(day: number) {
    setWeekdays((prev) =>
      prev.includes(day)
        ? prev.filter((d) => d !== day)
        : [...prev, day].sort((a, b) => a - b),
    );
  }

  function updateWindow(index: number, patch: Partial<WindowDraft>) {
    setWindows((prev) =>
      prev.map((w, i) => (i === index ? { ...w, ...patch } : w)),
    );
  }

  function addWindow() {
    setWindows((prev) => [...prev, emptyWindow()]);
  }

  function removeWindow(index: number) {
    setWindows((prev) =>
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== index),
    );
  }

  function buildPayload(): Partial<RecurringJobWritePayload> &
    ContractLineLinkWrite {
    const windowsPayload: RecurringJobWindowInput[] = windows.map((w, idx) => {
      const input: RecurringJobWindowInput = {
        label: w.label.trim(),
        start_time: w.startTime || null,
        ordering: idx,
      };
      if (w.id != null) input.id = w.id;
      // W-PW1 — no per-window pricing key is sent at all. An existing
      // window keeps whatever it stores; a new one inherits the job.
      return input;
    });

    // W24 — the write shape is the generated payload PLUS the
    // contract-line key, intersected locally (see `ContractLineLinkWrite`).
    // `createRecurringJob` / `updateRecurringJob` take the base type, and
    // a variable of an intersection type is assignable to it, so nothing
    // in the API layer has to change to carry the key.
    const payload: Partial<RecurringJobWritePayload> &
      ContractLineLinkWrite = {
      building: Number(building),
      customer: Number(customer),
      title: title.trim(),
      description: description.trim(),
      frequency,
      start_date: startDate,
      end_date: endDate || null,
      // Day-model: only send weekdays for WEEKLY/BIWEEKLY (MONTHLY ignores
      // it). Windows supersede the legacy single time-window inputs.
      weekdays: showWeekdays ? weekdays : [],
      windows: windowsPayload,
      // W-PW1 — CREATE must carry one (the write serializer requires it);
      // EDIT omits all three so a PATCH never rewrites what is stored.
      ...(isCreate
        ? { pricing_mode: MEMBERSHIP_PRICING_MODE }
        : {}),
      // Sprint 144 §2 — all optional. `effective*` has already collapsed
      // any selection that belongs to a different customer, so a stale
      // one can never reach the wire. Explicit `null` (not omitted) so
      // clearing a field on EDIT actually clears it.
      department: effectiveDepartmentId ? Number(effectiveDepartmentId) : null,
      work_type: effectiveWorkTypeId ? Number(effectiveWorkTypeId) : null,
      ...categoryPayload,
      ...contractLinePayload,
    };
    // Only touch crew when eligible crew loaded for this building, so a
    // transient fetch error on edit does not wipe the job's existing crew
    // (omitted key = untouched). Send only ids still in the eligible lists:
    // a pre-selected default that lost eligibility is dropped rather than
    // re-sent (the backend would reject re-adding it).
    if (crewLoaded) {
      const staffIds = new Set(eligibleStaff.map((u) => u.id));
      const managerIds = new Set(eligibleManagers.map((u) => u.id));
      payload.default_staff_ids = defaultStaffIds.filter((uid) =>
        staffIds.has(uid),
      );
      payload.default_manager_ids = defaultManagerIds.filter((uid) =>
        managerIds.has(uid),
      );
    }
    return payload;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneralError("");
    if (!validate()) return;
    setSubmitting(true);
    try {
      const payload = buildPayload();
      if (isCreate) {
        // On CREATE every required key is present by construction (the
        // fields validate() guards, plus `pricing_mode` from the branch in
        // buildPayload); the cast is what tells TypeScript that the
        // create-only branch has been taken.
        await createRecurringJob(payload as RecurringJobWritePayload);
        push({
          variant: "success",
          title: t("form.created_toast_title"),
          description: t("form.created_toast_desc"),
        });
        navigate("/planned-work");
        return;
      }
      if (id === undefined) return;
      await updateRecurringJob(id, payload);
      push({
        variant: "success",
        title: t("form.saved_toast_title"),
        description: t("form.saved_toast_desc"),
      });
      navigate(`/planned-work/${id}`);
    } catch (err) {
      const fields = extractAdminFieldErrors(err);
      if (Object.keys(fields).length > 0) {
        setFieldErrors(fields);
        if (fields.detail) setGeneralError(fields.detail);
      } else {
        setGeneralError(getApiError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const backHref =
    isCreate || id === undefined ? "/planned-work" : `/planned-work/${id}`;
  const backLabel = isCreate
    ? t("form.back_to_list")
    : t("form.back_to_detail");

  const buildingOptions: { id: number; name: string }[] = useMemo(() => {
    const opts = buildings.map((b) => ({ id: b.id, name: b.name }));
    if (fallbackBuilding && !opts.some((o) => o.id === fallbackBuilding.id)) {
      opts.unshift(fallbackBuilding);
    }
    return opts;
  }, [buildings, fallbackBuilding]);

  const customerOptions: { id: number; name: string }[] = useMemo(() => {
    const opts = filteredCustomers.map((c) => ({ id: c.id, name: c.name }));
    if (
      fallbackCustomer &&
      customer === fallbackCustomer.id &&
      !opts.some((o) => o.id === fallbackCustomer.id)
    ) {
      opts.unshift(fallbackCustomer);
    }
    return opts;
  }, [filteredCustomers, fallbackCustomer, customer]);

  const detailsSummary = [
    effectiveDepartmentId &&
      customerLabelName(
        currentDepartments.find((d) => String(d.id) === effectiveDepartmentId)
          ?.name ?? "",
        t,
      ),
    effectiveWorkTypeId &&
      customerLabelName(
        currentWorkTypes.find((w) => String(w.id) === effectiveWorkTypeId)
          ?.name ?? "",
        t,
      ),
    effectiveCategoryChoice.startsWith("fol:")
      ? currentFolders.find((f) => `fol:${f.id}` === effectiveCategoryChoice)
          ?.name
      : effectiveCategoryChoice.startsWith("cat:")
        ? offeredCategories.find(
            (c) => `cat:${c.id}` === effectiveCategoryChoice,
          )?.name
        : "",
    description.trim() && t("form.fold_details_has_notes"),
  ].filter(Boolean) as string[];

  /* The visits editor shows when somebody asked for it, or when there is
     something in it a reader must see: a second visit, a label, a time. */
  const windowsEditorVisible =
    windowsOpen ||
    windows.length > 1 ||
    windows.some((w) => w.label.trim() || w.startTime);

  const crewCount = defaultStaffIds.length + defaultManagerIds.length;

  return (
    <div data-testid="recurring-job-form-page">
      <Link to={backHref} className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {backLabel}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("list.page_title")}
          </div>
          <h2 className="page-title">
            {isCreate
              ? t("form.create_title")
              : t("form.edit_title", { title: loadedJobTitle })}
          </h2>
          <p className="page-sub">{t("form.page_sub")}</p>
        </div>
      </div>

      {generalError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {generalError}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <form className="card" onSubmit={handleSubmit}>
          {/* ----- Wat ----- */}
          <div className="form-section" data-testid="rj-section-what">
            <div className="form-section-title">{t("form.s_what")}</div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="rj-customer">
                  {t("form.field_customer")}
                </label>
                <select
                  id="rj-customer"
                  className="field-select"
                  value={customer === "" ? "" : String(customer)}
                  onChange={(event) =>
                    setCustomer(
                      event.target.value === ""
                        ? ""
                        : Number(event.target.value),
                    )
                  }
                  disabled={customerOptions.length === 0}
                  required
                >
                  <option value="" disabled>
                    {customerOptions.length === 0
                      ? t("form.field_customer_no_options")
                      : t("form.field_customer_placeholder")}
                  </option>
                  {customerOptions.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                {fieldErrors.customer && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.customer}
                  </div>
                )}
              </div>

              <div className="field">
                <label className="field-label" htmlFor="rj-building">
                  {t("form.field_building")}
                </label>
                <select
                  id="rj-building"
                  className="field-select"
                  value={building === "" ? "" : String(building)}
                  onChange={(event) => handleBuildingChange(event.target.value)}
                  required
                >
                  <option value="" disabled>
                    {t("form.field_building_placeholder")}
                  </option>
                  {buildingOptions.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
                {fieldErrors.building && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.building}
                  </div>
                )}
              </div>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="rj-title">
                {t("form.field_title")}
              </label>
              <input
                id="rj-title"
                className="field-input"
                type="text"
                maxLength={255}
                placeholder={t("form.field_title_placeholder")}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                required
              />
              {fieldErrors.title && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.title}
                </div>
              )}
            </div>

            {/* Notes and the customer's own labels fold: optional, and
                the summary line carries what is set so an editor sees it
                without opening. */}
            <details className="form-fold" data-testid="rj-group-labels">
              <summary className="form-fold-summary">
                {t("form.fold_details")}
                <span className="form-fold-summary-value">
                  {detailsSummary.length > 0
                    ? detailsSummary.join(" · ")
                    : t("form.fold_details_empty")}
                </span>
              </summary>
              <div className="form-fold-body">
                <div className="field">
                  <label className="field-label" htmlFor="rj-description">
                    {t("form.field_description")}
                  </label>
                  <textarea
                    id="rj-description"
                    className="field-textarea"
                    placeholder={t("form.field_description_placeholder")}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </div>
                <div className="form-2col">
                  <div className="field">
                    <label className="field-label" htmlFor="rj-department">
                      {t("form.field_department")}
                    </label>
                    <select
                      id="rj-department"
                      className="field-select"
                      data-testid="recurring-job-department"
                      value={effectiveDepartmentId}
                      onChange={(event) => setDepartmentId(event.target.value)}
                      disabled={customer === "" || currentDepartments.length === 0}
                    >
                      <option value="">{t("form.field_label_none")}</option>
                      {currentDepartments.map((d) => (
                        <option key={d.id} value={String(d.id)}>
                          {customerLabelName(d.name, t)}
                        </option>
                      ))}
                    </select>
                    {customer !== "" && currentDepartments.length === 0 && (
                      <div className="muted small" style={{ marginTop: 4 }}>
                        {t("form.field_department_none")}
                      </div>
                    )}
                  </div>

                  <div className="field">
                    <label className="field-label" htmlFor="rj-work-type">
                      {t("form.field_work_type")}
                    </label>
                    <select
                      id="rj-work-type"
                      className="field-select"
                      data-testid="recurring-job-work-type"
                      value={effectiveWorkTypeId}
                      onChange={(event) => setWorkTypeId(event.target.value)}
                      disabled={customer === "" || currentWorkTypes.length === 0}
                    >
                      <option value="">{t("form.field_label_none")}</option>
                      {currentWorkTypes.map((w) => (
                        <option key={w.id} value={String(w.id)}>
                          {customerLabelName(w.name, t)}
                        </option>
                      ))}
                    </select>
                    {customer !== "" && currentWorkTypes.length === 0 && (
                      <div className="muted small" style={{ marginTop: 4 }}>
                        {t("form.field_work_type_none")}
                      </div>
                    )}
                  </div>

                  <div className="field">
                    <label className="field-label" htmlFor="rj-category">
                      {t("form.field_category")}
                    </label>
                    <select
                      id="rj-category"
                      className="field-select"
                      data-testid="recurring-job-category"
                      value={effectiveCategoryChoice}
                      onChange={(event) => setCategoryChoice(event.target.value)}
                    >
                      <option value="">{t("form.field_label_none")}</option>
                      {offeredCategories.length > 0 && (
                        <optgroup label={t("form.field_category_group_company")}>
                          {offeredCategories.map((c) => (
                            <option key={`cat-${c.id}`} value={`cat:${c.id}`}>
                              {c.name}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      {currentFolders.length > 0 && (
                        <optgroup label={t("form.field_category_group_folders")}>
                          {currentFolders.map((f) => (
                            <option key={`fol-${f.id}`} value={`fol:${f.id}`}>
                              {f.name}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  </div>
                </div>
              </div>
            </details>
          </div>

          {/* ----- Wanneer ----- */}
          <div className="form-section" data-testid="rj-section-when">
            <div className="form-section-title">{t("form.s_when")}</div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="rj-frequency">
                  {t("form.field_frequency")}
                </label>
                <select
                  id="rj-frequency"
                  className="field-select"
                  value={frequency}
                  onChange={(event) =>
                    setFrequency(event.target.value as RecurringJobFrequency)
                  }
                >
                  {FREQUENCIES.map((f) => (
                    <option key={f} value={f}>
                      {t(`frequency.${f}`)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="rj-start">
                  {t("form.field_start_date")}
                </label>
                <input
                  id="rj-start"
                  className="field-input"
                  type="date"
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                  required
                />
                {frequency === "MONTHLY" && (
                  <span className="muted small">{t("form.monthly_hint")}</span>
                )}
                {fieldErrors.start_date && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.start_date}
                  </div>
                )}
              </div>
            </div>

            {/* Weekday set — WEEKLY / BIWEEKLY only. MONTHLY anchors on the
                start-date's day-of-month, so the picker is hidden. */}
            {showWeekdays && (
              <div className="field">
                <span className="field-label">{t("form.field_weekdays")}</span>
                <div
                  className="weekday-picker"
                  style={{ display: "flex", flexWrap: "wrap", gap: 8 }}
                  data-testid="rj-weekday-picker"
                >
                  {WEEKDAYS.map((day) => (
                    <button
                      key={day}
                      type="button"
                      className={
                        weekdays.includes(day)
                          ? "btn btn-primary btn-sm"
                          : "btn btn-secondary btn-sm"
                      }
                      aria-pressed={weekdays.includes(day)}
                      onClick={() => toggleWeekday(day)}
                    >
                      {t(`weekday_short.${day}`)}
                    </button>
                  ))}
                </div>
                {frequency === "BIWEEKLY" && (
                  <span className="muted small">
                    {t("form.field_weekdays_hint_biweekly")}
                  </span>
                )}
                {fieldErrors.weekdays && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.weekdays}
                  </div>
                )}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="rj-end">
                {t("form.field_end_date")}
              </label>
              <input
                id="rj-end"
                className="field-input"
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
              <span className="muted small">{t("form.field_end_date_hint")}</span>
              {fieldErrors.end_date && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.end_date}
                </div>
              )}
            </div>
          </div>

          {/* ----- Bezoeken per dag -----
              One visit per time per chosen day; each visit becomes a
              ticket on its day. Said once, in one sentence. The default
              single visit with no time is a fact, not a decision; the
              editor opens when somebody wants a time or a second visit.
              NOTE — no per-window pricing exists to fold: W-PW1 removed
              it (a recurring job is billed through its contract line). */}
          <div className="form-section" data-testid="rj-group-windows">
            <div className="form-section-title">{t("form.s_visits")}</div>
            <p className="muted small" style={{ marginTop: 0 }}>
              {t("form.visits_sentence")}
            </p>
            {!windowsEditorVisible ? (
              <div className="ew-facts" style={{ marginTop: 4 }}>
                <button
                  type="button"
                  className="ew-fact"
                  onClick={() => setWindowsOpen(true)}
                  aria-expanded={false}
                  data-testid="rj-windows-open"
                >
                  <span>
                    {t("form.visits_fact", { count: windows.length })}
                    {" · "}
                    {t("form.visits_no_time")}
                  </span>
                  <span className="ew-fact-pencil">
                    <Pencil size={13} strokeWidth={2} aria-hidden />
                  </span>
                </button>
              </div>
            ) : (
              <div className="field">
                <div className="pw-windows-editor" data-testid="rj-windows-editor">
                  {windows.map((win, idx) => (
                    <div
                      key={idx}
                      className="pw-window-row"
                      data-testid="rj-window-row"
                    >
                      <div className="form-2col">
                        <div className="field pw-window-field">
                          <label className="field-label">
                            {t("form.window_label")}
                          </label>
                          <input
                            className="field-input"
                            type="text"
                            maxLength={64}
                            placeholder={t("form.window_label_placeholder")}
                            value={win.label}
                            onChange={(event) =>
                              updateWindow(idx, { label: event.target.value })
                            }
                          />
                        </div>
                        <div className="field pw-window-field">
                          <label className="field-label">
                            {t("form.window_start_time")}
                          </label>
                          <input
                            className="field-input"
                            type="time"
                            value={win.startTime}
                            onChange={(event) =>
                              updateWindow(idx, { startTime: event.target.value })
                            }
                          />
                        </div>
                      </div>
                      {windows.length > 1 && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => removeWindow(idx)}
                          data-testid="rj-window-remove"
                        >
                          {t("form.window_remove")}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                {fieldErrors.windows && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.windows}
                  </div>
                )}
                <button
                  type="button"
                  className="btn btn-secondary btn-sm pw-window-add"
                  onClick={addWindow}
                  data-testid="rj-window-add"
                >
                  {t("form.window_add")}
                </button>
              </div>
            )}
          </div>

          {/* ----- Prijs -----
              W-PW1 — a recurring job is billed as a membership through
              its contract line; there is no pricing mode to choose. The
              line is the price question, defaulted from the contract
              when the customer has exactly one line. */}
          <div className="form-section" data-testid="rj-section-price">
            <div className="form-section-title">{t("form.s_price")}</div>
            {customer === "" ? (
              <p className="muted small">{t("form.price_pick_customer")}</p>
            ) : currentContractLines.length === 0 ? (
              <p className="muted small" data-testid="rj-price-no-contract">
                {t("form.price_no_contract")}
              </p>
            ) : (
              <div className="field">
                <label className="field-label" htmlFor="rj-contract-line">
                  {t("form.field_contract_line")}
                </label>
                <select
                  id="rj-contract-line"
                  className="field-select"
                  data-testid="recurring-job-contract-line"
                  value={effectiveContractLineId || NO_CONTRACT_LINE}
                  onChange={(event) => setContractLineId(event.target.value)}
                >
                  <option value={NO_CONTRACT_LINE}>{t("form.price_none")}</option>
                  {currentContractLines.map((line) => (
                    <option key={line.id} value={String(line.id)}>
                      {line.contractNo
                        ? `${line.lineName} — ${line.contractNo}`
                        : line.lineName}
                    </option>
                  ))}
                </select>
                <span className="muted small">
                  {t("form.field_contract_line_hint")}
                </span>
              </div>
            )}
          </div>

          {/* ----- Ploeg ----- optional, collapsed. */}
          <div className="form-section">
            <details className="form-fold" data-testid="rj-group-crew">
              <summary className="form-fold-summary">
                {t("form.s_crew")}
                <span className="form-fold-summary-value">
                  {crewCount > 0
                    ? t("form.crew_summary", { count: crewCount })
                    : t("form.crew_summary_none")}
                </span>
              </summary>
              <div className="form-fold-body">
                {building === "" ? (
                  <p className="muted small">
                    {t("form.crew_select_building_first")}
                  </p>
                ) : crewLoading ? (
                  <p className="muted small">{t("form.crew_loading")}</p>
                ) : crewError ? (
                  <p className="muted small">{t("form.crew_load_failed")}</p>
                ) : (
                  <div className="form-2col">
                    <div className="field">
                      <label className="field-label">
                        {t("form.field_default_staff")}
                      </label>
                      <div className="form-section-helper">
                        {t("form.field_default_staff_hint")}
                      </div>
                      <CrewPicker
                        candidates={eligibleStaff}
                        selected={defaultStaffIds}
                        onToggle={(uid) =>
                          setDefaultStaffIds((prev) => toggleId(prev, uid))
                        }
                        onSetAll={setDefaultStaffIds}
                        emptyLabel={t("form.no_staff_options")}
                        testId="rj-staff-picker"
                      />
                      {fieldErrors.default_staff_ids && (
                        <div className="alert-error login-error" role="alert">
                          {fieldErrors.default_staff_ids}
                        </div>
                      )}
                    </div>
                    <div className="field">
                      <label className="field-label">
                        {t("form.field_default_managers")}
                      </label>
                      <div className="form-section-helper">
                        {t("form.field_default_managers_hint")}
                      </div>
                      <CrewPicker
                        candidates={eligibleManagers}
                        selected={defaultManagerIds}
                        onToggle={(uid) =>
                          setDefaultManagerIds((prev) => toggleId(prev, uid))
                        }
                        onSetAll={setDefaultManagerIds}
                        emptyLabel={t("form.no_manager_options")}
                        testId="rj-manager-picker"
                      />
                      {fieldErrors.default_manager_ids && (
                        <div className="alert-error login-error" role="alert">
                          {fieldErrors.default_manager_ids}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </details>
          </div>

          <div className="form-actions">
            <Link to={backHref} className="btn btn-secondary">
              {t("form.cancel")}
            </Link>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
              data-testid="recurring-job-submit"
            >
              {submitting
                ? t("form.saving")
                : isCreate
                  ? t("form.submit_create")
                  : t("form.submit_edit")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function CrewPicker({
  candidates,
  selected,
  onToggle,
  onSetAll,
  emptyLabel,
  testId,
}: {
  candidates: CrewUser[];
  selected: number[];
  onToggle: (userId: number) => void;
  // #108 Part D — bulk selection for the shared toolbar (Select all /
  // Clear all). Receives the FULL new id list.
  onSetAll: (userIds: number[]) => void;
  emptyLabel: string;
  testId: string;
}) {
  // Display-only row filter — hidden-but-selected users stay selected.
  const [filter, setFilter] = useState("");
  if (candidates.length === 0) {
    return <p className="muted small">{emptyLabel}</p>;
  }
  const needle = filter.trim().toLowerCase();
  const visible = candidates.filter(
    (user) =>
      !needle ||
      user.email.toLowerCase().includes(needle) ||
      (user.full_name ?? "").toLowerCase().includes(needle),
  );
  return (
    <div className="crew-picker" data-testid={testId}>
      <MultiSelectToolbar
        selectedCount={selected.length}
        onSelectAll={() => onSetAll(candidates.map((u) => u.id))}
        onClearAll={() => onSetAll([])}
        filterValue={filter}
        onFilterChange={setFilter}
        testIdPrefix={testId}
      />
      <div className="crew-picker-list multi-select-list">
        {visible.map((user) => (
          <label key={user.id} className="crew-picker-row">
            <input
              type="checkbox"
              className="checkbox-input"
              checked={selected.includes(user.id)}
              onChange={() => onToggle(user.id)}
            />
            <span>
              {user.email}
              {user.full_name ? ` — ${user.full_name}` : ""}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
