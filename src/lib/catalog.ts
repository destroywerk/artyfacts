import { exhibitions } from "../data/exhibitions";
import { venues } from "../data/venues";
import type { ExhibitionWithVenue } from "../types";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

export function asUtcDate(isoDate: string): Date {
  return new Date(`${isoDate}T12:00:00Z`);
}

function assertCatalogIntegrity(): void {
  const venueIds = new Set<string>();
  const exhibitionIds = new Set<string>();

  for (const venue of venues) {
    if (venueIds.has(venue.id)) throw new Error(`Duplicate venue id: ${venue.id}`);
    venueIds.add(venue.id);

    if (venue.scrapeMethod !== "link-only" && !venue.whatsOnUrl) {
      throw new Error(`Scrapeable venue has no what's-on URL: ${venue.id}`);
    }
  }

  for (const exhibition of exhibitions) {
    if (exhibitionIds.has(exhibition.id)) {
      throw new Error(`Duplicate exhibition id: ${exhibition.id}`);
    }
    exhibitionIds.add(exhibition.id);

    if (!venueIds.has(exhibition.venueId)) {
      throw new Error(`Unknown venue "${exhibition.venueId}" on ${exhibition.id}`);
    }
    if (!ISO_DATE.test(exhibition.startDate) || !ISO_DATE.test(exhibition.endDate)) {
      throw new Error(`Invalid date format on ${exhibition.id}`);
    }
    if (exhibition.endDate < exhibition.startDate) {
      throw new Error(`End date precedes start date on ${exhibition.id}`);
    }
    if (exhibition.confidenceScore < 0 || exhibition.confidenceScore > 1) {
      throw new Error(`Invalid confidence score on ${exhibition.id}`);
    }
  }
}

assertCatalogIntegrity();

const venueById = new Map(venues.map((venue) => [venue.id, venue]));

export const catalog: ExhibitionWithVenue[] = exhibitions
  .map((exhibition) => {
    const venue = venueById.get(exhibition.venueId);
    if (!venue) throw new Error(`Unknown venue: ${exhibition.venueId}`);
    return { ...exhibition, venue };
  })
  .sort((a, b) => a.startDate.localeCompare(b.startDate) || a.title.localeCompare(b.title));

export function getFortnightCatalog(today: Date): ExhibitionWithVenue[] {
  const start = toIsoDate(today);
  const end = toIsoDate(addDays(today, 13));
  return catalog.filter(
    (exhibition) => exhibition.startDate <= end && exhibition.endDate >= start,
  );
}
