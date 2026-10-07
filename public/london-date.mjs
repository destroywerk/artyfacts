const LONDON_TIME_ZONE = "Europe/London";
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;

const londonDateFormatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: LONDON_TIME_ZONE,
  calendar: "gregory",
  numberingSystem: "latn",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function isoParts(isoDate) {
  if (!ISO_DATE_PATTERN.test(isoDate)) {
    throw new TypeError(`Invalid ISO calendar date: ${isoDate}`);
  }
  const [year, month, day] = isoDate.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    throw new TypeError(`Invalid ISO calendar date: ${isoDate}`);
  }
  return { year, month, day };
}

function toIsoDate(year, month, day) {
  return [
    String(year).padStart(4, "0"),
    String(month).padStart(2, "0"),
    String(day).padStart(2, "0"),
  ].join("-");
}

export function isIsoDate(isoDate) {
  try {
    isoParts(isoDate);
    return true;
  } catch {
    return false;
  }
}

export function londonDateIso(instant = new Date()) {
  const parts = Object.fromEntries(
    londonDateFormatter
      .formatToParts(instant)
      .filter(({ type }) => type !== "literal")
      .map(({ type, value }) => [type, value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function addIsoDays(isoDate, days) {
  const { year, month, day } = isoParts(isoDate);
  const date = new Date(Date.UTC(year, month - 1, day + days, 12));
  return toIsoDate(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
}

export function addOneCalendarMonth(isoDate) {
  const { year, month, day } = isoParts(isoDate);
  const nextMonthIndex = month;
  const nextYear = year + Math.floor(nextMonthIndex / 12);
  const normalizedMonthIndex = nextMonthIndex % 12;
  const lastDay = new Date(Date.UTC(nextYear, normalizedMonthIndex + 1, 0, 12)).getUTCDate();
  return toIsoDate(nextYear, normalizedMonthIndex + 1, Math.min(day, lastDay));
}

export function calendarDayDifference(fromIsoDate, toIsoDate) {
  const from = isoParts(fromIsoDate);
  const to = isoParts(toIsoDate);
  const fromTime = Date.UTC(from.year, from.month - 1, from.day, 12);
  const toTime = Date.UTC(to.year, to.month - 1, to.day, 12);
  return Math.round((toTime - fromTime) / DAY_MS);
}

export function londonCalendarDates(todayIso) {
  const endIso = addOneCalendarMonth(todayIso);
  const dayCount = calendarDayDifference(todayIso, endIso) + 1;
  return Array.from({ length: dayCount }, (_, index) => addIsoDays(todayIso, index));
}

export function millisecondsUntilLondonDateChange(instant = new Date()) {
  const startMs = instant.getTime();
  const currentDate = londonDateIso(instant);
  let lower = startMs + 1;
  let upper = startMs + 27 * 60 * 60 * 1000;

  while (londonDateIso(new Date(upper)) === currentDate) {
    upper += 27 * 60 * 60 * 1000;
  }

  while (lower < upper) {
    const middle = lower + Math.floor((upper - lower) / 2);
    if (londonDateIso(new Date(middle)) === currentDate) {
      lower = middle + 1;
    } else {
      upper = middle;
    }
  }

  return lower - startMs;
}
