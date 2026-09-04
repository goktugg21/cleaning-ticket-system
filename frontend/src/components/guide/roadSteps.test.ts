import { describe, expect, it } from "vitest";

import { roadStepStates, stepEyebrow } from "./roadSteps";

describe("stepEyebrow", () => {
  it("numbers from one", () => {
    expect(stepEyebrow(0, "Finished work")).toBe("1 · Finished work");
    expect(stepEyebrow(3, "With the customer")).toBe("4 · With the customer");
  });
});

describe("roadStepStates", () => {
  const road = ["draft", "active", "ending", "ended"] as const;

  it("splits the road at the current step", () => {
    expect(roadStepStates(road, "ending")).toEqual([
      "done",
      "done",
      "current",
      "ahead",
    ]);
  });

  it("first step current means nothing is done", () => {
    expect(roadStepStates(road, "draft")).toEqual([
      "current",
      "ahead",
      "ahead",
      "ahead",
    ]);
  });

  it("an unknown or missing state marks nothing done", () => {
    expect(roadStepStates(road, "cancelled" as never)).toEqual([
      "ahead",
      "ahead",
      "ahead",
      "ahead",
    ]);
    expect(roadStepStates(road, null)).toEqual([
      "ahead",
      "ahead",
      "ahead",
      "ahead",
    ]);
  });
});
