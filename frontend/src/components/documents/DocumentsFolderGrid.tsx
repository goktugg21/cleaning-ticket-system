/**
 * Sprint 155 §3 — folders as CARDS, in the pricing page's visual
 * language.
 *
 * The owner's ask was literally "make the documents page beautiful the
 * same way you made the pricing page beautiful". Sprint 154 §L.2 gave the
 * pricing categories big cards with the count promoted to a display
 * figure and a dashed "+" tile closing the grid; this is that same grid,
 * for folders.
 *
 * It REUSES `.pricing-category-*` rather than cloning it, with a
 * `.doc-folder-card` modifier for the two things that genuinely differ
 * (a folder icon, and a system-folder marker). A second, independently
 * maintained copy of the same visual rule is exactly what drifts —
 * CLAUDE.md's frontend rule, and Sprint 126's headerless permission
 * column is the standing example of what that costs.
 *
 * The tree in the sidebar is untouched and still owns drag-and-drop and
 * deep navigation; this grid is the "where am I, what is in here" view
 * that the page was missing. Access gating is entirely upstream in
 * `documentsAccess.ts` and is not touched — this is a visual change.
 */
import { Folder, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { BoundedList } from "../BoundedList";
import type { DocumentFolder } from "../../api/types";

export function DocumentsFolderGrid({
  folders,
  onOpen,
  onCreate,
}: {
  /** The folders at the CURRENT level only — the caller filters. */
  folders: DocumentFolder[];
  onOpen: (folder: DocumentFolder) => void;
  /** Opens the existing create-folder flow. Null hides the "+" card. */
  onCreate: (() => void) | null;
}) {
  const { t } = useTranslation("common");

  const grid = (
    <div className="pricing-category-grid" data-testid="doc-folder-cards">
      {folders.map((folder) => (
          <button
            key={folder.id}
            type="button"
            className="pricing-category-card doc-folder-card"
            onClick={() => onOpen(folder)}
            data-testid={`doc-folder-card-${folder.id}`}
          >
            <span className="pricing-category-card-name">
              <Folder
                size={16}
                strokeWidth={2}
                className="doc-folder-card-icon"
                aria-hidden="true"
              />
              {folder.name}
              {folder.is_system && (
                <Lock
                  size={12}
                  strokeWidth={2}
                  className="doc-folder-card-lock"
                  aria-label={t("documents.system_folder")}
                />
              )}
            </span>
            <span className="pricing-category-card-count">
              {folder.file_count}
            </span>
            <span className="pricing-category-card-count-label">
              {t("documents.file_count_label", { count: folder.file_count })}
            </span>
          </button>
        ))}

        {onCreate && (
          <button
            type="button"
            className="pricing-category-card pricing-category-card-add"
            onClick={onCreate}
            data-testid="doc-folder-card-add"
          >
            <span className="pricing-category-card-add-plus" aria-hidden="true">
              +
            </span>
            <span>{t("documents.new_folder")}</span>
          </button>
        )}
    </div>
  );

  // An empty level renders the grid DIRECTLY: `BoundedList` swaps its
  // children for the empty state at count 0, which would take the "+"
  // card away at precisely the moment it is the only thing worth
  // clicking. Above zero the grid is a SERVER collection and is bounded
  // (CLAUDE.md §8) — a customer with sixty folders scrolls inside the
  // grid rather than growing the page.
  if (folders.length === 0) {
    return (
      <div data-testid="doc-folder-grid-empty">
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("documents.no_subfolders")}
        </p>
        {grid}
      </div>
    );
  }

  return (
    <BoundedList
      size="md"
      count={folders.length}
      ariaLabel={t("documents.folders_label")}
      testIdPrefix="doc-folder-grid"
    >
      {grid}
    </BoundedList>
  );
}
