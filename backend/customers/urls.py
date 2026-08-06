from django.urls import path
from rest_framework.routers import DefaultRouter

from extra_work.views_pricing import (
    CustomerPriceFolderDetailView,
    CustomerPriceFolderListCreateView,
    CustomerCustomPriceDetailView,
    CustomerCustomPriceListCreateView,
    CustomerServicePriceBulkRaiseView,
    CustomerServicePriceCopyFromDefaultView,
    CustomerServicePriceDetailView,
    CustomerServicePriceListCreateView,
)

from documents.views import (
    DocumentDetailView,
    DocumentFolderDetailView,
    DocumentFolderListCreateView,
    DocumentListCreateView,
)

from .views import CustomerViewSet
from .views_labels import (
    DepartmentDetailView,
    DepartmentListCreateView,
    WorkTypeDetailView,
    WorkTypeListCreateView,
)
from .views_media import CustomerContractPdfView, CustomerLogoView
from .views_contacts import (
    CustomerContactDetailView,
    CustomerContactListCreateView,
    CustomerContactPromoteView,
)
from .views_memberships import (
    CustomerBuildingDeleteView,
    CustomerBuildingListCreateView,
    CustomerCompanyPolicyView,
    CustomerEmployeesView,
    CustomerUserAccessDeleteView,
    CustomerUserAccessListCreateView,
    CustomerUserCompanyAdminView,
    CustomerUserDeleteView,
    CustomerUserListCreateView,
)


router = DefaultRouter()
router.register(r"", CustomerViewSet, basename="customer")


