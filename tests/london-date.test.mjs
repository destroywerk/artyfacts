import assert from "node:assert/strict";
import test from "node:test";

import {
  addOneCalendarMonth,
  calendarDayDifference,
  londonCalendarDates,
  londonDateIso,
  millisecondsUntilLondonDateChange,
} from "../public/london-date.mjs";

test("derives the London date independently of the runtime timezone", () => {
  assert.equal(londonDateIso(new Date("2026-01-15T23:59:59.999Z")), "2026-01-15");
  assert.equal(londonDateIso(new Date("2026-01-16T00:00:00.000Z")), "2026-01-16");

  assert.equal(londonDateIso(new Date("2026-06-15T22:59:59.999Z")), "2026-06-15");
  assert.equal(londonDateIso(new Date("2026-06-15T23:00:00.000Z")), "2026-06-16");
});

test("finds London midnight in GMT and BST", () => {
  assert.equal(
    millisecondsUntilLondonDateChange(new Date("2026-01-15T23:59:30.000Z")),
    30_000,
  );
  assert.equal(
    millisecondsUntilLondonDateChange(new Date("2026-06-15T22:59:30.000Z")),
    30_000,
  );
});

test("handles the short and long London DST days", () => {
  assert.equal(
    millisecondsUntilLondonDateChange(new Date("2026-03-29T00:30:00.000Z")),
    22.5 * 60 * 60 * 1000,
  );
  assert.equal(
    millisecondsUntilLondonDateChange(new Date("2026-10-25T00:30:00.000Z")),
    23.5 * 60 * 60 * 1000,
  );
});

test("uses a clamped one-calendar-month navigation horizon", () => {
  assert.equal(addOneCalendarMonth("2026-01-31"), "2026-02-28");
  assert.equal(addOneCalendarMonth("2028-01-31"), "2028-02-29");
  assert.equal(addOneCalendarMonth("2026-08-31"), "2026-09-30");

  const dates = londonCalendarDates("2026-01-31");
  assert.equal(dates[0], "2026-01-31");
  assert.equal(dates.at(-1), "2026-02-28");
  assert.equal(dates.length, 29);
  assert.equal(calendarDayDifference(dates[0], dates.at(-1)), 28);
});
