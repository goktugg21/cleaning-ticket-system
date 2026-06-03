import { useTranslation } from "react-i18next";
import { StatusBadge } from "../../components/StatusBadge";
import type { StatusTone } from "../../lib/enumLabels";
import type { PlannedOccurrenceStatus } from "../../api/plannedWork.types";

// Maps the seven PlannedOccurrenceStatus values onto the shared
// StatusBadge tone palette. Source of truth for the enum:
// backend/planned_work/models.py::PlannedOccurrenceStatus.
const STATUS_TONE: Record<PlannedOccurrenceStatus, StatusTone> = {
  PLANNED: "open",
  TICKET_CREATED: "progress",
  COMPLETED: "approved",
  MISSED: "rejected",
  RESCHEDULED: "waiting",
  SKIPPED: "neutral",
  CANCELLED: "closed",
};

export function OccurrenceStatusBadge({
  status,
  variant = "cell",
}: {
  status: PlannedOccurrenceStatus;
  variant?: "pill" | "cell";
}) {
  const { t } = useTranslation("planned_work");
  return (
    <StatusBadge
      variant={variant}
      status={{
        kind: "generic",
        tone: STATUS_TONE[status] ?? "neutral",
        label: t(`occ_status.${status}`),
      }}
    />
  );
}
