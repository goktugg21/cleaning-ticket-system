/**
 * Sprint 155 §4 — the Edit / Done button that gates every editable list.
 *
 * One component so the label, the `aria-pressed` state and the icon are
 * identical on all eight swept screens. A per-screen copy would drift on
 * the first screen someone tweaks, and "Edit" meaning something slightly
 * different on one list than another is exactly the kind of thing an
 * operator stops trusting.
 *
 * Pair it with `useEditMode` (lib/useEditMode.ts): pass that hook's
 * `editMode` and `toggleMode` straight through.
 */
import { Check, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

export function EditModeToggle({
  editMode,
  onToggle,
  disabled,
  testId,
}: {
  editMode: boolean;
  onToggle: () => void;
  disabled?: boolean;
  testId: string;
}) {
  const { t } = useTranslation("common");
  return (
    <button
      type="button"
      className="btn btn-ghost btn-sm"
      aria-pressed={editMode}
      onClick={onToggle}
      disabled={disabled}
      data-testid={testId}
    >
      {editMode ? (
        <Check size={14} strokeWidth={2.2} />
      ) : (
        <Pencil size={14} strokeWidth={2.2} />
      )}
      <span style={{ marginLeft: 6 }}>
        {editMode ? t("edit_mode.done") : t("edit_mode.edit")}
      </span>
    </button>
  );
}
