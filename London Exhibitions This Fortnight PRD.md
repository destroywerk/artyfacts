# London Exhibitions This Fortnight: PRD

Oct 6, 2026 · @Tim

## Summary and goals

This is a mobile and desktop web page that shows every exhibition open in London this week and next, with a preview image, filtered by area and by institution. The data collects itself. Nobody edits a list by hand once it is running.

**Goals**

- Show what is on in the next 14 days in one glance.
- Cover the major museums and the smaller galleries.
- Update itself every day with no manual work.
- Load fast on a phone.

**How we will know it works**

- At least 90% of exhibitions on a spot-checked sample of venues appear with correct dates.
- The page has not needed a manual data fix for four weeks in a row.
- It loads in under two seconds on a mid-range phone.

## Users and scope

Version 1 is for me and a few friends, so there are no accounts, no payments and no public launch.

**In scope**

- Temporary and ongoing exhibitions at London venues, big and small, including commercial galleries.
- A rolling window: today to the end of next week.
- Filters for area and institution.
- Works on phones and desktop browsers.

**Out of scope for now**

- Ticket sales, bookings or reviews.
- Talks, workshops, late openings and other events.
- Permanent collections.
- Anywhere outside Greater London.
- Notifications and saved favourites.

## Features

The page has one job: show what is open soon, and let me narrow it fast. Exhibitions run for weeks, so a plain day grid would repeat each one many times. The calendar draws each show as a bar across the days it runs.

| Feature | What it does |
| --- | --- |
| Two-week calendar | A 14-day strip starting today. Each exhibition is a bar across its open days, with a small thumbnail. Desktop only. |
| Card list | Cards grouped as Opening this week, Closing soon and Ongoing. This is the default on mobile. |
| Preview image | One image per exhibition, with the venue's image as a fallback. |
| Area filter | Multi-select chips for parts of London (see the data model). |
| Institution filter | Searchable multi-select across all venues. |
| Free toggle | Shows only free-entry exhibitions. Included in version 1. |
| Day plan export | Tick exhibitions to build a list, then open it in Google Maps as a route, ordered nearest first from a start point you choose. |
| Shareable link | Filters sit in the URL so I can send a filtered view to a friend. |
| Venue link | Every card links to the venue's own page, so dates can be double-checked. |

Where a venue does not state its price clearly, the show is marked "price not found". It stays visible unless the Free toggle is on.

**Day plan export.** The app orders the ticked shows by distance using each venue's coordinates, starting from your location or the first show you pick, and always going to the nearest remaining venue next. It then builds a Google Maps directions link. Google Maps limits how many stops one link can hold (about ten, to be checked when we build it), so longer lists are split into two links. The plan also uses the stored opening hours. It flags any stop where you would arrive after closing, and it can suggest a different order. Treat this as a guide, since bank holidays and special closures are not covered.

## Data model

Two record types are enough: venues and exhibitions. A venue's area is worked out automatically from its postcode, so nobody tags it by hand.

| Record | Fields |
| --- | --- |
| Venue | id, name, type (national, public, commercial, independent), address, postcode, lat/lng, area, website, what's-on URL, opening hours by weekday, hours last checked, scrape method (website, feed, newsletter or link-only), last successful scrape |
| Exhibition | id, venue id, title, start date, end date, short description, image URL, cached thumbnail, source URL, free or paid (if known), confidence score, last verified |

**Areas (draft, to confirm)**

- Central: Soho, Mayfair, Marylebone, Bloomsbury, Strand
- South Bank and Bankside
- South Kensington and West
- City and East: Shoreditch, Whitechapel, Bethnal Green, Hackney
- Stratford and East: Stratford, Leyton, Waltham Forest
- North: Camden, Islington
- South East: Bermondsey, Peckham, Greenwich, Dulwich
- South West and Lambeth

The postcode lookup can use the free postcodes.io service, which returns the borough and ward for any UK postcode.

## Venue list

The venue list starts from your Google Maps list plus a starter list below, you vet it once, and after that discovery runs on its own. Your Maps list came in as screenshots and is merged below.

**Your Maps list (read from screenshots: 55 entries, 53 distinct venues)**

