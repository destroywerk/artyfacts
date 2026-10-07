# Exhibition ingestion data

`venue-seed.json` is the deduplicated source registry assembled from the PRD.
Priority-list institutions are ordered first. Aliases are merged, while
explicitly distinct physical sites such as Gagosian and White Cube locations
remain separate. `venue-overrides.json` contains venue-sourced metadata that
should survive regeneration.

Run the structured-data-first crawler and validator with:

```sh
python3 scripts/ingest.py
python3 scripts/validate_data.py
```

The crawler uses only the Python standard library. It checks `robots.txt`,
sends an identifying user agent, rate-limits each host, retries only transient
failures, and prefers JSON-LD, RSS/Atom, iCal, and sitemaps. It never requests
Instagram and does not attempt to solve or bypass bot-protection challenges.

Generated files:

- `venues.json`: every normalized venue record, with `null` for facts that have
  not been verified.
- `exhibitions.json`: accepted exhibitions overlapping the 14-day window.
- `coverage.json` and `coverage.csv`: one result per venue, including status,
  last success, extraction method, errors, and show count.
- `location-audit.json`: London-location evidence and status for every venue.
- `rejections.json`: rejected exhibition candidates with machine-readable
  reason codes and supporting evidence.
- `run-summary.json`: machine-readable counts, window dates, and priority gaps.
- `src/data/venues.ts`: only venues with accepted current London exhibitions.
- `src/data/exhibitions.ts`: accepted London-only exhibitions consumed by the
  site.

Venue activation requires an official address or postcode that resolves to
London. Multi-location galleries require exhibition evidence tied explicitly
to their London branch. Foreign or location-ambiguous candidates are rejected
rather than inferred from the venue record.

Coverage status is intentionally conservative. A reachable page with no
extractable dated exhibition structure is `unverified`, not a successful
zero-show scrape. `blocked`, `failed`, `ambiguous`, `closed`, and
`instagram-only` sources remain in the full venue and coverage outputs as
link-only records.

No accuracy percentage is calculated. Accuracy requires a separate, documented
spot-check sample against official venue pages.
