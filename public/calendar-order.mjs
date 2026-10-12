export function occurrenceGroupDate(occurrence, rangeStart) {
  if (occurrence.kind === "private-view") return occurrence.startDate;
  return occurrence.startDate > rangeStart ? occurrence.startDate : rangeStart;
}

export function occurrenceKindRank(occurrence, groupDate) {
  if (occurrence.kind === "private-view") return 0;
  if (occurrence.startDate === groupDate) return 1;
  return 2;
}

export function compareCalendarOccurrences(a, b, rangeStart) {
  const aGroup = occurrenceGroupDate(a, rangeStart);
  const bGroup = occurrenceGroupDate(b, rangeStart);
  const groupDifference = aGroup.localeCompare(bGroup);
  if (groupDifference) return groupDifference;

  const aKindRank = occurrenceKindRank(a, aGroup);
  const bKindRank = occurrenceKindRank(b, bGroup);
  const kindDifference = aKindRank - bKindRank;
  if (kindDifference) return kindDifference;

  if (aKindRank === 2 && a.startDate !== b.startDate) {
    return b.startDate.localeCompare(a.startDate);
  }

  const aPriority = a.priorityRank != null && Number.isFinite(Number(a.priorityRank))
    ? Number(a.priorityRank)
    : Number.POSITIVE_INFINITY;
  const bPriority = b.priorityRank != null && Number.isFinite(Number(b.priorityRank))
    ? Number(b.priorityRank)
    : Number.POSITIVE_INFINITY;
  if (aPriority !== bPriority) return aPriority < bPriority ? -1 : 1;

  const titleDifference = String(a.title).localeCompare(String(b.title));
  if (titleDifference) return titleDifference;
  const idDifference = String(a.id).localeCompare(String(b.id));
  if (idDifference) return idDifference;
  return Number(a.catalogIndex ?? 0) - Number(b.catalogIndex ?? 0);
}
