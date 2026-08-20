/**
 * Sprint 159 §3 — ONE status filter design, on both work lists.
 *
 * Sprint 158 gave Extra Work and Tickets the same default (open on what
 * has not been actioned) but two different-looking controls: Extra Work
 * read as a row of tiles with counts, Tickets as a chip row with no
 * numbers plus a sentence of prose underneath saying a filter was on.
 * The owner found the tickets version odd and the pair inconsistent,
 * and told us which way to unify: *ticketi ew gibi yapabilirsin.*
 *
 * So: the tile IS the filter, it carries its own count, the active one
 * is visibly selected, and clearing is a control rather than a sentence
 * — the "All" tile, plus an × on the active tile. The Sprint 158 prose
 * notice is gone; it existed because the chip row alone did not make
 * the active filter obvious enough, and a tile that is filled and
 * outlined does.
 *
 * ## Counts
 *
 * `count: -1` means "this list cannot know" and renders NO number. That
 * is not a placeholder, it is the honest answer for a server-paginated
 * list whose client holds one page: a tile reading "3" when the status
 * holds ninety is a number an operator would act on. Where the caller
 * has a SERVER-side breakdown it passes real numbers; where it has only
 * a page, it passes -1 rather than a lie.
 *
 * W8 BUG 2 — `showCounts={false}` drops the numbers from the WHOLE row.
 *
 * Per-tile `-1` was right for one tile that cannot be known beside
 * others that can. It was wrong for the case the ticket list actually
 * hits, where the count source cannot follow the filter at all: every
 * tile fell back to an em dash except "All", which kept a number from a
 * different source. One figure among eight dashes reads as eight empty
 * buckets, and no arrangement of dashes says why. A row with no numbers
 * is a filter, which is the other thing this row has always been, and it
 * needs no explaining.
 */
import { useTranslation } from "react-i18next";

export interface StatusTile {
  value: string;
  label: string;
  /** -1 = unknown; renders no number. */
  count: number;
}

export function StatusTiles({
  tiles,
  active,
  onChange,
  totalCount,
  testIdPrefix,
  showCounts = true,
}: {
  tiles: StatusTile[];
  /** "" is the all-statuses tile. */
  active: string;
  onChange: (value: string) => void;
  /** How many rows exist in total, for the "All" tile. -1 hides it. */
  totalCount: number;
  testIdPrefix: string;
  /** False = this row is a filter and nothing else. No tile shows a
   *  number, including "All". */
  showCounts?: boolean;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="status-tile-row" data-testid={`${testIdPrefix}-tiles`}>
      <button
        type="button"
        className={
          active === "" ? "status-tile status-tile-active" : "status-tile"
        }
        aria-pressed={active === ""}
        onClick={() => onChange("")}
        data-testid={`${testIdPrefix}-tile-all`}
      >
        <span className="status-tile-label">{t("status_chips.all")}</span>
        {showCounts && (
          <span className="status-tile-count">
            {totalCount >= 0 ? totalCount : "—"}
          </span>
        )}
      </button>
      {tiles.map((tile) => {
        const isActive = tile.value === active;
        return (
          <button
            key={tile.value}
            type="button"
            className={
              isActive ? "status-tile status-tile-active" : "status-tile"
            }
            aria-pressed={isActive}
            // The active tile clears; every other tile selects. One
            // control, and the × says which of the two this click is.
            onClick={() => onChange(isActive ? "" : tile.value)}
            data-testid={`${testIdPrefix}-tile-${tile.value}`}
          >
            <span className="status-tile-label">
              {tile.label}
              {isActive && (
                <span className="status-tile-clear" aria-hidden="true">
                  ×
                </span>
              )}
            </span>
            {showCounts && (
              <span className="status-tile-count">
                {tile.count >= 0 ? tile.count : "—"}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
