from django.urls import path

from .views_extra_work_hours import ExtraWorkHoursView
from .views_planned_vs_actual import ExtraWorkPlannedVsActualView
from .views_labour_rates import (
    EmployeeHourlyRateDetailView,
    EmployeeHourlyRateListCreateView,
)
from .views import (
    EmployeeHoursByBuildingView,
    EmployeeHoursByExtraWorkView,
    EmployeeHoursWeeklyView,
    HourSourceOptionsView,
    PeriodReportSummariesView,
    MeldingenByCategoryView,
    TicketReportView,
    WorkerHoursExportView,
    WorkerHoursReportView,
    HoursComparisonView,
    AgeBucketsView,
    ExtraWorkByDepartmentCSVView,
    ExtraWorkByDepartmentPDFView,
    ExtraWorkByDepartmentView,
    ExtraWorkRevenueByBuildingCSVView,
    ExtraWorkRevenueByBuildingPDFView,
    ExtraWorkRevenueByBuildingView,
    ExtraWorkRevenueCSVView,
    ExtraWorkRevenuePDFView,
    ExtraWorkRevenueView,
    ManagerThroughputView,
    SLABreachRateOverTimeView,
    SLADistributionView,
    StatusDistributionView,
    TicketsByBuildingCSVView,
    TicketsByBuildingPDFView,
    TicketsByBuildingView,
    TicketsByCustomerCSVView,
    TicketsByCustomerPDFView,
    TicketsByCustomerView,
    TicketsByOriginCSVView,
    TicketsByOriginPDFView,
    TicketsByOriginView,
    TicketsByTypeCSVView,
    TicketsByTypePDFView,
    TicketsByTypeView,
    TicketsOverTimeView,
)


