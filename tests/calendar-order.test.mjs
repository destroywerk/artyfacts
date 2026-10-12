import assert from "node:assert/strict";
import test from "node:test";

import {
  compareCalendarOccurrences,
  occurrenceGroupDate,
  occurrenceKindRank,
} from "../public/calendar-order.mjs";

const occurrence = (overrides) => ({
  id: "event",
  kind: "run",
  startDate: "2026-10-01",
  priorityRank: 20,
  title: "Example",
  catalogIndex: 0,
  ...overrides,
});

test("orders a day by PV, opening, carry-over, then venue priority", () => {
  const rangeStart = "2026-10-12";
  const values = [
    occurrence({ id: "carry", priorityRank: 1 }),
    occurrence({ id: "opening-low", startDate: rangeStart, priorityRank: 20 }),
    occurrence({ id: "pv", kind: "private-view", startDate: rangeStart, priorityRank: 50 }),
    occurrence({ id: "opening-high", startDate: rangeStart, priorityRank: 2 }),
  ];

  values.sort((a, b) => compareCalendarOccurrences(a, b, rangeStart));

  assert.deepEqual(
    values.map(({ id }) => id),
    ["pv", "opening-high", "opening-low", "carry"],
  );
});

test("groups later openings and private views at their actual dates", () => {
  const rangeStart = "2026-10-12";
  const laterOpening = occurrence({ startDate: "2026-10-14" });
  const laterPrivateView = occurrence({
    kind: "private-view",
    startDate: "2026-10-13",
  });

  assert.equal(occurrenceGroupDate(laterOpening, rangeStart), "2026-10-14");
  assert.equal(occurrenceGroupDate(laterPrivateView, rangeStart), "2026-10-13");
  assert.equal(occurrenceKindRank(laterPrivateView, "2026-10-13"), 0);
});

test("ascends later day groups and keeps private views before openings", () => {
  const rangeStart = "2026-10-12";
  const values = [
    occurrence({ id: "later-opening", startDate: "2026-10-15" }),
    occurrence({ id: "later-pv", kind: "private-view", startDate: "2026-10-14" }),
    occurrence({ id: "earlier-opening", startDate: "2026-10-13" }),
    occurrence({ id: "same-day-opening", startDate: "2026-10-14" }),
  ];

  values.sort((a, b) => compareCalendarOccurrences(a, b, rangeStart));

  assert.deepEqual(values.map(({ id }) => id), [
    "earlier-opening",
    "later-pv",
    "same-day-opening",
    "later-opening",
  ]);
});

test("orders carry-over exhibitions by most recent opening first", () => {
  const rangeStart = "2026-10-12";
  const values = [
    occurrence({ id: "old", startDate: "2026-02-01", priorityRank: 1 }),
    occurrence({ id: "recent", startDate: "2026-10-10", priorityRank: 50 }),
  ];

  values.sort((a, b) => compareCalendarOccurrences(a, b, rangeStart));
  assert.deepEqual(values.map(({ id }) => id), ["recent", "old"]);
});

test("uses stable title and id tiebreakers", () => {
  const rangeStart = "2026-10-12";
  const values = [
    occurrence({ id: "b", startDate: rangeStart, title: "Same" }),
    occurrence({ id: "a", startDate: rangeStart, title: "Same" }),
    occurrence({ id: "z", startDate: rangeStart, title: "Alpha" }),
  ];

  values.sort((a, b) => compareCalendarOccurrences(a, b, rangeStart));
  assert.deepEqual(values.map(({ id }) => id), ["z", "a", "b"]);
});