- Pilar Corrias (two entries), Gagosian (two entries, probably separate sites, kept as separate venue records).
- Marked closed on Google Maps: THE TAGLI, Maureen Paley, Barbican Art Gallery, Unit and Union Pacific (all "temporarily closed"), and Flowers Gallery ("place no longer exists"). Re-check these in phase 1, then drop or keep them.
- Three Rooms posts its exhibitions only on Instagram, so it is a link-only venue for now (see Data sourcing and scraping). Rhodes Contemporary Art Gallery is confirmed.
- The list is mostly commercial galleries plus a few major institutions, so the starter list below fills the museum side.
- Full list: The Photographers' Gallery, Pilar Corrias, THE TAGLI, Lisson Gallery, William Hine, Terrace Gallery, Three Rooms, Chisenhale Gallery, Soho Revue, The Cob Gallery, October Gallery, Mimosa House, Ginny on Frederick, Haricot Gallery, Hannah Barry Gallery, Sprüth Magers Gallery, Kristin Hjellegjerde Gallery, Matt's Gallery, Maureen Paley, Flowers Gallery, Kate MacGarry, Hales Gallery, Serpentine South Gallery, Victoria Miro, Tate Britain, Saatchi Gallery, Barbican Art Gallery, Whitechapel Gallery, White Cube Bermondsey, Pippy Houldsworth Gallery, Gagosian, Saatchi Yates, Huxley-Parlour, No.9 Cork Street, John Martin Gallery, Timothy Taylor, Ben Brown Fine Arts, Thaddaeus Ropac, Hayward Gallery, ST.ART Gallery, Sadie Coles HQ, The Redfern Gallery, Unit, David Zwirner, White Cube Mason's Yard, Rhodes Contemporary Art Gallery, The Courtauld Gallery, Maddox Gallery, Pace Gallery, Institute of Contemporary Arts, Royal Academy of Arts, The National Gallery, Union Pacific, LBF Contemporary.

**Starter list to fill the gaps (from memory, unverified, some may have moved or closed; overlaps with your list are merged at build)**

- National and major: British Museum, V&A, V&A East, Tate Modern, Tate Britain, National Gallery, National Portrait Gallery, Royal Academy, Science Museum, Natural History Museum, Barbican, Southbank Centre (Hayward Gallery), Serpentine, Whitechapel Gallery, Design Museum, Saatchi Gallery, Wellcome Collection, Courtauld Gallery, Somerset House, ICA, The Photographers' Gallery, Imperial War Museum, London Museum, Royal Museums Greenwich, Horniman Museum, Dulwich Picture Gallery, Wallace Collection, Royal Collection Trust (King's Gallery), Fashion and Textile Museum, Museum of the Home, Foundling Museum, Sir John Soane's Museum, Jewish Museum London, Estorick Collection, Garden Museum, Newport Street Gallery.
- Non-profit and independent: Camden Art Centre, South London Gallery, Chisenhale Gallery, Gasworks, Studio Voltaire, Zabludowicz Collection, Raven Row, Cubitt, Delfina Foundation, Pump House Gallery, Goldsmiths CCA, Peckham Platform, Matt's Gallery, Auto Italia.
- Commercial: White Cube, Gagosian, Hauser & Wirth, Lisson Gallery, David Zwirner, Pace, Victoria Miro, Sadie Coles HQ, Thaddaeus Ropac, Marian Goodman, Stephen Friedman, Maureen Paley, Herald St, Timothy Taylor, Annely Juda.

**Keeping it complete without manual work**

A monthly job searches for new venues using Google Places and OpenStreetMap (museums and galleries inside Greater London). New finds go in as unreviewed. They are shown on the site only if the extraction looks reliable, and I can prune them later in one pass.

## Data sourcing and scraping

We read each venue's own "what's on" page with one generic method, not a hand-written scraper per site. That is what makes 100+ venues manageable with no upkeep. Each venue is tried through three sources, best first.

1. **Structured data.** Many sites publish schema.org event data (JSON-LD), an RSS feed, a sitemap or an iCal file. If present, we read that directly. It is free and exact.
2. **Page text plus an AI extractor.** We fetch the what's-on page, and use a headless browser (Playwright) when the page needs JavaScript. A small, cheap Claude model reads the text and returns a fixed JSON shape: title, start, end, image, link and whether entry is free. This covers most venues.
3. **Aggregators as a cross-check only.** Listing sites can confirm dates, but their terms are stricter and they go stale, so they never replace the venue's own page.

**Images.** Take the page's main image for each exhibition (usually the Open Graph image on the exhibition page). Save a small resized copy to our own storage so cards do not break if the venue changes a link.

**Opening hours.** Collect each venue's weekly opening hours once, store them on the venue record, and refresh them every three months. The same extractor reads the hours from the venue's own visit or opening times page, so no new tooling is needed. Google Places can supply hours as a cross-check or fallback, but its terms limit how long its data may be stored, so it should not be the stored source. Hours do not cover bank holidays, Christmas closures or one-off late openings, so the site shows "hours checked" with a date and a note to confirm on the venue's page.

**Venues that only post on Instagram.** Some venues, such as Three Rooms, publish their shows only on Instagram. Instagram blocks automated reading and its terms forbid it, so we will not scrape it. These venues are marked link-only. They appear in the institution filter and on the site with a link to their Instagram, but without dates. A later option is to subscribe a dedicated inbox to a venue's mailing list, if it has one, and have the same extractor read the newsletters.

**Cleaning the results**

