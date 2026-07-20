// #108 Part D — THE platform toggle for boolean state.
//
// Platform rule (owner review round 2, 2026-06-28): toggles represent
// boolean STATE (settings, flags, filters); checkboxes are reserved
// for SELECTION (rows in a multi-select, styled via .checkbox-input).
// This component wraps the existing .toggle-switch styles (Settings
// page) so every boolean control renders identically. It is a plain
// controlled input — render it inside (or next to) a <label> carrying
// the caption text; pass `id` to pair with a <label htmlFor>.
import type { ChangeEventHandler } from "react";

interface ToggleProps {
  checked: boolean;
  onChange: ChangeEventHandler<HTMLInputElement>;
  disabled?: boolean;
  id?: string;
  className?: string;
  title?: string;
  "data-testid"?: string;
  "data-module"?: string;
  "data-policy-field"?: string;
  "data-user-id"?: number;
  "data-building-id"?: number;
  "aria-label"?: string;
}

export function Toggle({
  checked,
  onChange,
  disabled,
  id,
  className,
  title,
  ...rest
}: ToggleProps) {
  return (
    <span
      className={className ? `toggle-switch ${className}` : "toggle-switch"}
      title={title}
    >
      <input
        type="checkbox"
        id={id}
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        {...rest}
      />
      <span className="toggle-switch-slider" />
    </span>
  );
}
