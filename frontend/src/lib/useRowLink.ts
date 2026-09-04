/**
 * P-13 D (O3, §D.22 rule 9) — the ONE row-link hook. Returns the
 * props that make any table row a whole-row link: pointer + focus
 * semantics, Enter/Space activation, and the inner-control guard (a
 * click that starts on a nested link/button/input belongs to that
 * control, not the row). `ClickableRow` packages this for the common
 * `<tr>` case; hand-rolled copies (Contracts, Dashboard) fold onto it.
 */
import type { KeyboardEvent, MouseEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ROW_INNER_CONTROL_SELECTOR } from "./rowLink";

export interface RowLinkOptions {
  to?: string;
  onActivate?: () => void;
  /** Render as a plain non-interactive row. Default false. */
  inert?: boolean;
  ariaLabel?: string;
}

export interface RowLinkProps {
  role?: "link";
  tabIndex?: number;
  "aria-label"?: string;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
}

export function useRowLink({
  to,
  onActivate,
  inert = false,
  ariaLabel,
}: RowLinkOptions): { interactive: boolean; rowProps: RowLinkProps } {
  const navigate = useNavigate();

  const interactive = !inert && (Boolean(to) || Boolean(onActivate));
  if (!interactive) {
    return { interactive, rowProps: {} };
  }

  const activate = () => {
    if (onActivate) {
      onActivate();
    } else if (to) {
      navigate(to);
    }
  };

  return {
    interactive,
    rowProps: {
      role: "link",
      tabIndex: 0,
      "aria-label": ariaLabel,
      onClick: (event) => {
        if (event.target instanceof HTMLElement) {
          const inner = event.target.closest(ROW_INNER_CONTROL_SELECTOR);
          if (inner && inner !== event.currentTarget) {
            return;
          }
        }
        activate();
      },
      onKeyDown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      },
    },
  };
}