- Reject items with no dates, an end before the start, or dates more than two years away.
- Merge duplicates by venue, normalised title and start date.
- Give each item a confidence score. Low scores show a "check venue site" note.
- Skip the AI call when a page's content hash has not changed since the last run.

## Auto-update and monitoring

A scheduled job runs every night, refreshes all venues, and republishes the site. No server is needed.

**Schedule**

- Nightly (about 4am London time): re-check every venue's what's-on page.
- Weekly: re-crawl deeper pages for venues that list shows on separate pages.
- Monthly: run venue discovery for new galleries. Every three months: refresh each venue's opening hours.

**Failure handling**

- Retry a failed fetch twice, then keep yesterday's data for that venue.
- If a venue that normally returns shows returns none for three runs in a row, send me an alert by email.
- A simple status page lists each venue with its last success and number of shows found.
- If a site blocks us with bot protection, we do not try to get around it. The venue is marked as link-only and shown with a pointer to its site.

**Good manners**

- Obey robots.txt.
- One request every few seconds per site, and only a handful of pages per venue per night.
- A clear user agent with a contact address.
- Cache pages and skip unchanged ones.

## UI design

Design for the phone first, then widen it for desktop. The filters are always one tap away and the cards carry the page.

**Mobile**

- Top bar: This week and Next week toggle, plus a Filters button.
- Filters open as a bottom sheet with Area chips and a searchable Institution list.
- Cards stack in one column: image on top, then title, venue, area, and dates. A "Closing in 3 days" tag appears when it applies.

**Desktop**

- Filters sit in a left sidebar.
- A switch toggles between the card grid and the 14-day bar calendar.
- Hovering a bar in the calendar shows the card.

**States to design**

- No results for the chosen filters (offer to clear them).
- A venue that could not be refreshed (show the last known data with a small "last checked" note).
- Missing image (venue image, then a neutral placeholder).

## Tech stack and hosting

Use a static site rebuilt every night by a scheduled job. There is no database and no server to maintain, and it should cost very little to run.

| Layer | Choice | Why |
| --- | --- | --- |
| Scheduler | GitHub Actions cron | Free for this volume. Runs the scrape, then triggers a rebuild. |
| Fetching | Plain HTTP, plus Playwright for JavaScript-heavy pages | Fast for most sites, full browser only when needed. |
| Extraction | Claude Haiku-tier model with a fixed JSON schema | Cheap and handles very different page layouts. |
| Storage | One exhibitions.json file in the repo, plus images in object storage | Simple, easy to inspect, easy to roll back. |
| Site | Astro or Next.js, static output | Fast on phones, easy to filter in the browser. |
| Hosting | Cloudflare Pages or Vercel | Free tier is enough for me and friends. |
| Alerts | Email from the scheduled job | Tells me when a venue breaks. |

**Rough cost (an estimate, to be checked on the first week of real runs):** a few pounds a month for AI calls, since most pages are skipped when unchanged. Everything else fits free tiers.

## Risks and mitigations

The biggest risk is wrong dates, because the AI extractor can misread a page. The rest are manageable.

| Risk | Mitigation |
| --- | --- |
| Wrong or missing dates | Validation rules, confidence scores, and a link to the venue's page on every card. |
| Site layout changes | Generic extraction survives most redesigns. Alerts catch the rest. |
| Bot protection blocks us | Do not bypass it. Mark the venue link-only. |
| Image rights | Keep the site private to me and friends. Cache small thumbnails only, and always credit and link the venue. |
| Venue closes or moves | Monthly discovery plus the zero-results alert. |
| AI cost creeping up | Hash check skips unchanged pages. Cap the daily number of calls. |
| Page layouts the extractor cannot parse | Fall back to the venue's calendar or iCal feed if one exists. |

## Build phases and open questions

Build in five steps. Each one has a check that must pass before the next starts.

1. **Venue list.** Merge your Maps list with the starter list and vet it. Check: every venue has a what's-on URL, a postcode and opening hours.
2. **Extraction on 10 venues.** Mix of big, small and commercial. Check: at least 90% of shows are correct when I hand-check them.
3. **Site v0.** Card list, week toggle, area, institution and free-entry filters, on real data. Check: usable on my phone.
4. **All venues plus monitoring.** Nightly job, alerts and the status page. Check: a full week of runs without manual fixes.
5. **Auto-discovery and polish.** Monthly new-venue search, the desktop bar calendar, day plan export to Google Maps, thumbnail caching.

**Open questions**

- Did the screenshots cover your whole Maps list, or did I miss rows between them? You said many venues are missing from it, so the starter list and discovery will fill the gaps.
- Are the eight draft areas right, or do you prefer your own groupings?
- Should the desktop default be the bar calendar or the card grid?
- Do you want commercial galleries mixed in with museums, or a switch to hide them?
