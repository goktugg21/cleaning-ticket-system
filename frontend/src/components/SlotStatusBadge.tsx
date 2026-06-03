import { useTranslation } from "react-i18next";
import { StatusBadge } from "./StatusBadge";
import type { StatusTone } from "../lib/enumLabels";
import type { SlotStatus } from "../api/admin";

// Maps the four staff-slot statuses onto the shared StatusBadge tone
// palette. Source of truth: backend StaffAssignmentSlotStatus
// (ASSIGNED | COMPLETED | UNABLE_TO_COMPLETE | CANCELLED).
const SLOT_TONE: Record<SlotStatus, StatusTone> = {
  ASSIGNED: "open",
  COMPLETED: "approved",
  UNABLE_TO_COMPLETE: "rejected",
  CANCELLED: "closed",
};

export function SlotStatusBadge({
  status,
  variant = "cell",
}: {
  status: SlotStatus;
  variant?: "pill" | "cell";
}) {
  const { t } = useTranslation("staff_slots");
  return (
    <StatusBadge
      variant={variant}
      status={{
        kind: "generic",
        tone: SLOT_TONE[status] ?? "neutral",
        label: t(`slot_status.${status}`),
      }}
    />
  );
}
