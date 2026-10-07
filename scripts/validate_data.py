#!/usr/bin/env python3
"""Validate generated venue, exhibition, and coverage data."""

from __future__ import annotations

import calendar
import json
import re
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
AREAS = {
    "Central",
    "South Bank & Bankside",
    "South Kensington & West",
    "City & East",
    "Stratford & East",
    "North",
    "South East",
    "South West & Lambeth",
}
VENUE_TYPES = {"national", "public", "commercial", "independent"}
SCRAPE_METHODS = {"website", "feed", "newsletter", "link-only"}
PRICE_STATUSES = {"free", "paid", "unknown"}
BRANCH_SOURCE_PREFIXES = {
    "tate-britain": "/whats-on/tate-britain/",
    "tate-modern": "/whats-on/tate-modern/",
}
BRANCH_TOKENS = {
    "tate-britain": ("tate britain",),
    "tate-modern": ("tate modern",),
    "white-cube-bermondsey": ("bermondsey",),
    "white-cube-masons-yard": ("mason",),
    "gagosian-britannia-street": ("britannia",),
    "gagosian-grosvenor-hill": ("grosvenor",),
    "serpentine-south": ("serpentine south", "south gallery"),
    "vam": ("south kensington", "cromwell"),
    "vam-east": ("v&a east", "vam east", "stratford", "east bank", "storehouse"),
    "young-vam": ("young v&a", "young va", "bethnal green", "cambridge heath"),
}
BRANCH_CONFLICT_TOKENS = {
    "tate-britain": ("tate modern",),
    "tate-modern": ("tate britain",),
    "white-cube-bermondsey": ("mason",),
    "white-cube-masons-yard": ("bermondsey",),
    "gagosian-britannia-street": ("grosvenor",),
    "gagosian-grosvenor-hill": ("britannia",),
    "serpentine-south": ("serpentine north", "north gallery"),
    "vam": ("v&a east", "vam east", "young v&a", "young va", "dundee"),
    "vam-east": ("south kensington", "young v&a", "young va", "dundee"),
    "young-vam": ("south kensington", "v&a east", "vam east", "dundee"),
}
PARENT_TITLE_ALIASES = {
    "tate-britain": ("Tate",),
    "tate-modern": ("Tate",),
    "vam": ("V&A", "Victoria and Albert Museum"),
    "vam-east": ("V&A", "Victoria and Albert Museum"),
    "young-vam": ("V&A", "Victoria and Albert Museum"),
    "white-cube-bermondsey": ("White Cube",),
    "white-cube-masons-yard": ("White Cube",),
    "gagosian-britannia-street": ("Gagosian",),
    "gagosian-grosvenor-hill": ("Gagosian",),
    "serpentine-south": ("Serpentine", "Serpentine Galleries"),
}
COVERAGE_STATUSES = {
    "success",
    "no-current-shows",
    "link-only",
    "blocked",
    "failed",
    "ambiguous",
    "closed",
    "instagram-only",
    "unverified",
    "unresolved",
    "temporarily-closed-unverified",
    "location-closed-unverified",
}
DAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}
POSTCODE_RE = re.compile(
    r"^(?:GIR 0AA|(?:[A-PR-UWYZ][A-HK-Y]?\d[A-Z\d]? "
    r"\d[ABD-HJLNP-UW-Z]{2}))$",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WINDOW_KIND = "calendar-month-inclusive"
GENERIC_LISTING_TITLE_RE = re.compile(
    r"^(?:events?(?:\s+and|\s*&)?\s+exhibitions?\s+calendar|"
    r"exhibitions?\s+calendar|events?\s+calendar|what(?:'|’)?s\s+on|"
    r"events?\s+and\s+exhibitions?|programme|program|visit|"
    r"current\s+exhibitions?|exhibitions?|archive|search(?:\s+results?)?)$",
    re.IGNORECASE,
)
GENERIC_LISTING_PATH_RE = re.compile(
    r"/(?:events?(?:-and-exhibitions)?(?:-calendar)?|"
    r"exhibitions?(?:-calendar)?|what(?:s|-s)-on|programme|program|"
    r"visit|archive|search)/?$",
    re.IGNORECASE,
)
KNOWN_NON_EXHIBITION_TITLE_RE = re.compile(
    r"^(?:club origami|creative tales|halloween mask making|"
    r"wild life drawing:\s*owls)$",
    re.IGNORECASE,
)
GENERIC_DESCRIPTION_RE = re.compile(
    r"^(?:plan your visit|find out what'?s on|welcome to tate|"
    r"tate modern|tate britain|book tickets?|learn more|read more)\.?$",
    re.IGNORECASE,
)


def normalized_label(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def parse_iso(value: Any, field: str, errors: list[str]) -> date | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be an ISO date string")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field} is not a valid ISO date: {value!r}")
        return None


def add_calendar_month(value: date) -> date:
    month_index = value.month
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def valid_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def same_organisation(url_a: str, url_b: str) -> bool:
    host_a = (urllib.parse.urlparse(url_a).hostname or "").lower().removeprefix("www.")
    host_b = (urllib.parse.urlparse(url_b).hostname or "").lower().removeprefix("www.")
    return bool(
        host_a
        and host_b
        and (
            host_a == host_b
            or host_a.endswith("." + host_b)
            or host_b.endswith("." + host_a)
        )
    )


def typescript_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    marker = " = "
    start = text.find(marker)
    if start < 0 or not text.rstrip().endswith(";"):
        raise ValueError(f"{path} is not in generated JSON-compatible form")
    payload = text[start + len(marker) :].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def validate() -> list[str]:
    errors: list[str] = []
    required_paths = [
        DATA_DIR / "venue-seed.json",
        DATA_DIR / "venues.json",
        DATA_DIR / "exhibitions.json",
        DATA_DIR / "coverage.json",
        DATA_DIR / "rejections.json",
        DATA_DIR / "location-audit.json",
        DATA_DIR / "price-overrides.json",
        DATA_DIR / "price-audit.json",
        DATA_DIR / "title-overrides.json",
        DATA_DIR / "title-audit.json",
        DATA_DIR / "description-overrides.json",
        DATA_DIR / "description-audit.json",
        DATA_DIR / "address-audit.json",
        DATA_DIR / "image-audit.json",
        DATA_DIR / "run-summary.json",
        ROOT / "src" / "data" / "venues.ts",
        ROOT / "src" / "data" / "exhibitions.ts",
    ]
    for path in required_paths:
        if not path.exists():
            errors.append(f"Missing required output: {path.relative_to(ROOT)}")
    if errors:
        return errors

    seed = load_json(DATA_DIR / "venue-seed.json")
    venues = load_json(DATA_DIR / "venues.json")
    exhibitions = load_json(DATA_DIR / "exhibitions.json")
    coverage = load_json(DATA_DIR / "coverage.json")
    summary = load_json(DATA_DIR / "run-summary.json")
    try:
        venues_ts = typescript_json(ROOT / "src" / "data" / "venues.ts")
        exhibitions_ts = typescript_json(ROOT / "src" / "data" / "exhibitions.ts")
    except (ValueError, json.JSONDecodeError) as error:
        errors.append(str(error))
        venues_ts = []
        exhibitions_ts = []
    active_venue_ids = {item.get("venueId") for item in exhibitions}
    expected_active_venues = [
        venue for venue in venues if venue.get("id") in active_venue_ids
    ]
    if venues_ts != expected_active_venues:
        errors.append(
            "src/data/venues.ts must contain exactly the venues with verified London exhibitions"
        )
    if exhibitions_ts != exhibitions:
        errors.append("src/data/exhibitions.ts does not match data/exhibitions.json")

    seeds = seed.get("venues")
    if not isinstance(seeds, list):
        return errors + ["venue-seed.json must contain a venues array"]
    seed_ids = [item.get("id") for item in seeds]
    if len(seed_ids) != len(set(seed_ids)):
        errors.append("venue-seed.json contains duplicate venue ids")
    if any(not isinstance(item, str) or not SLUG_RE.fullmatch(item) for item in seed_ids):
        errors.append("Every venue id must be a lowercase kebab-case slug")

    venue_ids = [item.get("id") for item in venues]
    coverage_ids = [item.get("venueId") for item in coverage]
    if set(venue_ids) != set(seed_ids):
        errors.append("Generated venues do not exactly cover the seed venue ids")
    if set(coverage_ids) != set(seed_ids):
        errors.append("Coverage output does not exactly cover the seed venue ids")
    if len(venue_ids) != len(set(venue_ids)):
        errors.append("Generated venues contain duplicate ids")
    if len(coverage_ids) != len(set(coverage_ids)):
        errors.append("Coverage output contains duplicate venue ids")

    venue_by_id: dict[str, dict[str, Any]] = {}
    required_venue_fields = {
        "id",
        "name",
        "type",
        "address",
        "postcode",
        "coordinates",
        "area",
        "website",
        "whatsOnUrl",
        "openingHours",
        "hoursLastChecked",
        "scrapeMethod",
        "lastSuccessfulScrape",
        "priorityRank",
    }
    for venue in venues:
        venue_id = venue.get("id", "<missing>")
        venue_by_id[str(venue_id)] = venue
        missing = required_venue_fields - set(venue)
        if missing:
            errors.append(f"{venue_id}: missing venue fields {sorted(missing)}")
        if venue.get("type") not in VENUE_TYPES:
            errors.append(f"{venue_id}: invalid venue type")
        if venue.get("scrapeMethod") not in SCRAPE_METHODS:
            errors.append(f"{venue_id}: invalid scrape method")
        for field in ("website", "whatsOnUrl"):
            value = venue.get(field)
            if value is not None and not valid_http_url(value):
                errors.append(f"{venue_id}: invalid {field}")
        postcode = venue.get("postcode")
        if postcode is not None and not POSTCODE_RE.fullmatch(postcode):
            errors.append(f"{venue_id}: invalid UK postcode {postcode!r}")
        address = venue.get("address")
        if address is not None and (
            not isinstance(address, str)
            or not address.strip()
            or re.search(
                r"\b(null|undefined|unknown|n/?a|tbc|placeholder|email enquiries)\b"
                r"|(?:\+44|tel(?:ephone)?\b)",
                address,
                re.IGNORECASE,
            )
            or POSTCODE_RE.fullmatch(address.strip())
        ):
            errors.append(f"{venue_id}: malformed or placeholder address")
        area = venue.get("area")
        if area is not None and area not in AREAS:
            errors.append(f"{venue_id}: invalid area {area!r}")
        coordinates = venue.get("coordinates")
        if coordinates is not None:
            try:
                lat = float(coordinates["lat"])
                lng = float(coordinates["lng"])
                if not (51.1 <= lat <= 51.8 and -0.7 <= lng <= 0.4):
                    errors.append(f"{venue_id}: coordinates fall outside Greater London")
            except (KeyError, TypeError, ValueError):
                errors.append(f"{venue_id}: malformed coordinates")
        location_parts = (address, postcode, coordinates)
        if any(part is None for part in location_parts) and not all(
            part is None for part in location_parts
        ):
            errors.append(
                f"{venue_id}: address, postcode and coordinates must be all verified or all null"
            )
        if venue_id in active_venue_ids and any(
            part is None for part in location_parts
        ):
            errors.append(f"{venue_id}: active venue lacks a complete official address")
        opening_hours = venue.get("openingHours")
        if opening_hours is not None:
            if not isinstance(opening_hours, dict):
                errors.append(f"{venue_id}: openingHours must be an object or null")
            else:
                for day_name, hours in opening_hours.items():
                    if day_name not in DAYS:
                        errors.append(f"{venue_id}: unknown weekday {day_name!r}")
                    if not isinstance(hours, dict) or not TIME_RE.fullmatch(
                        str(hours.get("open", ""))
                    ) or not TIME_RE.fullmatch(str(hours.get("close", ""))):
                        errors.append(f"{venue_id}: invalid hours for {day_name}")
        for field in ("hoursLastChecked", "lastSuccessfulScrape"):
            value = venue.get(field)
            if value is not None:
                parse_iso(value, f"{venue_id}.{field}", errors)

    window_start = parse_iso(summary.get("windowStart"), "summary.windowStart", errors)
    window_end = parse_iso(summary.get("windowEnd"), "summary.windowEnd", errors)
    if window_start and window_end and window_end != add_calendar_month(window_start):
        errors.append("The generated window must end one calendar month after its start")
    if summary.get("windowKind") != WINDOW_KIND:
        errors.append(f"run-summary.json windowKind must be {WINDOW_KIND!r}")
    if (
        window_start
        and window_end
        and summary.get("windowInclusiveDays") != (window_end - window_start).days + 1
    ):
        errors.append("run-summary.json windowInclusiveDays is inconsistent")
    if summary.get("accuracyClaim") is not None:
        errors.append("run-summary.json must not claim unmeasured accuracy")

    exhibition_ids: set[str] = set()
    exhibition_keys: set[tuple[str, str, str]] = set()
    source_identity_venues: dict[tuple[str, str, str, str], set[str]] = {}
    for exhibition in exhibitions:
        exhibition_id = exhibition.get("id", "<missing>")
        if exhibition_id in exhibition_ids:
            errors.append(f"Duplicate exhibition id: {exhibition_id}")
        exhibition_ids.add(exhibition_id)
        venue_id = exhibition.get("venueId")
        venue = venue_by_id.get(venue_id)
        if not venue:
            errors.append(f"{exhibition_id}: unknown venue {venue_id!r}")
            continue
        title = exhibition.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{exhibition_id}: title is required")
            title = ""
        elif GENERIC_LISTING_TITLE_RE.fullmatch(title.strip()):
            errors.append(f"{exhibition_id}: generic listing title is not an exhibition")
        elif normalized_label(title) == normalized_label(venue.get("name")):
            errors.append(f"{exhibition_id}: venue-name-only title is not an exhibition")
        elif KNOWN_NON_EXHIBITION_TITLE_RE.fullmatch(title.strip()):
            errors.append(f"{exhibition_id}: known event page is not an exhibition")
        aliases = [str(venue.get("name") or "")]
        aliases.extend(PARENT_TITLE_ALIASES.get(str(venue_id), ()))
        for alias in {value for value in aliases if value}:
            escaped = re.escape(alias)
            if re.search(
                rf"(?:\s[-–—|·]\s|\s+at\s+){escaped}\s*$",
                title,
                re.IGNORECASE,
            ) or re.search(
                rf"^{escaped}\s*(?:[-–—|·:])\s+",
                title,
                re.IGNORECASE,
            ):
                errors.append(
                    f"{exhibition_id}: unexplained venue/site affix remains in title"
                )
                break
        description = exhibition.get("shortDescription")
        if not isinstance(description, str):
            errors.append(f"{exhibition_id}: shortDescription must be a string")
            description = ""
        if venue_id in {"tate-modern", "tate-britain"}:
            if not description.strip():
                errors.append(f"{exhibition_id}: Tate description is required")
            elif GENERIC_DESCRIPTION_RE.fullmatch(description.strip()):
                errors.append(
                    f"{exhibition_id}: Tate description is generic venue boilerplate"
                )
        start = parse_iso(exhibition.get("startDate"), f"{exhibition_id}.startDate", errors)
        end = parse_iso(exhibition.get("endDate"), f"{exhibition_id}.endDate", errors)
        if start and end:
            if end < start:
                errors.append(f"{exhibition_id}: end date precedes start date")
            if window_start and window_end and not (start <= window_end and end >= window_start):
                errors.append(f"{exhibition_id}: does not overlap the generated window")
            if window_start and start > window_start + timedelta(days=730):
                errors.append(f"{exhibition_id}: starts more than two years away")
        key = (
            str(venue_id),
            re.sub(r"[^a-z0-9]+", "", title.casefold()),
            str(exhibition.get("startDate")),
        )
        if key in exhibition_keys:
            errors.append(f"{exhibition_id}: duplicate venue/title/start tuple")
        exhibition_keys.add(key)
        source_url = exhibition.get("sourceUrl")
        if not valid_http_url(source_url):
            errors.append(f"{exhibition_id}: invalid source URL")
        elif GENERIC_LISTING_PATH_RE.search(
            urllib.parse.urlparse(source_url).path.rstrip("/") + "/"
        ):
            errors.append(
                f"{exhibition_id}: generic listing URL is not an exhibition detail page"
            )
        elif "instagram.com" in (urllib.parse.urlparse(source_url).hostname or ""):
            errors.append(f"{exhibition_id}: Instagram cannot be an ingested source")
        elif not (
            same_organisation(source_url, venue.get("website") or "")
            or same_organisation(source_url, venue.get("whatsOnUrl") or "")
        ):
            errors.append(f"{exhibition_id}: source URL is not on an official venue host")
        if valid_http_url(source_url):
            parsed_source = urllib.parse.urlsplit(source_url)
            canonical_source = urllib.parse.urlunsplit(
                (
                    parsed_source.scheme.casefold(),
                    parsed_source.netloc.casefold(),
                    parsed_source.path.rstrip("/"),
                    "",
                    "",
                )
            )
            identity = (
                canonical_source,
                normalized_label(title),
                str(exhibition.get("startDate")),
                str(exhibition.get("endDate")),
            )
            source_identity_venues.setdefault(identity, set()).add(str(venue_id))
        branch_prefix = BRANCH_SOURCE_PREFIXES.get(str(venue_id))
        if (
            branch_prefix
            and valid_http_url(source_url)
            and not urllib.parse.urlparse(source_url).path.startswith(branch_prefix)
        ):
            errors.append(
                f"{exhibition_id}: source URL is not scoped to {venue_id}"
            )
        image_url = exhibition.get("imageUrl")
        if image_url is not None and not valid_http_url(image_url):
            errors.append(f"{exhibition_id}: invalid image URL")
        if image_url and "replace-this-with" in image_url.casefold():
            errors.append(f"{exhibition_id}: placeholder image URL")
        if exhibition.get("priceStatus") not in PRICE_STATUSES:
            errors.append(f"{exhibition_id}: invalid price status")
        confidence = exhibition.get("confidenceScore")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            errors.append(f"{exhibition_id}: confidence must be between 0 and 1")
        parse_iso(exhibition.get("lastVerified"), f"{exhibition_id}.lastVerified", errors)

    for identity, mapped_venues in source_identity_venues.items():
        if len(mapped_venues) > 1:
            errors.append(
                "One exhibition identity maps to multiple venue branches without "
                f"explicit multi-branch evidence: {identity[0]} -> "
                f"{', '.join(sorted(mapped_venues))}"
            )

    for row in coverage:
        venue_id = row.get("venueId", "<missing>")
        if (
            row.get("windowStart") != summary.get("windowStart")
            or row.get("windowEnd") != summary.get("windowEnd")
            or row.get("windowKind") != WINDOW_KIND
        ):
            errors.append(f"{venue_id}: coverage window metadata is inconsistent")
        status = row.get("status")
        if status not in COVERAGE_STATUSES:
            errors.append(f"{venue_id}: invalid coverage status {status!r}")
        if row.get("showCount") != sum(
            1 for exhibition in exhibitions if exhibition.get("venueId") == venue_id
        ):
            errors.append(f"{venue_id}: coverage showCount does not match exhibitions")
        if not isinstance(row.get("locationVerified"), bool):
            errors.append(f"{venue_id}: locationVerified must be boolean")
        if row.get("showCount", 0) and not row.get("locationVerified"):
            errors.append(f"{venue_id}: active venue lacks verified London location")
        if status in {
            "blocked",
            "failed",
            "ambiguous",
            "closed",
            "instagram-only",
            "unverified",
            "unresolved",
        }:
            if venue_by_id.get(venue_id, {}).get("scrapeMethod") != "link-only":
                errors.append(f"{venue_id}: problem status must generate link-only method")

    rejections = load_json(DATA_DIR / "rejections.json")
    location_audit = load_json(DATA_DIR / "location-audit.json")
    price_audit = load_json(DATA_DIR / "price-audit.json")
    title_audit = load_json(DATA_DIR / "title-audit.json")
    description_audit = load_json(DATA_DIR / "description-audit.json")
    address_audit = load_json(DATA_DIR / "address-audit.json")
    image_audit = load_json(DATA_DIR / "image-audit.json")
    if not isinstance(rejections.get("records"), list):
        errors.append("rejections.json must contain a records array")
    generic_rejections = [
        row
        for row in rejections.get("records", [])
        if row.get("reasonCode") == "generic-listing-not-exhibition"
    ]
    title_rejections = title_audit.get("rejectedRecords")
    if not isinstance(title_rejections, list):
        errors.append("title-audit.json must contain a rejectedRecords array")
        title_rejections = []
    rejection_keys = {
        (row.get("venueId"), row.get("title"), row.get("sourceUrl"))
        for row in title_rejections
        if row.get("reasonCode") == "generic-listing-not-exhibition"
    }
    for row in generic_rejections:
        key = (row.get("venueId"), row.get("title"), row.get("sourceUrl"))
        if key not in rejection_keys:
            errors.append(
                "Every generic listing rejection must also appear in title-audit.json"
            )
    accepted_audits = {
        row.get("exhibitionId"): row
        for row in location_audit.get("exhibitions", [])
        if row.get("accepted")
    }
    if set(accepted_audits) != exhibition_ids:
        errors.append(
            "Every output exhibition must have one accepted London location audit"
        )
    venue_audits = {
        row.get("venueId"): row for row in location_audit.get("venues", [])
    }
    if set(venue_audits) != set(venue_ids):
        errors.append("Every venue must have a machine-readable location audit")
    for exhibition in exhibitions:
        audit = accepted_audits.get(exhibition["id"])
        if not audit or audit.get("reasonCode") != "verified-london":
            errors.append(
                f"{exhibition['id']}: missing verified-london exhibition evidence"
            )
            continue
        venue_id = exhibition["venueId"]
        if venue_id in BRANCH_TOKENS:
            branch_evidence = " ".join(
                str(value or "")
                for value in (
                    exhibition.get("title"),
                    exhibition.get("sourceUrl"),
                    audit.get("evidence"),
                )
            ).casefold()
            branch_evidence = re.sub(r"[^a-z0-9&]+", " ", branch_evidence)
            if any(
                token in branch_evidence
                for token in BRANCH_CONFLICT_TOKENS.get(venue_id, ())
            ):
                errors.append(
                    f"{exhibition['id']}: location audit contains conflicting branch evidence"
                )
            if not any(token in branch_evidence for token in BRANCH_TOKENS[venue_id]):
                errors.append(
                    f"{exhibition['id']}: location audit lacks branch-specific evidence"
                )
    price_audits = {
        row.get("exhibitionId"): row for row in price_audit.get("records", [])
    }
    if set(price_audits) != exhibition_ids:
        errors.append("Every output exhibition must have one admission-price audit")
    for exhibition in exhibitions:
        audit = price_audits.get(exhibition["id"])
        if audit and audit.get("priceStatus") != exhibition.get("priceStatus"):
            errors.append(
                f"{exhibition['id']}: price audit does not match exhibition status"
            )
        if audit and not isinstance(audit.get("confidenceScore"), (int, float)):
            errors.append(f"{exhibition['id']}: price audit confidence is required")
    title_audits = {
        row.get("exhibitionId"): row for row in title_audit.get("records", [])
    }
    if set(title_audits) != exhibition_ids:
        errors.append("Every output exhibition must have one title audit")
    description_audits = {
        row.get("exhibitionId"): row
        for row in description_audit.get("records", [])
    }
    if set(description_audits) != exhibition_ids:
        errors.append("Every output exhibition must have one description audit")
    for exhibition in exhibitions:
        audit = description_audits.get(exhibition["id"])
        if audit and audit.get("description") != exhibition.get("shortDescription"):
            errors.append(
                f"{exhibition['id']}: description audit does not match exhibition"
            )
    image_audits = {
        row.get("exhibitionId"): row for row in image_audit.get("records", [])
    }
    if set(image_audits) != exhibition_ids:
        errors.append("Every output exhibition must have one image audit")
    for exhibition in exhibitions:
        audit = image_audits.get(exhibition["id"])
        if not audit:
            continue
        if audit.get("imageUrl") != exhibition.get("imageUrl"):
            errors.append(
                f"{exhibition['id']}: image audit does not match exhibition image"
            )
        expected_status = (
            {"official-remote-image", "exhibition-official", "venue-official-fallback"}
            if exhibition.get("imageUrl")
            else {"missing-official-image"}
        )
        if audit.get("status") not in expected_status:
            errors.append(f"{exhibition['id']}: image audit status is inconsistent")
    address_audits = {
        row.get("venueId"): row for row in address_audit.get("records", [])
    }
    if set(address_audits) != set(venue_ids):
        errors.append("Every venue must have one official-address audit")
    for venue in venues:
        audit = address_audits.get(venue["id"])
        if not audit:
            continue
        complete = all(
            venue.get(field) is not None
            for field in ("address", "postcode", "coordinates")
        )
        if bool(audit.get("accepted")) != complete:
            errors.append(f"{venue['id']}: address audit does not match venue location")
    for exhibition in exhibitions:
        venue_audit = venue_audits.get(exhibition["venueId"])
        if not venue_audit or not venue_audit.get("accepted"):
            errors.append(
                f"{exhibition['id']}: venue is not independently London-verified"
            )
    if any(
        "au 108 rue vieille du temple" in str(item.get("title", "")).casefold()
        for item in exhibitions
    ):
        errors.append("Known non-London exhibition Au 108 rue Vieille du Temple remains")

    status_counts: dict[str, int] = {}
    for row in coverage:
        status = row["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    successful = sum(
        status_counts.get(status, 0) for status in ("success", "no-current-shows")
    )
    if summary.get("totalVenues") != len(venues):
        errors.append("Summary totalVenues does not match venues.json")
    if summary.get("successfulScrapes") != successful:
        errors.append("Summary successfulScrapes does not match coverage.json")
    if summary.get("exhibitionsFound") != len(exhibitions):
        errors.append("Summary exhibitionsFound does not match exhibitions.json")
    if summary.get("activeLondonVenues") != len(active_venue_ids):
        errors.append("Summary activeLondonVenues does not match exhibitions.json")
    rejection_rows = rejections.get("records", [])
    if summary.get("rejectedCandidates") != len(rejection_rows):
        errors.append("Summary rejectedCandidates does not match rejections.json")
    if summary.get("statusCounts") != dict(sorted(status_counts.items())):
        errors.append("Summary statusCounts does not match coverage.json")
    return errors


def main() -> int:
    try:
        errors = validate()
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"Validation could not run: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    if errors:
        print(f"Data validation failed with {len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    summary = load_json(DATA_DIR / "run-summary.json")
    print(
        "Data validation passed: "
        f"{summary['totalVenues']} venues, "
        f"{summary['exhibitionsFound']} exhibitions, "
        f"{summary['successfulScrapes']} successful scrapes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
