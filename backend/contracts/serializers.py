"""
Sprint 160 — serializers for the contracts module.

The rule that shapes every one of them: **validation lookups resolve
through the SAME scoped queryset the picker endpoint reads.** An id the
picker would not offer is an id the write path does not accept, by
construction rather than by two lists that happen to agree — and an
out-of-scope id produces DRF's `does_not_exist`, byte-identical to a
fictional one, so no response distinguishes "does not exist" from
"exists but is not yours" (H-1, the Sprint 142.1 defect class).

Cross-company buildings are the one case that is a DIFFERENT 400, and
deliberately so: a SUPER_ADMIN legitimately sees company A and company
B, so naming a B building on an A contract is a mistake to report, not
an existence leak to hide. A COMPANY_ADMIN never reaches that branch —
a foreign building is already out of their scope and reads as
nonexistent.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from buildings.models import Building
from customers.models import Customer

from .models import (
    Contract,
    ContractBuilding,
    ContractLine,
    ContractRevision,
    ContractType,
    MONTHS_PER_PERIOD,
)
from .numbering import allocate_contract_number
from .revisions import (
    contract_has_been_invoiced,
    display_revision,
    is_locked,
    revision_totals,
)
from .scope import (
    filter_buildings_for_contracts,
    filter_contract_types_for,
    filter_customers_for_contracts,
)


# Stable error codes. Quoted in tests and in the frontend's error
# mapping; do not reword without changing both.
ERR_CONTRACT_TYPE_NAME_NOT_UNIQUE = "contract_type_name_not_unique"
ERR_BUILDING_CROSS_COMPANY = "building_cross_company"
# W20 — a contract line naming a department of ANOTHER customer is a
# tenant-scoping violation, not a validation nicety.
ERR_DEPARTMENT_CROSS_CUSTOMER = "department_cross_customer"
ERR_CUSTOMER_CROSS_COMPANY = "customer_cross_company"
ERR_CONTRACT_TYPE_CROSS_COMPANY = "contract_type_cross_company"
ERR_REVISION_LOCKED = "revision_locked"
ERR_END_BEFORE_START = "end_date_before_start_date"

# DRF's stock `does_not_exist` message is
# `Invalid pk "{pk_value}" - object does not exist.` — it echoes the id
# back. Echoing the caller's OWN input leaks nothing, but it does make
# the two bodies textually different, which turns the H-1 property
# ("a foreign id and a fictional id are indistinguishable") into
# something a test can only assert after normalising the message.
# Removing the echo makes the two responses genuinely byte-identical,
# so the assertion is literal and cannot rot into a weaker one.
DOES_NOT_EXIST_MESSAGE = "Invalid pk - object does not exist."

# The default label of the automatically-created first revision. Dutch
# because nl is this project's primary language; the frontend sends the
# viewer's own translation of the same string, so an operator sees it in
# their language and this constant is only the fallback for a contract
# created without one (fixtures, imports, the API used directly).
DEFAULT_INITIAL_REVISION_LABEL = "Oorspronkelijk contract"


class ContractTypeSerializer(serializers.ModelSerializer):
    """The per-company catalog of contract kinds."""

    contract_count = serializers.SerializerMethodField()

    class Meta:
        model = ContractType
        fields = [
            "id",
            "company",
            "name",
            "standard_slot",
            "is_active",
            "sort_order",
            "contract_count",
            "created_at",
            "updated_at",
        ]
        # `standard_slot` is DERIVED in save() and never client-set —
        # accepting it would let a caller claim a row is a standard kind
        # whose name says otherwise.
        read_only_fields = ["id", "standard_slot", "created_at", "updated_at"]
        extra_kwargs = {"company": {"required": False}}

    def get_contract_count(self, obj) -> int:
        # Annotated by the view for the list path; the fallback keeps a
        # detail read correct without a second annotation.
        if hasattr(obj, "annotated_contract_count"):
            return obj.annotated_contract_count
        return obj.contracts.count()

    def validate_name(self, value):
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("Name may not be blank.")
        return cleaned


class ContractLineSerializer(serializers.ModelSerializer):
    """One project on a revision.

    `building` is optional and, when given, must be one of the parent
    CONTRACT's buildings — not merely a building of the company. A
    project cannot be located somewhere the contract does not cover.
    """

    building_name = serializers.CharField(
        source="building.name", read_only=True, default=None
    )
    # The Extra Work has no human-facing number of its own (its list
    # and detail address it by id), so the register links by id too.
    extra_work_no = serializers.IntegerField(
        source="extra_work.id", read_only=True, default=None
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None
    )

    class Meta:
        model = ContractLine
        fields = [
            "id",
            "revision",
            "name",
            "building",
            "building_name",
            "sort_order",
            "hours",
            "area_m2",
            # W20 — the three planning fields. `frequency_per_year` is a
            # count of performances per year, never money; `norm` is the
            # operator's spec note; `department` must belong to the
            # contract's OWN customer (validate_department).
            "frequency_per_year",
            "norm",
            "department",
            "department_name",
            "amount",
            "vat_pct",
            # W16 — the chargeable job this line MIRRORS, on an extra
            # work register; NULL on every ordinary contract line.
            # READ-ONLY: the link is made by
            # `extra_work_register.sync_extra_work_register`, and a
            # client that could set it would be claiming one job's money
            # for another's line.
            "extra_work",
            "extra_work_no",
        ]
        # W20 — one list. This used to be TWO assignments, and the
        # second silently replaced the first, which left `extra_work`
        # writable despite the comment above saying it must not be.
        read_only_fields = ["id", "revision", "extra_work"]

    def validate_name(self, value):
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("Name may not be blank.")
        return cleaned

    def validate_amount(self, value):
        if value is not None and value < Decimal("0.00"):
            raise serializers.ValidationError("Amount may not be negative.")
        return value

    def validate_building(self, value):
        if value is None:
            return value
        revision = self.context.get("revision")
        if revision is None and self.instance is not None:
            revision = self.instance.revision
        if revision is None:
            return value
        covered = set(
            revision.contract.building_links.values_list(
                "building_id", flat=True
            )
        )
        if value.id not in covered:
            raise serializers.ValidationError(
                "This building is not covered by the contract.",
                code=ERR_BUILDING_CROSS_COMPANY,
            )
        return value

    def validate_department(self, value):
        """W20 — the department must be the contract's OWN customer's.

        `Department` is a per-customer label list; a line naming
        another customer's label would leak one tenant's vocabulary
        into another's agreed scope (H-1/H-2 territory). Same
        revision-resolution shape as `validate_building` above, so the
        two guards cannot drift apart.
        """
        if value is None:
            return value
        revision = self.context.get("revision")
        if revision is None and self.instance is not None:
            revision = self.instance.revision
        if revision is None:
            return value
        if value.customer_id != revision.contract.customer_id:
            raise serializers.ValidationError(
                "This department belongs to another customer.",
                code=ERR_DEPARTMENT_CROSS_CUSTOMER,
            )
        return value


class ContractLineNestedSerializer(serializers.ModelSerializer):
    """Read-only projection of a line for the contract list / detail
    payloads. Separate from `ContractLineSerializer` so the write shape
    can gain validation without widening what a list read exposes.
    """

    building_name = serializers.CharField(
        source="building.name", read_only=True, default=None
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None
    )

    class Meta:
        model = ContractLine
        fields = [
            "id",
            "name",
            "building",
            "building_name",
            "sort_order",
            "hours",
            "area_m2",
            # W20 — mirrored from the write serializer so the detail
            # page's `projects` payload can render what was entered.
            "frequency_per_year",
            "norm",
            "department",
            "department_name",
            "amount",
            "vat_pct",
        ]
        read_only_fields = fields


class ContractRevisionSerializer(serializers.ModelSerializer):
    """A version of the contract's agreed scope.

    `is_locked` is DERIVED (`revisions.is_locked`): a revision whose
    effective date has arrived is closed to edits, and a correction is
    a new revision. The flag is computed on read rather than stored,
    for the same reason the active revision is derived.
    """

    created_by_name = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    hours = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    lines = ContractLineNestedSerializer(many=True, read_only=True)

    class Meta:
        model = ContractRevision
        fields = [
            "id",
            "contract",
            "label",
            "effective_from",
            "notes",
            "created_by",
            "created_by_name",
            "created_at",
            "amount",
            "hours",
            "line_count",
            "is_locked",
            "is_active",
            "lines",
        ]
        read_only_fields = ["id", "contract", "created_by", "created_at"]

    def get_created_by_name(self, obj):
        user = obj.created_by
        if user is None:
            return None
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.email

    def get_amount(self, obj) -> Decimal:
        return revision_totals(obj)["amount"]

    def get_hours(self, obj) -> Decimal:
        return revision_totals(obj)["hours"]

    def get_line_count(self, obj) -> int:
        return revision_totals(obj)["line_count"]

    def get_is_locked(self, obj) -> bool:
        # One existence query per CONTRACT, not per revision: the detail
        # page serializes every revision a contract has.
        cache = self.context.setdefault("_contract_invoiced", {})
        if obj.contract_id not in cache:
            cache[obj.contract_id] = contract_has_been_invoiced(obj.contract_id)
        return is_locked(obj, contract_invoiced=cache[obj.contract_id])

    def get_is_active(self, obj) -> bool:
        """True for the ONE revision currently in force. Computed from
        the contract's revisions, never stored — see
        `contracts/revisions.py`."""
        current = self.context.get("active_revision_id")
        if current is not None:
            return obj.id == current
        resolved = display_revision(obj.contract)
        return resolved is not None and resolved.id == obj.id

    def validate_label(self, value):
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("Label may not be blank.")
        return cleaned


class ContractSerializer(serializers.ModelSerializer):
    """The contract header, plus the derived money the UI reads.

    Every total here (`monthly_amount`, `yearly_amount`, `total_hours`,
    `line_count`) is computed from the ACTIVE revision's lines and
    stored nowhere. The list view annotates them onto the queryset so a
    page of contracts costs a constant number of queries; the
    `revision_totals` fallback keeps a single-instance read correct.
    """

    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None
    )
    customer_name = serializers.CharField(
        source="customer.name", read_only=True, default=None
    )
    contract_type_name = serializers.CharField(
        source="contract_type.name", read_only=True, default=None
    )
    # Sprint 169 §4 — the name PLUS the slot, so the client can render a
    # standard kind in the reader's language. The JSON is never
    # translated server-side; that decision belongs to one frontend
    # helper, `lib/contractTypeLabel.ts`.
    contract_type_standard_slot = serializers.CharField(
        source="contract_type.standard_slot", read_only=True, default=""
    )
    contract_no = serializers.CharField(read_only=True)
    status = serializers.SerializerMethodField()
    # W20 — READ-ONLY, and a METHOD field rather than the model field:
    # `Contract` carries a partial UniqueConstraint conditioned on
    # `kind` (one EXTRA_WORK register per customer), and DRF
    # auto-attaches a validator for any constraint whose fields all
    # appear as serializer sources — a validator that then KeyErrors on
    # every write because a read-only `kind` never reaches `attrs`. A
    # method field's source is '*', so the constraint stays out of the
    # write path exactly as it was before `kind` was exposed.
    kind = serializers.SerializerMethodField()

    building_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        write_only=True,
        required=False,
        queryset=Building.objects.none(),
        help_text="The buildings ('locations') this contract covers.",
    )
    buildings = serializers.SerializerMethodField()

    active_revision = serializers.SerializerMethodField()
    monthly_amount = serializers.SerializerMethodField()
    yearly_amount = serializers.SerializerMethodField()
    total_hours = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()
    projects = serializers.SerializerMethodField()

    initial_revision_label = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text=(
            "Label for the first revision, created automatically with "
            "the contract. Defaults to the Dutch "
            f'"{DEFAULT_INITIAL_REVISION_LABEL}".'
        ),
    )

    class Meta:
        model = Contract
        fields = [
            "id",
            "company",
            "company_name",
            "customer",
            "customer_name",
            "contract_type",
            "contract_type_name",
            "contract_type_standard_slot",
            "contract_no",
            # W20 — the frontend needs to know an EXTRA_WORK register
            # from a STANDARD contract to hide the planning fields on
            # register lines (they are projected, not authored). Never
            # client-writable: registers are created only by
            # `extra_work_register.get_or_create_register`. See the
            # method-field declaration for why it is one.
            "kind",
            "start_date",
            "end_date",
            "lifecycle",
            "status",
            "description",
            "notes",
            "billing_period",
            "billing_day",
            "billing_type",
            "payment_terms_days",
            "start_proration",
            "building_ids",
            "buildings",
            "active_revision",
            "monthly_amount",
            "yearly_amount",
            "total_hours",
            "line_count",
            "projects",
            "initial_revision_label",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "contract_no", "created_at", "updated_at"]
        extra_kwargs = {"company": {"required": False}}

    def __init__(self, *args, **kwargs):
        """Bind the relational fields to the ACTOR'S scoped querysets.

        This is the H-1 mechanism, not a convenience: with the queryset
        scoped, an id belonging to another tenant fails with
        `does_not_exist` — the same error, the same code, the same
        response body as an id that was never real.
        """
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None:
            return
        building_field = self.fields["building_ids"].child_relation
        building_field.queryset = filter_buildings_for_contracts(
            user, Building.objects.all()
        )
        self.fields["customer"].queryset = filter_customers_for_contracts(
            user, Customer.objects.all()
        )
        self.fields["contract_type"].queryset = filter_contract_types_for(
            user, ContractType.objects.all()
        )
        for field in (
            building_field,
            self.fields["customer"],
            self.fields["contract_type"],
        ):
            field.error_messages["does_not_exist"] = DOES_NOT_EXIST_MESSAGE

    # --- derived reads ------------------------------------------------

    def _active_revision(self, obj):
        cached = getattr(obj, "_cached_active_revision", "unset")
        if cached != "unset":
            return cached
        by_contract = self.context.get("active_revisions") or {}
        revision = by_contract.get(obj.id)
        if revision is None and not by_contract:
            revision = display_revision(obj)
        obj._cached_active_revision = revision
        return revision

    def get_status(self, obj) -> str:
        return obj.status()

    def get_kind(self, obj) -> str:
        return obj.kind

    def get_buildings(self, obj):
        # `.all()` with NO further queryset methods on purpose: the view
        # prefetches `building_links__building`, and any additional
        # `.select_related()` / `.filter()` here would bypass that cache
        # and re-query PER ROW. That is exactly the per-row cost
        # `tests/test_query_counts.py` exists to catch.
        return [
            {"id": link.building_id, "name": link.building.name}
            for link in obj.building_links.all()
        ]

    def get_active_revision(self, obj):
        revision = self._active_revision(obj)
        if revision is None:
            return None
        totals = revision_totals(revision)
        return {
            "id": revision.id,
            "label": revision.label,
            "effective_from": revision.effective_from,
            "amount": totals["amount"],
            "hours": totals["hours"],
            "line_count": totals["line_count"],
        }

    def _period_amount(self, obj) -> Decimal:
        revision = self._active_revision(obj)
        if revision is None:
            return Decimal("0.00")
        return revision_totals(revision)["amount"]

    def get_monthly_amount(self, obj) -> Decimal:
        """The active revision's period money normalised to one month.

        NOT a stored figure and NOT the invoice forecast's yearly / 12
        — see `contracts/billing.py` for why those two legitimately
        differ once proration is involved.
        """
        from .billing import money

        months = MONTHS_PER_PERIOD[obj.billing_period]
        return money(self._period_amount(obj) / Decimal(months))

    def get_yearly_amount(self, obj) -> Decimal:
        """Twelve months of the active revision at its current price.

        This is the CATALOG yearly figure the list page totals, and it
        is deliberately not the forecast's `yearly_amount`: this one
        answers "what is this contract worth in a full year at today's
        agreed price", the forecast answers "what will actually be
        invoiced in year N", which includes proration and any
        revision that takes effect partway through.
        """
        from .billing import money

        months = MONTHS_PER_PERIOD[obj.billing_period]
        return money(self._period_amount(obj) * Decimal(12) / Decimal(months))

    def get_total_hours(self, obj) -> Decimal:
        revision = self._active_revision(obj)
        if revision is None:
            return Decimal("0.00")
        return revision_totals(revision)["hours"]

    def get_line_count(self, obj) -> int:
        revision = self._active_revision(obj)
        if revision is None:
            return 0
        return revision_totals(revision)["line_count"]

    def get_projects(self, obj):
        """The active revision's lines, as the list page's dynamic
        per-project columns read them."""
        revision = self._active_revision(obj)
        if revision is None:
            return []
        return ContractLineNestedSerializer(
            revision.lines.all(), many=True
        ).data

    # --- validation ---------------------------------------------------

    def validate(self, attrs):
        start = attrs.get("start_date") or getattr(
            self.instance, "start_date", None
        )
        end = (
            attrs.get("end_date")
            if "end_date" in attrs
            else getattr(self.instance, "end_date", None)
        )
        if start and end and end < start:
            raise serializers.ValidationError(
                {
                    "end_date": [
                        serializers.ErrorDetail(
                            "End date must be on or after the start date.",
                            code=ERR_END_BEFORE_START,
                        )
                    ]
                }
            )
        return attrs

    def validate_company_consistency(self, company, attrs):
        """Every related row must belong to the contract's OWN company.

        Reached only by an actor who can already see both companies (a
        SUPER_ADMIN), because for anyone else the foreign row was
        filtered out of the scoped queryset and failed earlier as
        `does_not_exist`. So this is a genuine 400 about a mistake, not
        a masked existence answer.
        """
        errors = {}
        customer = attrs.get("customer") or getattr(
            self.instance, "customer", None
        )
        if customer is not None and customer.company_id != company.id:
            errors["customer"] = [
                serializers.ErrorDetail(
                    "This customer belongs to another company.",
                    code=ERR_CUSTOMER_CROSS_COMPANY,
                )
            ]
        contract_type = attrs.get("contract_type") or getattr(
            self.instance, "contract_type", None
        )
        if contract_type is not None and contract_type.company_id != company.id:
            errors["contract_type"] = [
                serializers.ErrorDetail(
                    "This contract type belongs to another company.",
                    code=ERR_CONTRACT_TYPE_CROSS_COMPANY,
                )
            ]
        buildings = attrs.get("building_ids")
        if buildings:
            foreign = [b for b in buildings if b.company_id != company.id]
            if foreign:
                errors["building_ids"] = [
                    serializers.ErrorDetail(
                        "One or more buildings belong to another company.",
                        code=ERR_BUILDING_CROSS_COMPANY,
                    )
                ]
        if errors:
            raise serializers.ValidationError(errors)


class ContractForecastRowSerializer(serializers.Serializer):
    """One PLANNED invoice. Read-only by construction — the forecast is
    a calculation and this app writes no invoices (Sprint 158 does)."""

    invoice_date = serializers.DateField(read_only=True)
    due_date = serializers.DateField(read_only=True)
    period_start = serializers.DateField(read_only=True)
    period_end = serializers.DateField(read_only=True)
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    is_prorated = serializers.BooleanField(read_only=True)
    covered_days = serializers.IntegerField(read_only=True)
    period_days = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)


class ContractForecastSerializer(serializers.Serializer):
    """The Invoice Preview payload for one contract and one year."""

    year = serializers.IntegerField(read_only=True)
    rows = ContractForecastRowSerializer(many=True, read_only=True)
    rows_total = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    yearly_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    monthly_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    invoices_per_year = serializers.IntegerField(read_only=True)
    first_invoice_date = serializers.DateField(read_only=True, allow_null=True)
    excluded_first_invoice = serializers.BooleanField(read_only=True)


def create_contract(*, serializer, company, user):
    """Create a contract, its building links and its FIRST revision, in
    ONE transaction.

    A contract is never revision-less: the first revision is created
    here, labelled by the caller (or the Dutch default), effective from
    the contract's own start date. Everything the contract is worth
    hangs off that revision, so a failure to create it would leave a
    contract that reads as zero money — hence one atomic block, with
    the number allocation inside it.
    """
    data = dict(serializer.validated_data)
    buildings = data.pop("building_ids", [])
    label = (data.pop("initial_revision_label", "") or "").strip()
    data.pop("company", None)

    year = data["start_date"].year
    with transaction.atomic():
        number, _seq = allocate_contract_number(company.id, year)
        contract = Contract.objects.create(
            company=company, contract_no=number, **data
        )
        for building in buildings:
            ContractBuilding.objects.create(
                contract=contract, building=building
            )
        ContractRevision.objects.create(
            contract=contract,
            label=label or DEFAULT_INITIAL_REVISION_LABEL,
            effective_from=contract.start_date,
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
    return contract


def sync_contract_buildings(contract, buildings):
    """Replace a contract's building links with `buildings`.

    Add / remove rather than delete-all-and-recreate, so the audit log
    records the two buildings that actually changed instead of every
    building on the contract churning on an unrelated edit.
    """
    current = {
        link.building_id: link for link in contract.building_links.all()
    }
    wanted = {building.id: building for building in buildings}
    for building_id, link in current.items():
        if building_id not in wanted:
            link.delete()
    for building_id, building in wanted.items():
        if building_id not in current:
            ContractBuilding.objects.create(
                contract=contract, building=building
            )


def assert_revision_editable(revision):
    """Raise a 400 if `revision` is closed to edits.

    A revision locks the moment its effective date arrives, because
    from then on it is what the contract agreed and money has been
    computed against it. The correction path is a NEW revision — the
    same discipline that makes a SENT invoice correctable only by
    reversal.
    """
    if is_locked(revision):
        raise serializers.ValidationError(
            {
                "revision": [
                    serializers.ErrorDetail(
                        "This revision is in force and can no longer be "
                        "edited. Create a new revision instead.",
                        code=ERR_REVISION_LOCKED,
                    )
                ]
            }
        )


def default_effective_from(contract):
    """A sensible `effective_from` for a NEW revision: tomorrow, or the
    contract's start date if that is still in the future.

    Never today: a revision created with today's date would be locked
    the instant it was saved, which is a confusing first experience of
    a feature whose whole purpose is forward-dating.
    """
    today = timezone.localdate()
    if contract.start_date > today:
        return contract.start_date
    return today + timedelta(days=1)
