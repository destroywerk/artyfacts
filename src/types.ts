export const AREAS = [
  "Central",
  "South Bank & Bankside",
  "South Kensington & West",
  "City & East",
  "Stratford & East",
  "North",
  "South East",
  "South West & Lambeth",
] as const;

export type Area = (typeof AREAS)[number];
export type VenueType = "national" | "public" | "commercial" | "independent";
export type ScrapeMethod = "website" | "feed" | "newsletter" | "link-only";
export type PriceStatus = "free" | "paid" | "unknown";

export interface DayHours {
  open: string;
  close: string;
}

export type WeeklyHours = Partial<
  Record<
    | "monday"
    | "tuesday"
    | "wednesday"
    | "thursday"
    | "friday"
    | "saturday"
    | "sunday",
    DayHours
  >
>;

export interface Venue {
  id: string;
  name: string;
  type: VenueType;
  address: string | null;
  postcode: string | null;
  coordinates: {
    lat: number;
    lng: number;
  } | null;
  area: Area | null;
  website: string | null;
  whatsOnUrl: string | null;
  instagramUrl?: string | null;
  openingHours: WeeklyHours | null;
  hoursLastChecked: string | null;
  scrapeMethod: ScrapeMethod;
  lastSuccessfulScrape: string | null;
  priorityRank?: number | null;
}

export interface Exhibition {
  id: string;
  venueId: string;
  title: string;
  startDate: string;
  endDate: string;
  shortDescription: string;
  imageUrl: string | null;
  cachedThumbnail: string | null;
  imageAlt?: string;
  sourceUrl: string;
  priceStatus: PriceStatus;
  confidenceScore: number;
  lastVerified: string;
  imagePosition?: string;
  accent: string;
}

export interface ExhibitionWithVenue extends Exhibition {
  venue: Venue;
}
