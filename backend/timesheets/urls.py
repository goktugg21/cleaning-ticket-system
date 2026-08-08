"""
Sprint 152 — URL routes for the timesheets module, mounted at
`/api/timesheets/` (see `backend/config/urls.py`).

The literal-segment routes (`hour-types/standard-set/`,
`summary/export.csv`, `weeks/close/`) are declared BEFORE the
`<int:...>` detail routes they sit near, following the precedent in
`extra_work/urls_catalog.py`. A numeric converter would not swallow a
non-numeric segment anyway; the ordering documents the intent so a later
change to a converter cannot quietly break it.
"""
from django.urls import path

from .views_employees import TimesheetEmployeeListView
from .views_entries import TimeEntryDetailView, TimeEntryListCreateView
from .views_hour_types import (
    HourTypeDetailView,
    HourTypeListCreateView,
    HourTypeStandardSetView,
)
from .views_summary import TimesheetSummaryCSVView, TimesheetSummaryView
from .views_week_grid import TimeEntryWeekGridView
from .views_weeks import (
    WeekCloseView,
    WeekLockListView,
    WeekReopenView,
    WeekStatusView,
)


urlpatterns = [
    path(
        "hour-types/standard-set/",
        HourTypeStandardSetView.as_view(),
        name="timesheet-hour-type-standard-set",
    ),
    path(
        "hour-types/",
        HourTypeListCreateView.as_view(),
        name="timesheet-hour-type-list",
    ),
    path(
        "hour-types/<int:hour_type_id>/",
        HourTypeDetailView.as_view(),
        name="timesheet-hour-type-detail",
    ),
    # Sprint 152.1 — the admin entry form's employee picker. Its own
    # endpoint rather than a param on `/api/employees/`; see
    # `views_employees` for why.
    path(
        "employees/",
        TimesheetEmployeeListView.as_view(),
        name="timesheet-employee-list",
    ),
    # Sprint 154 §M — the week grid. Declared BEFORE `entries/<int:...>/`
    # for the same reason as the other literal-segment routes in this
    # file: the ordering documents the intent, so a later change to a
    # converter cannot quietly let the detail route swallow it.
    path(
        "entries/bulk-week/",
        TimeEntryWeekGridView.as_view(),
        name="timesheet-entry-bulk-week",
    ),
    path(
        "entries/",
        TimeEntryListCreateView.as_view(),
        name="timesheet-entry-list",
    ),
    path(
        "entries/<int:entry_id>/",
        TimeEntryDetailView.as_view(),
        name="timesheet-entry-detail",
    ),
    path(
        "weeks/status/",
        WeekStatusView.as_view(),
        name="timesheet-week-status",
    ),
    path(
        "weeks/close/",
        WeekCloseView.as_view(),
        name="timesheet-week-close",
    ),
    path(
        "weeks/reopen/",
        WeekReopenView.as_view(),
        name="timesheet-week-reopen",
    ),
    path(
        "weeks/",
        WeekLockListView.as_view(),
        name="timesheet-week-list",
    ),
    path(
        "summary/export.csv",
        TimesheetSummaryCSVView.as_view(),
        name="timesheet-summary-csv",
    ),
    path(
        "summary/",
        TimesheetSummaryView.as_view(),
        name="timesheet-summary",
    ),
]
