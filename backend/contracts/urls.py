"""
Sprint 160 — URL routes for the contracts module, mounted at
`/api/contracts/` (see `backend/config/urls.py`).

The literal-segment routes (`stats/`, `options/`, `types/`,
`revisions/`, `lines/`) are declared BEFORE the `<int:...>` detail
routes they sit near, following the precedent in
`extra_work/urls_catalog.py` and `timesheets/urls.py`. A numeric
converter would not swallow a non-numeric segment anyway; the ordering
documents the intent so a later change to a converter cannot quietly
break it.
"""
from django.urls import path

from .views_contracts import (
    ContractTypeStandardSetView,
    ContractDetailView,
    ContractListCreateView,
    ContractOptionsView,
    ContractStatsView,
    ContractTypeDetailView,
    ContractTypeListCreateView,
)
from .views_forecast import ContractForecastView
from .views_register import ExtraWorkRegisterSyncView, ExtraWorkRegisterView
from .views_revisions import (
    ContractLineDetailView,
    ContractLineListCreateView,
    ContractRevisionDetailView,
    ContractRevisionListCreateView,
)


urlpatterns = [
    path("stats/", ContractStatsView.as_view(), name="contract-stats"),
    # W16 — the per-customer extra work register. Keyed on the CUSTOMER
    # and not on a contract id, exactly as the reference system's
    # `/contracts/extra-works/{customerId}` is: the caller has a
    # customer in hand and must not have to know whether a register has
    # been made yet. Declared above the `<int:contract_id>` routes for
    # the reason the module docstring gives.
    path(
        "extra-works/<int:customer_id>/",
        ExtraWorkRegisterView.as_view(),
        name="contract-extra-work-register",
    ),
    path(
        "extra-works/<int:customer_id>/sync/",
        ExtraWorkRegisterSyncView.as_view(),
        name="contract-extra-work-register-sync",
    ),
    path("options/", ContractOptionsView.as_view(), name="contract-options"),
    path(
        "types/standard-set/",
        ContractTypeStandardSetView.as_view(),
        name="contract-type-standard-set",
    ),
    path(
        "types/",
        ContractTypeListCreateView.as_view(),
        name="contract-type-list",
    ),
    path(
        "types/<int:type_id>/",
        ContractTypeDetailView.as_view(),
        name="contract-type-detail",
    ),
    # Revision + line routes hang off `revisions/` and `lines/` rather
    # than nesting under the contract id, because a revision id is
    # already unique and the frontend holds one when it edits. The
    # CREATE route is the exception: a new revision has no id yet, so it
    # is addressed through its contract.
    path(
        "revisions/<int:revision_id>/lines/",
        ContractLineListCreateView.as_view(),
        name="contract-line-list",
    ),
    path(
        "revisions/<int:revision_id>/",
        ContractRevisionDetailView.as_view(),
        name="contract-revision-detail",
    ),
    path(
        "lines/<int:line_id>/",
        ContractLineDetailView.as_view(),
        name="contract-line-detail",
    ),
    path("", ContractListCreateView.as_view(), name="contract-list"),
    path(
        "<int:contract_id>/revisions/",
        ContractRevisionListCreateView.as_view(),
        name="contract-revision-list",
    ),
    path(
        "<int:contract_id>/forecast/",
        ContractForecastView.as_view(),
        name="contract-forecast",
    ),
    path(
        "<int:contract_id>/",
        ContractDetailView.as_view(),
        name="contract-detail",
    ),
]