urlpatterns = [
    # Employees directory — a single customer's people with their
    # effective access role (read-first). Distinct from /users/ (the
    # membership-management surface): SA / PA / CCA-CLM-CU read; the
    # access-role edit reuses the existing /access/ endpoints.
    path(
        "<int:customer_id>/employees/",
        CustomerEmployeesView.as_view(),
        name="customer-employees",
    ),
    # RF-1 — customer logo (GET serve / POST upload / DELETE remove).
    path(
        "<int:customer_id>/logo/",
        CustomerLogoView.as_view(),
        name="customer-logo",
    ),
    # Invoicing Phase 4a — informational contract PDF (GET serve provider /
    # POST upload / DELETE remove — OSIUS admin write).
    path(
        "<int:customer_id>/contract-pdf/",
        CustomerContractPdfView.as_view(),
        name="customer-contract-pdf",
    ),
    # Sprint 125 — customer Documents. Provider (SA / CA) + customer users
    # with `customer.documents.manage` share a per-customer folder tree.
    # View classes live in documents/views.py (the model app owns the
    # views); the URL anchor is customer-scoped here (mirrors the pricing
    # routes). Folders use their integer pk in the path; Documents use their
    # opaque public_id UUID (never the row pk).
    path(
        "<int:customer_id>/documents/folders/",
        DocumentFolderListCreateView.as_view(),
        name="customer-document-folders",
    ),
    path(
        "<int:customer_id>/documents/folders/<int:folder_id>/",
        DocumentFolderDetailView.as_view(),
        name="customer-document-folder-detail",
    ),
    path(
        "<int:customer_id>/documents/files/",
        DocumentListCreateView.as_view(),
        name="customer-document-files",
    ),
    path(
        "<int:customer_id>/documents/files/<uuid:public_id>/",
        DocumentDetailView.as_view(),
        name="customer-document-detail",
    ),
    # Sprint 127 — per-customer Extra Work label lists (Department + Work
    # Type). Provider (SA / CA-own-company) manage the rows; customer users
    # with access read them to populate the Extra Work create dropdowns.
    # View classes live in views_labels.py (the model app owns the views);
    # the URL anchor is customer-scoped here, mirroring the documents /
    # pricing routes.
    path(
        "<int:customer_id>/departments/",
        DepartmentListCreateView.as_view(),
        name="customer-departments",
    ),
    path(
        "<int:customer_id>/departments/<int:label_id>/",
        DepartmentDetailView.as_view(),
        name="customer-department-detail",
    ),
    path(
        "<int:customer_id>/work-types/",
        WorkTypeListCreateView.as_view(),
        name="customer-work-types",
    ),
    path(
        "<int:customer_id>/work-types/<int:label_id>/",
        WorkTypeDetailView.as_view(),
        name="customer-work-type-detail",
    ),
    path(
        "<int:customer_id>/users/",
        CustomerUserListCreateView.as_view(),
        name="customer-users",
    ),
    path(
        "<int:customer_id>/users/<int:user_id>/",
        CustomerUserDeleteView.as_view(),
        name="customer-user-delete",
    ),
    # SoT Addendum A.1 — toggle the company-wide Customer Company Admin
    # status on a customer membership (POST grant / DELETE revoke).
    path(
        "<int:customer_id>/users/<int:user_id>/company-admin/",
        CustomerUserCompanyAdminView.as_view(),
        name="customer-user-company-admin",
    ),
    # Sprint 14 — customer ↔ buildings (M:N).
    path(
        "<int:customer_id>/buildings/",
        CustomerBuildingListCreateView.as_view(),
        name="customer-buildings",
    ),
    path(
        "<int:customer_id>/buildings/<int:building_id>/",
        CustomerBuildingDeleteView.as_view(),
        name="customer-building-delete",
    ),
    # Sprint 14 — per-customer-user building access.
    path(
        "<int:customer_id>/users/<int:user_id>/access/",
        CustomerUserAccessListCreateView.as_view(),
        name="customer-user-access",
    ),
    path(
        "<int:customer_id>/users/<int:user_id>/access/<int:building_id>/",
        CustomerUserAccessDeleteView.as_view(),
        name="customer-user-access-delete",
    ),
    # Sprint 27E — per-customer CustomerCompanyPolicy read/write.
    path(
        "<int:customer_id>/policy/",
        CustomerCompanyPolicyView.as_view(),
        name="customer-policy",
    ),
    # Sprint 28 Batch 4 — per-customer Contact phone-book CRUD.
    path(
        "<int:customer_id>/contacts/",
        CustomerContactListCreateView.as_view(),
        name="customer-contacts",
    ),
    path(
        "<int:customer_id>/contacts/<int:contact_id>/",
        CustomerContactDetailView.as_view(),
        name="customer-contact-detail",
    ),
    # Sprint 12B — promote a Contact into an authenticated customer User.
    path(
        "<int:customer_id>/contacts/<int:contact_id>/promote-to-user/",
        CustomerContactPromoteView.as_view(),
        name="customer-contact-promote",
    ),
    # Sprint 28 Batch 5 — per-customer service contract prices.
    # View classes live in extra_work/views_pricing.py (the model
    # app owns the views); the URL anchor is here so the path is
    # customer-scoped and the IsSuperAdminOrCompanyAdminForCompany
    # gate resolves on the Customer object.
    path(
        "<int:customer_id>/pricing/",
        CustomerServicePriceListCreateView.as_view(),
        name="customer-pricing-list",
    ),
    path(
        "<int:customer_id>/pricing/<int:price_id>/",
        CustomerServicePriceDetailView.as_view(),
        name="customer-pricing-detail",
    ),
    # Sprint 4B — bulk seed CSP rows from Service.default_unit_price /
    # default_vat_pct. Provider-side action (SA always; CA when the
    # customer-price toggle is True).
    path(
        "<int:customer_id>/pricing/copy-from-default/",
        CustomerServicePriceCopyFromDefaultView.as_view(),
        name="customer-pricing-copy-from-default",
    ),
    # M5 C — bulk-raise a customer's contract prices (% or fixed),
    # writing new validity-window rows (history preserved).
    path(
        "<int:customer_id>/pricing/bulk-raise/",
        CustomerServicePriceBulkRaiseView.as_view(),
        name="customer-pricing-bulk-raise",
    ),
    # M5 A — per-customer ad-hoc / custom price lines (non-catalog).
    # Sprint 143 §3 — the customer's OWN folders over their price rows.
    path(
        "<int:customer_id>/price-folders/",
        CustomerPriceFolderListCreateView.as_view(),
        name="customer-price-folder-list",
    ),
    path(
        "<int:customer_id>/price-folders/<int:folder_id>/",
        CustomerPriceFolderDetailView.as_view(),
        name="customer-price-folder-detail",
    ),
    path(
        "<int:customer_id>/custom-pricing/",
        CustomerCustomPriceListCreateView.as_view(),
        name="customer-custom-pricing-list",
    ),
    path(
        "<int:customer_id>/custom-pricing/<int:custom_price_id>/",
        CustomerCustomPriceDetailView.as_view(),
        name="customer-custom-pricing-detail",
    ),
] + router.urls
