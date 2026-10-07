# Open in London

A mobile-first, static guide to exhibitions open in London over the next
fortnight. The first local slice uses a horizontal fourteen-day calendar:
each exhibition runs across its open dates and opens a full detail view. It
also includes area and institution filters, a free-entry filter, venue source
links, hover previews, and shareable filter URLs.

## Run locally

```sh
npm install
npm run dev
```

Then open `http://localhost:4321`.

## Checks

```sh
npm run check
npm run build
```

## Data

- `src/data/venues.ts` contains the initial ten-venue extraction pilot.
- `src/data/exhibitions.ts` contains venue-sourced records verified on
  6 October 2026.
- `src/lib/catalog.ts` validates required fields and rejects broken records
  during the build.

The current remote images are source-site fallbacks. Local cached thumbnails,
the nightly extraction workflow, monitoring, and route planner are later PRD
phases.