urlpatterns = [
    # Sprint 177 §7 — the source picker. A plain literal path, before the
    # report routes, in keeping with the ordering rule below.
    path(
        "hour-sources/",
        HourSourceOptionsView.as_view(),
        name="report-hour-sources",
    ),
    # Sprint 180 §2 — the four report CARDS, in one request. A literal
    # path, before the report routes, in keeping with the ordering rule
    # below.
    path(
        "period-report-summaries/",
        PeriodReportSummariesView.as_view(),
        name="report-period-summaries",
    ),
    # Sprint 178 §2 — the four reports. EXPORT literal before the report
    # route in each pair, the ordering this repo keeps so a later
    # converter change cannot let one swallow the other.
    path(
        "employee-hours-by-building/export.<str:fmt>",
        EmployeeHoursByBuildingView.as_view(),
        name="report-employee-hours-by-building-export",
    ),
    path(
        "employee-hours-by-building/",
        EmployeeHoursByBuildingView.as_view(),
        name="report-employee-hours-by-building",
    ),
    path(
        "employee-hours-weekly/export.<str:fmt>",
        EmployeeHoursWeeklyView.as_view(),
        name="report-employee-hours-weekly-export",
    ),
    path(
        "employee-hours-weekly/",
        EmployeeHoursWeeklyView.as_view(),
        name="report-employee-hours-weekly",
    ),
    path(
        "employee-hours-by-extra-work/export.<str:fmt>",
        EmployeeHoursByExtraWorkView.as_view(),
        name="report-employee-hours-by-extra-work-export",
    ),
    path(
        "employee-hours-by-extra-work/",
        EmployeeHoursByExtraWorkView.as_view(),
        name="report-employee-hours-by-extra-work",
    ),
    # Sprint 185 E §1 — the export literal BEFORE the report route, the
    # ordering this repo keeps so a later converter change cannot let one
    # swallow the other.
    path(
        "meldingen-by-category/export.<str:fmt>",
        MeldingenByCategoryView.as_view(),
        name="report-meldingen-by-category-export",
    ),
    path(
        "meldingen-by-category/",
        MeldingenByCategoryView.as_view(),
        name="report-meldingen-by-category",
    ),
    path(
        "ticket-report/export.<str:fmt>",
        TicketReportView.as_view(),
        name="report-ticket-report-export",
    ),
    path(
        "ticket-report/",
        TicketReportView.as_view(),
        name="report-ticket-report",
    ),
    # Sprint 171 §4 — the export literals BEFORE the report route, the
    # ordering this repo keeps so a later converter change cannot let
    # one swallow the other.
    path(
        "worker-hours/export.<str:fmt>",
        WorkerHoursExportView.as_view(),
        name="report-worker-hours-export",
    ),
    path(
        "worker-hours/",
        WorkerHoursReportView.as_view(),
        name="report-worker-hours",
    ),
    # Sprint 165 §5 — contracted vs worked hours. Lives in `reports`
    # because it reads BOTH `contracts` and `timesheets`, neither of
    # which may import the other.
    path(
        "hours-comparison/",
        HoursComparisonView.as_view(),
        name="reports-hours-comparison",
    ),
    path(
        "status-distribution/",
        StatusDistributionView.as_view(),
        name="reports-status-distribution",
    ),
    path(
        "tickets-over-time/",
        TicketsOverTimeView.as_view(),
        name="reports-tickets-over-time",
    ),
    path(
        "manager-throughput/",
        ManagerThroughputView.as_view(),
        name="reports-manager-throughput",
    ),
    path(
        "age-buckets/",
        AgeBucketsView.as_view(),
        name="reports-age-buckets",
    ),
    path(
        "sla-distribution/",
        SLADistributionView.as_view(),
        name="reports-sla-distribution",
    ),
    path(
        "sla-breach-rate-over-time/",
        SLABreachRateOverTimeView.as_view(),
        name="reports-sla-breach-rate-over-time",
    ),
    # ---- Sprint 5 dimensions + exports --------------------------------
    path(
        "tickets-by-type/",
        TicketsByTypeView.as_view(),
        name="reports-tickets-by-type",
    ),
    path(
        "tickets-by-type/export.csv",
        TicketsByTypeCSVView.as_view(),
        name="reports-tickets-by-type-csv",
    ),
    path(
        "tickets-by-type/export.pdf",
        TicketsByTypePDFView.as_view(),
        name="reports-tickets-by-type-pdf",
    ),
    path(
        "tickets-by-customer/",
        TicketsByCustomerView.as_view(),
        name="reports-tickets-by-customer",
    ),
    path(
        "tickets-by-customer/export.csv",
        TicketsByCustomerCSVView.as_view(),
        name="reports-tickets-by-customer-csv",
    ),
    path(
        "tickets-by-customer/export.pdf",
        TicketsByCustomerPDFView.as_view(),
        name="reports-tickets-by-customer-pdf",
    ),
    path(
        "tickets-by-building/",
        TicketsByBuildingView.as_view(),
        name="reports-tickets-by-building",
    ),
    path(
        "tickets-by-building/export.csv",
        TicketsByBuildingCSVView.as_view(),
        name="reports-tickets-by-building-csv",
    ),
    path(
        "tickets-by-building/export.pdf",
        TicketsByBuildingPDFView.as_view(),
        name="reports-tickets-by-building-pdf",
    ),
    # ---- Sprint 14A: ticket origin separation -------------------------
    path(
        "tickets-by-origin/",
        TicketsByOriginView.as_view(),
        name="reports-tickets-by-origin",
    ),
    path(
        "tickets-by-origin/export.csv",
        TicketsByOriginCSVView.as_view(),
        name="reports-tickets-by-origin-csv",
    ),
    path(
        "tickets-by-origin/export.pdf",
        TicketsByOriginPDFView.as_view(),
        name="reports-tickets-by-origin-pdf",
    ),
    # ---- Sprint 14A: Extra Work revenue states ------------------------
    path(
        "extra-work-revenue/",
        ExtraWorkRevenueView.as_view(),
        name="reports-extra-work-revenue",
    ),
    path(
        "extra-work-revenue/export.csv",
        ExtraWorkRevenueCSVView.as_view(),
        name="reports-extra-work-revenue-csv",
    ),
    path(
        "extra-work-revenue/export.pdf",
        ExtraWorkRevenuePDFView.as_view(),
        name="reports-extra-work-revenue-pdf",
    ),
    # ---- Sprint 124: Extra Work revenue grouped by building -----------
    path(
        "extra-work-revenue-by-building/",
        ExtraWorkRevenueByBuildingView.as_view(),
        name="reports-extra-work-revenue-by-building",
    ),
    path(
        "extra-work-revenue-by-building/export.csv",
        ExtraWorkRevenueByBuildingCSVView.as_view(),
        name="reports-extra-work-revenue-by-building-csv",
    ),
    path(
        "extra-work-revenue-by-building/export.pdf",
        ExtraWorkRevenueByBuildingPDFView.as_view(),
        name="reports-extra-work-revenue-by-building-pdf",
    ),
    # ---- W4-R: the per-person hourly rate. SA / CA only, at the door
    # and again in the queryset — a wage is personal data and a
    # BUILDING_MANAGER is refused here even though they are admitted to
    # every other reports surface. Literal segment BEFORE the detail
    # route, the ordering this repo keeps. ------------------------------
    path(
        "employee-hourly-rates/",
        EmployeeHourlyRateListCreateView.as_view(),
        name="reports-employee-hourly-rates",
    ),
    path(
        "employee-hourly-rates/<int:pk>/",
        EmployeeHourlyRateDetailView.as_view(),
        name="reports-employee-hourly-rate-detail",
    ),
    # ---- W3-H: the hours booked to ONE extra work, with the roll-up of
    # budget / entered / cost. Read by the panel on the Extra Work detail
    # page; the cost half is computed in `reports/labour_cost.py`, which
    # is the one place it may be. ----------------------------------------
    path(
        "extra-work/<int:extra_work_id>/hours/",
        ExtraWorkHoursView.as_view(),
        name="reports-extra-work-hours",
    ),
    # ---- W7: planned hours beside worked hours, per person, for one
    # job. Read by the panel on the operational ticket. No money in the
    # response, which is what lets STAFF read their own line here while
    # the hours endpoint above refuses them. Distinct literal segment,
    # so neither route can swallow the other. --------------------------
    path(
        "extra-work/<int:extra_work_id>/planned-vs-actual/",
        ExtraWorkPlannedVsActualView.as_view(),
        name="reports-extra-work-planned-vs-actual",
    ),
    # ---- Sprint 131: Extra Work revenue grouped Building -> Department ->
    # Work Type ----------------------------------------------------------
    path(
        "extra-work-by-department/",
        ExtraWorkByDepartmentView.as_view(),
        name="reports-extra-work-by-department",
    ),
    path(
        "extra-work-by-department/export.csv",
        ExtraWorkByDepartmentCSVView.as_view(),
        name="reports-extra-work-by-department-csv",
    ),
    path(
        "extra-work-by-department/export.pdf",
        ExtraWorkByDepartmentPDFView.as_view(),
        name="reports-extra-work-by-department-pdf",
    ),
]
