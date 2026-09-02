/**
 * P-12 §D.24 rule 3 — the road: tabs are the steps of a workflow, in
 * the order things happen, numbered. This module is the pure half of
 * `RoadTabs`: the numbering and the progress-state derivation, kept
 * out of the component so vitest can pin them (the unit harness runs
 * node-env and renders nothing).
 */

/** "1 · Finished work" — the numbered eyebrow over a step. */
export function stepEyebrow(indexZeroBased: number, word: string): string {
  return `${indexZeroBased + 1} · ${word}`;
}

export type RoadStepState = "done" | "current" | "ahead";

/**
 * For the read-only road on a detail page (variant "progress"): every
 * step before the current one is done, the current one is current,
 * everything after is ahead. A key that is not on the road marks the
 * whole road "ahead" — an unknown state must never look finished.
 */
export function roadStepStates<K extends string>(
  keys: readonly K[],
  currentKey: K | null | undefined,
): RoadStepState[] {
  const at = currentKey == null ? -1 : keys.indexOf(currentKey);
  return keys.map((_, i) => {
    if (at === -1) return "ahead";
    if (i < at) return "done";
    if (i === at) return "current";
    return "ahead";
  });
}
