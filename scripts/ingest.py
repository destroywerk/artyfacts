#!/usr/bin/env python3
"""Respectful, structured-data-first ingestion for London exhibition venues.

The crawler intentionally uses only Python's standard library. It obeys
robots.txt, rate-limits every host, identifies itself, does not fetch
Instagram, and stops at bot protection rather than trying to bypass it.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SEED_PATH = DATA_DIR / "venue-seed.json"
OVERRIDES_PATH = DATA_DIR / "venue-overrides.json"
PRICE_OVERRIDES_PATH = DATA_DIR / "price-overrides.json"
TITLE_OVERRIDES_PATH = DATA_DIR / "title-overrides.json"
DESCRIPTION_OVERRIDES_PATH = DATA_DIR / "description-overrides.json"
VENUES_JSON_PATH = DATA_DIR / "venues.json"
EXHIBITIONS_JSON_PATH = DATA_DIR / "exhibitions.json"
COVERAGE_JSON_PATH = DATA_DIR / "coverage.json"
COVERAGE_CSV_PATH = DATA_DIR / "coverage.csv"
REJECTIONS_PATH = DATA_DIR / "rejections.json"
LOCATION_AUDIT_PATH = DATA_DIR / "location-audit.json"
PRICE_AUDIT_PATH = DATA_DIR / "price-audit.json"
TITLE_AUDIT_PATH = DATA_DIR / "title-audit.json"
DESCRIPTION_AUDIT_PATH = DATA_DIR / "description-audit.json"
ADDRESS_AUDIT_PATH = DATA_DIR / "address-audit.json"
IMAGE_AUDIT_PATH = DATA_DIR / "image-audit.json"
SUMMARY_PATH = DATA_DIR / "run-summary.json"
CACHE_DIR = DATA_DIR / "cache" / "http"
VENUES_TS_PATH = ROOT / "src" / "data" / "venues.ts"
EXHIBITIONS_TS_PATH = ROOT / "src" / "data" / "exhibitions.ts"

DEFAULT_USER_AGENT = (
    "LondonExhibitionsBot/1.0 "
    "(private non-commercial exhibition index; contact: Tim Green)"
)
USER_AGENT = os.environ.get("LONDON_EXHIBITIONS_USER_AGENT", DEFAULT_USER_AGENT)
MAX_RESPONSE_BYTES = 3_000_000
TRANSIENT_RETRIES = 2
WINDOW_MONTHS = 1
WINDOW_KIND = "calendar-month-inclusive"
POSTCODE_RE = re.compile(
    r"\b(?:GIR\s?0AA|(?:[A-PR-UWYZ][A-HK-Y]?\d[A-Z\d]?"
    r"\s?\d[ABD-HJLNP-UW-Z]{2}))\b",
    re.IGNORECASE,
)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
MONTH_NUMBER = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
MONTH_PATTERN = "|".join(MONTH_NUMBER)
DAY_MONTH_RANGE_RE = re.compile(
    rf"\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?"
    rf"(\d{{1,2}})\s+({MONTH_PATTERN})(?:\s+(\d{{4}}))?"
    rf"\s*(?:–|—|-|to|until)\s*"
    rf"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?"
    rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})\b",
    re.IGNORECASE,
)
MONTH_DAY_RANGE_RE = re.compile(
    rf"\b({MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})"
    rf"\s*(?:–|—|-|to|until)\s*"
    rf"({MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
DETAIL_PATH_RE = re.compile(
    r"/(?:exhibitions?(?:displays)?|whats?-on|whatson|programme|program|"
    r"projects?|shows?)(?:/|$)",
    re.IGNORECASE,
)
LISTING_END_RE = re.compile(
    r"/(?:exhibitions?(?:displays)?|whats?-on|whatson|programme|program|"
    r"projects?|shows?)/?$",
    re.IGNORECASE,
)
NON_EXHIBITION_RE = re.compile(
    r"\b(talks?|workshops?|tours?|films?|cinema|concerts?|performances?|"
    r"lates?|courses?|family days?|conferences?|festivals?|screenings?|"
    r"lectures?|webinars?|podcasts?|artist-in-residence|residenc(?:y|ies)|"
    r"members?'? hours?|private views?|opening receptions?|previews?|"
    r"(?:new|young) architects club|(?:primary|secondary) schools? morning)\b",
    re.IGNORECASE,
)
KNOWN_EVENT_TITLE_RE = re.compile(
    r"^(?:club origami|creative tales|halloween mask making|"
    r"wild life drawing:\s*owls)$",
    re.IGNORECASE,
)
EXHIBITION_HINT_RE = re.compile(
    r"\b(exhibition|installation|display|commission|gallery)\b", re.IGNORECASE
)
EXHIBITION_TYPE_HINT_RE = re.compile(
    r"\b(exhibition|installation|display|commission)\b", re.IGNORECASE
)
OUT_OF_SCOPE_RE = re.compile(
    r"\b(online exhibition|virtual exhibition|digital exhibition|"
    r"permanent collection|permanent display|permanent home|"
    r"various locations|national touring|touring programme)\b",
    re.IGNORECASE,
)
OUT_OF_SCOPE_TITLE_RE = re.compile(
    r"\b(across the uk|future exhibitions?|current exhibitions?|"
    r"past exhibitions?|events? and exhibitions? calendar|"
    r"location exhibitions?|bicester|brussels|patmos|"
    r"park nights|futuretense)\b",
    re.IGNORECASE,
)
GENERIC_LISTING_TITLE_RE = re.compile(
    r"^\s*(?:events?(?:\s+(?:and|&)\s+exhibitions?)?(?:\s+calendar)?|"
    r"exhibitions?(?:\s+calendar)?|what(?:'|’)s\s+on|programme|program|"
    r"visit|current\s+exhibitions?|archive|search\s+results?)\s*$",
    re.IGNORECASE,
)
GENERIC_LISTING_PATH_RE = re.compile(
    r"/(?:events?-calendar|current-exhibitions?|exhibitions?/archive|"
    r"search(?:/results?)?|programme|program|visit)/?$",
    re.IGNORECASE,
)
GENERIC_LISTING_DESCRIPTION_RE = re.compile(
    r"\b(?:exhibitions?|displays?|events?|programmes?|workshops?)\b"
    r"(?:.{0,60}\b(?:exhibitions?|displays?|events?|programmes?|workshops?)\b){2,}",
    re.IGNORECASE,
)
NON_EXHIBITION_PATH_RE = re.compile(
    r"/(?:astronomy-)?courses?(?:/|$)", re.IGNORECASE
)
BOT_PROTECTION_RE = re.compile(
    r"(cf-chl-|cloudflare ray id|just a moment|attention required|"
    r"captcha challenge|access denied|perimeterx|akamai bot manager)",
    re.IGNORECASE,
)
DAY_MAP = {
    "monday": "monday",
    "mon": "monday",
    "tuesday": "tuesday",
    "tue": "tuesday",
    "wednesday": "wednesday",
    "wed": "wednesday",
    "thursday": "thursday",
    "thu": "thursday",
    "friday": "friday",
    "fri": "friday",
    "saturday": "saturday",
    "sat": "saturday",
    "sunday": "sunday",
    "sun": "sunday",
}
SITE_TOKENS = {
    "tate-modern": ("tate modern",),
    "tate-britain": ("tate britain",),
    "gagosian-britannia-street": ("britannia",),
    "gagosian-grosvenor-hill": ("grosvenor",),
    "white-cube-bermondsey": ("bermondsey",),
    "white-cube-masons-yard": ("mason",),
    "vam": ("south kensington", "cromwell"),
    "vam-east": ("v&a east", "vam east", "stratford", "east bank", "storehouse"),
    "young-vam": ("young v&a", "young va", "bethnal green", "cambridge heath"),
    "serpentine-south": ("serpentine south", "south gallery"),
    "david-zwirner-london": ("london", "grafton street"),
    "hauser-and-wirth-london": ("london", "savile row"),
    "pace-gallery-london": ("london", "hanover square"),
    "marian-goodman-gallery-london": ("london",),
    "sprueth-magers-london": ("london", "grafton street"),
    "thaddaeus-ropac-london": ("london", "dover street"),
    "victoria-miro": ("london", "wharf road"),
}
SITE_CONFLICT_TOKENS = {
    "tate-modern": ("tate britain",),
    "tate-britain": ("tate modern",),
    "vam": (
        "v&a east",
        "vam east",
        "stratford",
        "east bank",
        "storehouse",
        "young v&a",
        "young va",
    ),
    "vam-east": ("south kensington", "cromwell road", "young v&a", "young va"),
    "young-vam": (
        "south kensington",
        "cromwell road",
        "v&a east",
        "vam east",
        "stratford",
        "east bank",
        "storehouse",
        "dundee",
    ),
    "serpentine-south": ("serpentine north", "north gallery"),
    "gagosian-britannia-street": ("grosvenor",),
    "gagosian-grosvenor-hill": ("britannia",),
    "white-cube-bermondsey": ("mason",),
    "white-cube-masons-yard": ("bermondsey",),
}
STRICT_BRANCH_PATH_VENUES = {
    "tate-britain",
    "tate-modern",
}
MULTI_LOCATION_VENUES = {
    "ben-brown-fine-arts",
    "david-zwirner-london",
    "flowers-gallery",
    "gagosian-britannia-street",
    "gagosian-grosvenor-hill",
    "hauser-and-wirth-london",
    "hales-gallery",
    "lisson-gallery",
    "kristin-hjellegjerde-gallery",
    "maddox-gallery",
    "marian-goodman-gallery-london",
    "pace-gallery-london",
    "sprueth-magers-london",
    "serpentine-south",
    "tate-britain",
    "tate-modern",
    "thaddaeus-ropac-london",
    "timothy-taylor",
    "vam",
    "vam-east",
    "young-vam",
    "victoria-miro",
    "white-cube-bermondsey",
    "white-cube-masons-yard",
}
FOREIGN_LOCATION_RE = re.compile(
    r"\b(Los Angeles|New York|Paris|Hong Kong|Brussels|Bicester|Berlin|"
    r"Tokyo|Seoul|Shanghai|Beijing|Rome|Milan|Zurich|Vienna|Madrid|"
    r"Venice|Patmos|Greece|Dundee|South Shields|Blackpool|Barnsley|Hull|Norwich)\b",
    re.IGNORECASE,
)
LONDON_ASSIGNMENT_RE = re.compile(
    r"\b(?:London\s*:|London location|location in London|London gallery|"
    r"gallery in London|on view (?:at|in)[^.]{0,80}\bLondon\b|"
    r"David Zwirner,\s*London|London,\s*20\d{4})",
    re.IGNORECASE,
)
PRIORITY_GROUPS = [
    ("the-photographers-gallery",),
    ("pilar-corrias",),
    ("the-tagli",),
    ("lisson-gallery",),
    ("william-hine",),
    ("terrace-gallery",),
    ("chisenhale-gallery",),
    ("soho-revue",),
    ("the-cob-gallery",),
    ("october-gallery",),
    ("mimosa-house",),
    ("ginny-on-frederick",),
    ("haricot-gallery",),
    ("hannah-barry-gallery",),
    ("sprueth-magers-london",),
    ("kristin-hjellegjerde-gallery",),
    ("matts-gallery",),
    ("maureen-paley",),
    ("kate-macgarry",),
    ("hales-gallery",),
    ("serpentine-south",),
    ("victoria-miro",),
    ("tate-britain",),
    ("saatchi-gallery",),
    ("barbican-art-gallery",),
    ("whitechapel-gallery",),
    ("white-cube-bermondsey",),
    ("pippy-houldsworth-gallery",),
    ("gagosian-britannia-street", "gagosian-grosvenor-hill"),
    ("saatchi-yates",),
    ("huxley-parlour",),
    ("no-9-cork-street",),
    ("john-martin-gallery",),
    ("timothy-taylor",),
    ("ben-brown-fine-arts",),
    ("thaddaeus-ropac-london",),
    ("hayward-gallery",),
    ("st-art-gallery",),
    ("sadie-coles-hq",),
    ("the-redfern-gallery",),
    ("unit-london",),
    ("david-zwirner-london",),
    ("white-cube-masons-yard",),
    ("rhodes-contemporary-art",),
    ("the-courtauld-gallery",),
    ("maddox-gallery",),
    ("pace-gallery-london",),
    ("institute-of-contemporary-arts",),
    ("royal-academy",),
    ("national-gallery",),
    ("union-pacific",),
    ("lbf-contemporary",),
    ("blueshop-cottage",),
]
PRIORITY_RANK = {
    venue_id: rank
    for rank, group in enumerate(PRIORITY_GROUPS, start=1)
    for venue_id in group
}
REJECTIONS: list[dict[str, Any]] = []
REJECTIONS_LOCK = threading.Lock()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def clean_text(value: Any, limit: int | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(clean_text(item) for item in value)
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value)))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def likely_london_postcode(value: str) -> bool:
    outward = format_postcode(value).split()[0]
    return outward.startswith(
        (
            "E",
            "EC",
            "N",
            "NW",
            "SE",
            "SW",
            "W",
            "WC",
            "BR",
            "CR",
            "DA",
            "EN",
            "HA",
            "IG",
            "KT",
            "RM",
            "SM",
            "TW",
            "UB",
            "WD",
        )
    )


def london_postcodes_in(value: str) -> list[str]:
    return sorted(
        {
            format_postcode(match.group(0))
            for match in POSTCODE_RE.finditer(value)
            if likely_london_postcode(match.group(0))
        }
    )


def reject_candidate(
    venue: dict[str, Any],
    title: str,
    source_url: str | None,
    reason_code: str,
    reason: str,
    evidence: str = "",
) -> None:
    row = {
        "venueId": venue["id"],
        "title": clean_text(title, 180) or None,
        "sourceUrl": source_url,
        "reasonCode": reason_code,
        "reason": reason,
        "evidence": clean_text(evidence, 400) or None,
    }
    with REJECTIONS_LOCK:
        REJECTIONS.append(row)


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "untitled"


def normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", slugify(value))


def sanitize_title(value: Any, venue_name: str) -> str:
    title = clean_text(value, 300)
    title = re.sub(
        rf"^cookies?\s+{re.escape(venue_name)}\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.split(
        r"\s+(?:Resources|Exhibition handout|Download Exhibition|Related Events)\b",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    title = re.sub(
        rf"\s*\|\s*{re.escape(venue_name)}\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"\s*\|\s*\d{1,2}\s+[A-Za-z]+\s*[-–—]\s*"
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}.*$",
        "",
        title,
    )
    title = re.sub(
        r"\s*[-–—]\s*(Overview|Press|Installation Views|Checklist)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return clean_text(title, 180)


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


def title_aliases(venue: dict[str, Any]) -> list[str]:
    aliases = [clean_text(venue.get("name"))]
    aliases.extend(PARENT_TITLE_ALIASES.get(venue["id"], ()))
    return sorted({alias for alias in aliases if alias}, key=len, reverse=True)


def normalize_title_site_affixes(
    record: dict[str, Any], venue: dict[str, Any]
) -> dict[str, Any]:
    before = clean_text(record.get("title"), 300)
    title = before
    changed = True
    while changed:
        changed = False
        for alias in title_aliases(venue):
            escaped = re.escape(alias)
            candidates = (
                rf"^\s*{escaped}\s*(?:[-–—|·:])\s*(.+)$",
                rf"^(.+?)\s*(?:[-–—|·])\s*{escaped}\s*$",
                rf"^(.+?)\s+at\s+{escaped}\s*$",
            )
            for pattern in candidates:
                match = re.fullmatch(pattern, title, flags=re.IGNORECASE)
                if not match:
                    continue
                remainder = clean_text(match.group(1), 300)
                if len(remainder) >= 4 and normalized_title(remainder) != normalized_title(alias):
                    title = remainder
                    changed = True
                    break
            if changed:
                break
    if title != before:
        record["title"] = title
        record["id"] = slugify(
            f"{record['venueId']}-{title}-{record['startDate']}"
        )
        if record.get("_titleAudit", {}).get("reasonCode") in {
            None,
            "official-source-title",
        }:
            record["_titleAudit"] = {
                "titleBeforeOverride": before,
                "reasonCode": "venue-site-affix-normalized",
                "evidence": (
                    "Removed an HTML/SEO venue or parent-institution affix; "
                    "the remaining text is the specific exhibition title."
                ),
            }
    return record


def page_description(probe: "PageProbe", title: str) -> str:
    social = probe.meta.get("og:description") or probe.meta.get("twitter:description")
    if social:
        return clean_text(social, 280)
    fallback = clean_text(probe.meta.get("description"), 280)
    title_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-zÀ-ÿ]{4,}", title)
        if word.casefold() not in {"with", "from", "this", "that"}
    }
    if fallback and any(word in fallback.casefold() for word in title_words):
        return fallback
    return ""


def parse_date(value: Any) -> date | None:
    if isinstance(value, dict):
        value = value.get("@value") or value.get("value")
    if not isinstance(value, str):
        return None
    value = value.strip()
    match = ISO_DATE_RE.match(value)
    if match:
        try:
            return date.fromisoformat(match.group(0))
        except ValueError:
            return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.date()
    except (TypeError, ValueError, OverflowError):
        return None


def date_ranges_from_text(value: str) -> list[tuple[date, date]]:
    ranges: list[tuple[int, date, date]] = []
    for match in DAY_MONTH_RANGE_RE.finditer(value):
        end_year = int(match.group(6))
        start_year = int(match.group(3) or end_year)
        try:
            start = date(
                start_year,
                MONTH_NUMBER[match.group(2).lower()],
                int(match.group(1)),
            )
            end = date(
                end_year,
                MONTH_NUMBER[match.group(5).lower()],
                int(match.group(4)),
            )
            if not match.group(3) and start > end:
                start = start.replace(year=start.year - 1)
            ranges.append((match.start(), start, end))
        except ValueError:
            continue
    for match in MONTH_DAY_RANGE_RE.finditer(value):
        try:
            start = date(
                int(match.group(3)),
                MONTH_NUMBER[match.group(1).lower()],
                int(match.group(2)),
            )
            end = date(
                int(match.group(6)),
                MONTH_NUMBER[match.group(4).lower()],
                int(match.group(5)),
            )
            ranges.append((match.start(), start, end))
        except ValueError:
            continue
    return [(start, end) for _, start, end in sorted(ranges)]


def iso_or_none(value: date | None) -> str | None:
    return value.isoformat() if value else None


def add_calendar_months(value: date, months: int = WINDOW_MONTHS) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def same_organisation(url_a: str | None, url_b: str | None) -> bool:
    if not url_a or not url_b:
        return False
    host_a = (urllib.parse.urlparse(url_a).hostname or "").lower().removeprefix("www.")
    host_b = (urllib.parse.urlparse(url_b).hostname or "").lower().removeprefix("www.")
    return bool(host_a and host_b and (host_a == host_b or host_a.endswith("." + host_b) or host_b.endswith("." + host_a)))


def normalized_url_path(url: str) -> str:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path).lower()
    return re.sub(r"[^a-z0-9]+", " ", path).strip()


def generic_listing_reason(
    title: str,
    source_url: str,
    description: str,
    venue_name: str,
) -> str | None:
    source_path = urllib.parse.urlparse(source_url).path
    if GENERIC_LISTING_TITLE_RE.fullmatch(title):
        return "Title identifies a calendar or listing page, not a named exhibition"
    if normalized_title(title) == normalized_title(venue_name):
        return "Title is only the venue name, not a named exhibition"
    if GENERIC_LISTING_PATH_RE.search(source_path):
        return "Source URL is a generic calendar, programme, archive, search, or visit page"
    if GENERIC_LISTING_DESCRIPTION_RE.search(description) and not EXHIBITION_HINT_RE.search(
        title
    ):
        return "Description lists mixed displays, events, programmes, or workshops rather than one named exhibition"
    return None


def matches_venue_site(
    venue_id: str, value: str, source_url: str | None = None
) -> bool:
    lowered = value.lower()
    conflicts = SITE_CONFLICT_TOKENS.get(venue_id, ())
    tokens = SITE_TOKENS.get(venue_id, ())
    if source_url:
        source_path = normalized_url_path(source_url)
        if any(token in source_path for token in conflicts):
            return False
        if any(token in source_path for token in tokens):
            return True
    if any(token in lowered for token in conflicts):
        return False
    if any(token in lowered for token in tokens):
        return True
    return not tokens or any(token in lowered for token in tokens)


def official_url(candidate: Any, page_url: str, venue: dict[str, Any]) -> str:
    if isinstance(candidate, dict):
        candidate = candidate.get("@id") or candidate.get("url")
    if not isinstance(candidate, str) or not candidate.strip():
        return page_url
    result = urllib.parse.urljoin(page_url, candidate.strip())
    if result.startswith(("http://", "https://")) and (
        same_organisation(result, venue.get("website"))
        or same_organisation(result, venue.get("whatsOnUrl"))
    ):
        return result
    return page_url


def image_url(value: Any, page_url: str) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl") or value.get("@id")
    if not isinstance(value, str):
        return None
    result = urllib.parse.urljoin(page_url, value.strip())
    if "replace-this-with" in result.lower():
        return None
    return result if result.startswith(("http://", "https://")) else None


def page_image(probe: "PageProbe", page_url: str) -> str | None:
    social = image_url(
        probe.meta.get("og:image")
        or probe.meta.get("twitter:image")
        or probe.meta.get("twitter:image:src"),
        page_url,
    )
    if social:
        return social
    title_tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-zÀ-ÿ]{4,}", probe.title)
        if token.casefold()
        not in {"exhibition", "gallery", "london", "current", "works", "with"}
    }
    scored: list[tuple[int, int, str]] = []
    for index, candidate in enumerate(probe.image_candidates):
        raw = candidate.get("data-src")
        responsive = (
            candidate.get("data-responsive-src") or candidate.get("srcset") or ""
        )
        if not raw and responsive:
            urls = re.findall(r"https?://[^'\"\s,}]+", html.unescape(responsive))
            raw = urls[-1] if urls else None
        raw = raw or candidate.get("src")
        resolved = image_url(raw, page_url)
        if not resolved or resolved.startswith("data:"):
            continue
        searchable = clean_text(
            [
                candidate.get("alt"),
                candidate.get("class"),
                urllib.parse.unquote(urllib.parse.urlparse(resolved).path),
            ]
        ).casefold()
        if re.search(r"\b(logo|icon|avatar|navigation|gmap|map)\b", searchable):
            continue
        score = 0
        if any(token in searchable for token in title_tokens):
            score += 4
        if re.search(r"\b(hero|featured|banner|lead)\b", searchable):
            score += 3
        if candidate.get("data-src") or responsive:
            score += 1
        if "/wp-content/uploads/" in resolved:
            score += 1
        if score:
            scored.append((score, -index, resolved))
    return max(scored)[2] if scored else None


def infer_price(item: dict[str, Any], text: str) -> str:
    explicit = item.get("isAccessibleForFree")
    if explicit is True or str(explicit).lower() == "true":
        return "free"
    if explicit is False or str(explicit).lower() == "false":
        return "paid"
    offers = item.get("offers")
    if not isinstance(offers, list):
        offers = [offers] if offers else []
    prices: list[float] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        raw = offer.get("price")
        try:
            prices.append(float(raw))
        except (TypeError, ValueError):
            pass
    if prices:
        return "free" if all(price == 0 for price in prices) else "paid"
    if re.search(r"(£\s?\d|\bfrom\s+£)", text, re.IGNORECASE):
        return "paid"
    if re.search(r"\bfree for members?\b", text, re.IGNORECASE):
        return "paid"
    if re.search(r"\b(free|free entry|admission is free)\b", text, re.IGNORECASE):
        return "free"
    return "unknown"


def accent_for(value: str) -> str:
    palette = (
        "#385448",
        "#805440",
        "#7a7863",
        "#b75534",
        "#476d9b",
        "#334737",
        "#277f8e",
        "#9e2026",
        "#8c704d",
        "#433e79",
        "#4f7694",
        "#6b5b73",
    )
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return palette[digest[0] % len(palette)]


def is_instagram(url: str | None) -> bool:
    return bool(url and "instagram.com" in (urllib.parse.urlparse(url).hostname or "").lower())


@dataclass
class FetchResult:
    url: str
    status: int | None
    body: bytes
    content_type: str
    error: str | None = None
    blocked: bool = False
    from_cache: bool = False
    redirect_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and not self.blocked

    def text(self) -> str:
        charset = "utf-8"
        match = re.search(r"charset=([\w-]+)", self.content_type, re.IGNORECASE)
        if match:
            charset = match.group(1)
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class HostLimiter:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._next_allowed: dict[str, float] = {}

    def lock_for(self, host: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(host, threading.Lock())

    def wait(self, host: str) -> None:
        with self.lock_for(host):
            remaining = self._next_allowed.get(host, 0.0) - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            self._next_allowed[host] = time.monotonic() + self.delay


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class RespectfulFetcher:
    def __init__(self, delay: float, refresh: bool) -> None:
        self.limiter = HostLimiter(delay)
        self.refresh = refresh
        self.opener = urllib.request.build_opener(NoRedirect)
        self._robots: dict[str, tuple[bool, str, list[str]]] = {}
        self._robots_guard = threading.Lock()
        self._robots_locks: dict[str, threading.Lock] = {}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _robots_lock_for(self, host: str) -> threading.Lock:
        with self._robots_guard:
            return self._robots_locks.setdefault(host, threading.Lock())

    def _request_once(self, url: str) -> FetchResult:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return FetchResult(url, None, b"", "", "URL has no hostname")
        self.limiter.wait(host)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/ld+json,application/xml,text/xml,text/calendar,application/rss+xml,application/atom+xml;q=0.9,*/*;q=0.5",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with self.opener.open(request, timeout=25) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    return FetchResult(url, response.status, b"", "", "Response exceeded size limit")
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
                content_type = response.headers.get("Content-Type", "")
                return FetchResult(
                    url,
                    response.status,
                    body,
                    content_type,
                    redirect_url=response.headers.get("Location"),
                )
        except urllib.error.HTTPError as error:
            body = error.read(200_000)
            return FetchResult(
                url,
                error.code,
                body,
                error.headers.get("Content-Type", "") if error.headers else "",
                f"HTTP {error.code}",
                blocked=error.code in {401, 403, 406, 409, 429},
                redirect_url=error.headers.get("Location") if error.headers else None,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return FetchResult(url, None, b"", "", f"{type(error).__name__}: {error}")

    def robots_decision(self, url: str) -> tuple[bool, str, list[str]]:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        key = f"{parsed.scheme}://{parsed.netloc}"
        if not host:
            return False, "invalid-host", []
        with self._robots_guard:
            cached = self._robots.get(key)
        if cached:
            return cached
        with self._robots_lock_for(key):
            with self._robots_guard:
                cached = self._robots.get(key)
            if cached:
                return cached
            robots_url = urllib.parse.urljoin(key, "/robots.txt")
            result = self._request_once(robots_url)
            redirects = 0
            while (
                result.status in {301, 302, 303, 307, 308}
                and result.redirect_url
                and redirects < 4
            ):
                robots_url = urllib.parse.urljoin(robots_url, result.redirect_url)
                result = self._request_once(robots_url)
                redirects += 1
            sitemaps: list[str] = []
            if result.status == 404:
                decision = (True, "robots-not-found", sitemaps)
            elif result.status in {401, 403}:
                decision = (False, f"robots-http-{result.status}", sitemaps)
            elif not result.ok:
                decision = (False, f"robots-unavailable:{result.error}", sitemaps)
            else:
                robots_text = result.text()
                parser = urllib.robotparser.RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(robots_text.splitlines())
                sitemaps = parser.site_maps() or []
                allowed = parser.can_fetch(USER_AGENT, url)
                decision = (allowed, "robots-allowed" if allowed else "robots-disallowed", sitemaps)
            with self._robots_guard:
                self._robots[key] = decision
            return decision

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{digest}.body", CACHE_DIR / f"{digest}.json"

    def _load_cache(self, url: str) -> FetchResult | None:
        if self.refresh:
            return None
        body_path, meta_path = self._cache_paths(url)
        if not body_path.exists() or not meta_path.exists():
            return None
        try:
            meta = read_json(meta_path, {})
            fetched_at = datetime.fromisoformat(meta["fetchedAt"])
            if datetime.now(timezone.utc) - fetched_at > timedelta(hours=18):
                return None
            return FetchResult(
                meta.get("url", url),
                meta.get("status"),
                body_path.read_bytes(),
                meta.get("contentType", ""),
                meta.get("error"),
                meta.get("blocked", False),
                from_cache=True,
                redirect_url=meta.get("redirectUrl"),
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return None

    def _save_cache(self, requested_url: str, result: FetchResult) -> None:
        if not result.ok:
            return
        body_path, meta_path = self._cache_paths(requested_url)
        body_path.write_bytes(result.body)
        write_json(
            meta_path,
            {
                "url": result.url,
                "status": result.status,
                "contentType": result.content_type,
                "error": result.error,
                "blocked": result.blocked,
                "redirectUrl": result.redirect_url,
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "sha256": hashlib.sha256(result.body).hexdigest(),
            },
        )

    def fetch(self, url: str) -> FetchResult:
        if is_instagram(url):
            return FetchResult(url, None, b"", "", "Instagram is intentionally not scraped", blocked=True)
        if not url.startswith(("http://", "https://")):
            return FetchResult(url, None, b"", "", "Unsupported URL scheme")
        cached = self._load_cache(url)
        if cached:
            return cached
        current_url = url
        for redirect_count in range(5):
            allowed, reason, _ = self.robots_decision(current_url)
            if not allowed:
                return FetchResult(current_url, None, b"", "", reason, blocked=True)
            result: FetchResult | None = None
            for attempt in range(TRANSIENT_RETRIES + 1):
                result = self._request_once(current_url)
                if result.status in {301, 302, 303, 307, 308}:
                    location = result.redirect_url
                    if not location:
                        return FetchResult(
                            current_url,
                            result.status,
                            result.body,
                            result.content_type,
                            "Redirect target unavailable; update the seed URL",
                        )
                    current_url = urllib.parse.urljoin(current_url, location)
                    break
                if result.status is None or (result.status and result.status >= 500):
                    if attempt < TRANSIENT_RETRIES:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                break
            assert result is not None
            if result.status in {301, 302, 303, 307, 308}:
                continue
            result.url = current_url
            if result.ok and BOT_PROTECTION_RE.search(result.text()[:200_000]):
                result.blocked = True
                result.error = "Bot-protection challenge detected; no bypass attempted"
            self._save_cache(url, result)
            return result
        return FetchResult(current_url, None, b"", "", "Too many redirects")

    def sitemaps_for(self, url: str) -> list[str]:
        _, _, sitemaps = self.robots_decision(url)
        return sitemaps


class PageProbe(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.json_ld: list[str] = []
        self.feed_links: list[str] = []
        self.calendar_links: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self.times: list[str] = []
        self.meta: dict[str, str] = {}
        self.text_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.section_title_parts: list[str] = []
        self.title_parts: list[str] = []
        self.address_parts: list[str] = []
        self.price_parts: list[str] = []
        self.image_candidates: list[dict[str, str]] = []
        self._script_type = ""
        self._script_parts: list[str] = []
        self._current_anchor: str | None = None
        self._anchor_parts: list[str] = []
        self._in_h1 = 0
        self._in_section_title = 0
        self._in_title = 0
        self._in_address = 0
        self._price_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        classes = values.get("class", "").lower().split()
        if self._price_depth:
            self._price_depth += 1
        elif "content-block--price" in classes:
            self._price_depth = 1
        if tag == "script":
            self._script_type = values.get("type", "").lower()
            self._script_parts = []
        elif tag == "base" and values.get("href"):
            self.base_url = urllib.parse.urljoin(self.base_url, values["href"])
        elif tag == "a" and values.get("href"):
            self._current_anchor = urllib.parse.urljoin(self.base_url, values["href"])
            self._anchor_parts = []
        elif tag == "link" and values.get("href"):
            target = urllib.parse.urljoin(self.base_url, values["href"])
            content_type = values.get("type", "").lower()
            rel = values.get("rel", "").lower()
            if "alternate" in rel and ("rss" in content_type or "atom" in content_type):
                self.feed_links.append(target)
            if "calendar" in content_type or target.lower().endswith((".ics", ".ical")):
                self.calendar_links.append(target)
        elif tag == "time" and values.get("datetime"):
            self.times.append(values["datetime"])
        elif tag == "meta":
            key = (
                values.get("property")
                or values.get("name")
                or values.get("itemprop")
                or ""
            ).lower()
            content = values.get("content", "")
            if key and content:
                self.meta[key] = content
        elif tag == "img":
            self.image_candidates.append(
                {
                    key: values[key]
                    for key in (
                        "src",
                        "data-src",
                        "data-responsive-src",
                        "srcset",
                        "alt",
                        "class",
                    )
                    if values.get(key)
                }
            )
        elif tag == "h1":
            self._in_h1 += 1
        elif "sectiontitle" in values.get("class", "").lower().split():
            self._in_section_title += 1
        elif tag == "title":
            self._in_title += 1
        elif tag == "address":
            self._in_address += 1

    def handle_endtag(self, tag: str) -> None:
        if self._price_depth:
            self._price_depth -= 1
        if tag == "script":
            if "ld+json" in self._script_type:
                self.json_ld.append("".join(self._script_parts))
            self._script_type = ""
            self._script_parts = []
        elif tag == "a" and self._current_anchor:
            self.anchors.append((self._current_anchor, clean_text(self._anchor_parts)))
            self._current_anchor = None
            self._anchor_parts = []
        elif tag == "h1":
            self._in_h1 = max(0, self._in_h1 - 1)
        elif tag in {"span", "div"} and self._in_section_title:
            self._in_section_title = max(0, self._in_section_title - 1)
        elif tag == "title":
            self._in_title = max(0, self._in_title - 1)
        elif tag == "address":
            self._in_address = max(0, self._in_address - 1)

    def handle_data(self, data: str) -> None:
        if self._script_type:
            self._script_parts.append(data)
            return
        stripped = data.strip()
        if not stripped:
            return
        if sum(len(part) for part in self.text_parts) < 600_000:
            self.text_parts.append(stripped)
        if self._current_anchor:
            self._anchor_parts.append(stripped)
        if self._in_h1:
            self.h1_parts.append(stripped)
        if self._in_section_title:
            self.section_title_parts.append(stripped)
        if self._in_title:
            self.title_parts.append(stripped)
        if self._in_address:
            self.address_parts.append(stripped)
        if self._price_depth:
            self.price_parts.append(stripped)

    @property
    def text(self) -> str:
        return clean_text(self.text_parts)

    @property
    def title(self) -> str:
        return clean_text(self.h1_parts or self.section_title_parts or self.title_parts)

    @property
    def primary_price(self) -> str:
        return clean_text(self.price_parts)


def parse_json_ld(probe: PageProbe) -> list[Any]:
    values: list[Any] = []
    for raw in probe.json_ld:
        raw = raw.strip()
        if not raw:
            continue
        try:
            values.append(json.loads(raw))
        except json.JSONDecodeError:
            # Some CMSs concatenate JSON objects without an array.
            decoder = json.JSONDecoder()
            position = 0
            while position < len(raw):
                try:
                    value, end = decoder.raw_decode(raw, position)
                    values.append(value)
                    position = end
                except json.JSONDecodeError:
                    position += 1
    return values


def walk_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from walk_objects(child)
    elif isinstance(value, list):
        for item in value:
            yield from walk_objects(item)


def type_names(item: dict[str, Any]) -> set[str]:
    value = item.get("@type", [])
    if isinstance(value, str):
        value = [value]
    return {str(entry).lower() for entry in value}


def event_from_item(
    item: dict[str, Any],
    venue: dict[str, Any],
    page_url: str,
    today: date,
    window_end: date,
    shared_source: bool,
) -> tuple[dict[str, Any] | None, bool]:
    types = type_names(item)
    is_event = any(
        entry.endswith("event") or entry in {"exhibition", "visualartsevent"}
        for entry in types
    )
    if not is_event:
        return None, False
    raw_title = clean_text(item.get("name") or item.get("headline"), 300)
    title = sanitize_title(raw_title, venue["name"])
    source = official_url(item.get("url") or item.get("@id"), page_url, venue)
    description = clean_text(item.get("description"), 280)
    generic_reason = generic_listing_reason(
        title, source, description, venue["name"]
    )
    if generic_reason:
        reject_candidate(
            venue,
            title,
            source,
            "generic-listing-not-exhibition",
            generic_reason,
            description or title,
        )
        return None, True
    combined = clean_text(
        [
            raw_title,
            title,
            description,
            json.dumps(item.get("location"), ensure_ascii=False, default=str),
            source,
        ]
    )
    explicit_exhibition_type = any(
        "exhibition" in entry or "visualarts" in entry for entry in types
    )
    clearly_exhibition = (
        explicit_exhibition_type
        or EXHIBITION_TYPE_HINT_RE.search(combined)
        or DETAIL_PATH_RE.search(urllib.parse.urlparse(source).path)
    )
    if not clearly_exhibition:
        reject_candidate(
            venue, title, source, "not-exhibition", "Structured event is not an exhibition"
        )
        return None, False
    if (
        NON_EXHIBITION_RE.search(title)
        or (
            NON_EXHIBITION_RE.search(combined)
            and not explicit_exhibition_type
        )
        or NON_EXHIBITION_PATH_RE.search(urllib.parse.urlparse(source).path)
        or KNOWN_EVENT_TITLE_RE.search(title)
    ):
        reject_candidate(
            venue,
            title,
            source,
            "excluded-event-type",
            "Talk, tour, course, screening, preview, or other non-exhibition event",
        )
        return None, False
    scope_text = clean_text([title, item.get("description")])
    if OUT_OF_SCOPE_RE.search(scope_text) or OUT_OF_SCOPE_TITLE_RE.search(title):
        code = "non-london-location" if FOREIGN_LOCATION_RE.search(title) else "out-of-scope"
        reject_candidate(
            venue,
            title,
            source,
            code,
            "Event is outside the London temporary-exhibition scope",
            title,
        )
        return None, False
    if not matches_venue_site(venue["id"], combined, source):
        reject_candidate(
            venue,
            title,
            source,
            "location-branch-mismatch",
            "Event is not explicitly assigned to this London branch",
            json.dumps(item.get("location"), ensure_ascii=False, default=str),
        )
        return None, False
    start = parse_date(item.get("startDate") or item.get("startTime"))
    end = parse_date(item.get("endDate") or item.get("endTime"))
    if not title or not start or not end:
        reject_candidate(
            venue, title, source, "missing-dates", "Exhibition requires both start and end dates"
        )
        return None, False
    if (
        end < start
        or start < today - timedelta(days=730)
        or start > today + timedelta(days=730)
        or end > today + timedelta(days=730)
    ):
        reject_candidate(
            venue,
            title,
            source,
            "invalid-date-range",
            "Dates are reversed or outside the two-year validation boundary",
            f"{start.isoformat()} to {end.isoformat()}",
        )
        return None, False
    if end < today or start > window_end:
        reject_candidate(
            venue,
            title,
            source,
            "outside-window",
            "Exhibition does not overlap the generated calendar-month window",
            f"{start.isoformat()} to {end.isoformat()}",
        )
        return None, True
    record_id = slugify(f"{venue['id']}-{title}-{start.isoformat()}")
    record = {
        "id": record_id,
        "venueId": venue["id"],
        "title": title,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "shortDescription": description,
        "imageUrl": image_url(item.get("image") or item.get("thumbnailUrl"), page_url),
        "cachedThumbnail": None,
        "sourceUrl": source,
        "priceStatus": infer_price(item, combined),
        "confidenceScore": 0.96,
        "lastVerified": today.isoformat(),
        "accent": accent_for(record_id),
        "_branchEvidence": combined,
    }
    return record, True


def generic_page_event(
    probe: PageProbe,
    venue: dict[str, Any],
    page_url: str,
    today: date,
    window_end: date,
    shared_source: bool,
) -> tuple[dict[str, Any] | None, bool]:
    path = urllib.parse.urlparse(page_url).path
    if not DETAIL_PATH_RE.search(path) or LISTING_END_RE.search(path):
        return None, False
    raw_title = clean_text(probe.meta.get("og:title") or probe.title, 300)
    title = sanitize_title(raw_title, venue["name"])
    if (
        not title
        or NON_EXHIBITION_RE.search(title)
        or KNOWN_EVENT_TITLE_RE.search(title)
    ):
        if title:
            reject_candidate(
                venue,
                title,
                page_url,
                "excluded-event-type",
                "Page is a non-exhibition event",
            )
        return None, False
    description = page_description(probe, title)
    generic_reason = generic_listing_reason(
        title, page_url, description, venue["name"]
    )
    if generic_reason:
        reject_candidate(
            venue,
            title,
            page_url,
            "generic-listing-not-exhibition",
            generic_reason,
            description or title,
        )
        return None, True
    combined = clean_text([raw_title, title, description, probe.text[:50_000]])
    scope_text = clean_text([raw_title, title, description])
    if (
        OUT_OF_SCOPE_RE.search(scope_text)
        or OUT_OF_SCOPE_TITLE_RE.search(title)
        or NON_EXHIBITION_PATH_RE.search(path)
    ):
        code = "non-london-location" if FOREIGN_LOCATION_RE.search(title) else "out-of-scope"
        reject_candidate(
            venue,
            title,
            page_url,
            code,
            "Page is outside the London temporary-exhibition scope",
            title,
        )
        return None, False
    if not matches_venue_site(venue["id"], combined, page_url):
        reject_candidate(
            venue,
            title,
            page_url,
            "location-branch-mismatch",
            "Page is not explicitly assigned to this London branch",
            raw_title,
        )
        return None, False
    ranges = date_ranges_from_text(combined)
    if ranges:
        start, end = ranges[0]
    else:
        parsed_dates = [parsed for value in probe.times if (parsed := parse_date(value))]
        unique_dates = sorted(set(parsed_dates))
        if len(unique_dates) < 2:
            reject_candidate(
                venue,
                title,
                page_url,
                "missing-dates",
                "Page does not provide both exhibition dates",
            )
            return None, False
        start, end = unique_dates[0], unique_dates[-1]
    if (
        end < start
        or start < today - timedelta(days=730)
        or start > today + timedelta(days=730)
        or end > today + timedelta(days=730)
    ):
        reject_candidate(
            venue,
            title,
            page_url,
            "invalid-date-range",
            "Dates are reversed or outside the two-year validation boundary",
            f"{start.isoformat()} to {end.isoformat()}",
        )
        return None, False
    if end < today or start > window_end:
        reject_candidate(
            venue,
            title,
            page_url,
            "outside-window",
            "Exhibition does not overlap the generated calendar-month window",
            f"{start.isoformat()} to {end.isoformat()}",
        )
        return None, True
    source = official_url(probe.meta.get("og:url"), page_url, venue)
    record_id = slugify(f"{venue['id']}-{title}-{start.isoformat()}")
    return (
        {
            "id": record_id,
            "venueId": venue["id"],
            "title": title,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "shortDescription": description,
            "imageUrl": page_image(probe, page_url),
            "cachedThumbnail": None,
            "sourceUrl": source,
            "priceStatus": infer_price({}, probe.primary_price or combined),
            "confidenceScore": 0.78,
            "lastVerified": today.isoformat(),
            "accent": accent_for(record_id),
            "_branchEvidence": combined,
        },
        True,
    )


def extract_opening_hours(item: dict[str, Any]) -> dict[str, dict[str, str]] | None:
    specifications = item.get("openingHoursSpecification")
    if not isinstance(specifications, list):
        specifications = [specifications] if specifications else []
    result: dict[str, dict[str, str]] = {}
    for spec in specifications:
        if not isinstance(spec, dict):
            continue
        opens = clean_text(spec.get("opens"))
        closes = clean_text(spec.get("closes"))
        if not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", opens) or not re.fullmatch(
            r"\d{2}:\d{2}(?::\d{2})?", closes
        ):
            continue
        raw_days = spec.get("dayOfWeek", [])
        if not isinstance(raw_days, list):
            raw_days = [raw_days]
        for raw_day in raw_days:
            day = str(raw_day).rsplit("/", 1)[-1].lower()
            canonical = DAY_MAP.get(day) or DAY_MAP.get(day[:3])
            if canonical:
                result[canonical] = {"open": opens[:5], "close": closes[:5]}
    return result or None


def metadata_from_json_ld(values: list[Any], page_text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    suitable_types = {
        "organization",
        "localbusiness",
        "artgallery",
        "museum",
        "touristattraction",
        "place",
        "performingartstheater",
        "civicstructure",
    }
    for value in values:
        for item in walk_objects(value):
            if not (type_names(item) & suitable_types):
                continue
            address = item.get("address")
            if isinstance(address, dict):
                postcode = clean_text(address.get("postalCode")).upper()
                street = clean_text(
                    [
                        address.get("streetAddress"),
                        address.get("addressLocality"),
                    ]
                )
                if postcode and POSTCODE_RE.fullmatch(postcode):
                    result.setdefault("postcode", format_postcode(postcode))
                if street:
                    result.setdefault("address", street)
            geo = item.get("geo")
            if isinstance(geo, dict):
                try:
                    lat = float(geo.get("latitude"))
                    lng = float(geo.get("longitude"))
                    if 51.1 <= lat <= 51.8 and -0.7 <= lng <= 0.4:
                        result.setdefault("coordinates", {"lat": lat, "lng": lng})
                except (TypeError, ValueError):
                    pass
            hours = extract_opening_hours(item)
            if hours:
                result.setdefault("openingHours", hours)
    if "postcode" not in result:
        postcodes = {format_postcode(match.group(0)) for match in POSTCODE_RE.finditer(page_text)}
        if len(postcodes) == 1:
            result["postcode"] = postcodes.pop()
    return result


def metadata_from_probe(
    values: list[Any], probe: PageProbe, page_url: str
) -> dict[str, Any]:
    result = metadata_from_json_ld(values, probe.text)
    address_text = clean_text(probe.address_parts)
    postcodes = london_postcodes_in(address_text)
    if len(postcodes) == 1:
        postcode = postcodes[0]
        result.setdefault("postcode", postcode)
        street = clean_text(POSTCODE_RE.sub("", address_text)).strip(" ,")
        if valid_street_address(street):
            result.setdefault("address", street)
    if result.get("postcode") and not result.get("address"):
        postcode_matches = list(POSTCODE_RE.finditer(probe.text))
        matching = [
            match
            for match in postcode_matches
            if format_postcode(match.group(0)) == result["postcode"]
        ]
        if len(matching) == 1:
            context = probe.text[max(0, matching[0].start() - 180) : matching[0].start()]
            street_matches = list(
                re.finditer(
                    r"\b\d{1,4}[A-Za-z]?(?:[–—-]\d{1,4})?\s+"
                    r"[A-Za-zÀ-ÿ0-9'’&., -]{2,80}?\b"
                    r"(?:Street|Road|Lane|Square|Place|Row|Mews|Gardens|"
                    r"Terrace|Yard|Hill|Park|Avenue|Walk|Way)\b"
                    r"(?:,\s*[A-Za-zÀ-ÿ'’ -]{2,35})?\s*$",
                    context,
                    re.IGNORECASE,
                )
            )
            if street_matches:
                street = clean_text(street_matches[-1].group(0)).strip(" ,")
                if valid_street_address(street):
                    result["address"] = street
    if result.get("address") and result.get("postcode"):
        result["addressSourceUrl"] = page_url
    return result


def format_postcode(value: str) -> str:
    compact = re.sub(r"\s+", "", value.upper())
    return f"{compact[:-3]} {compact[-3:]}" if len(compact) > 3 else compact


def candidate_detail_links(
    probe: PageProbe, venue: dict[str, Any], limit: int
) -> list[str]:
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, (target, label) in enumerate(probe.anchors):
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme not in {"http", "https"} or not same_organisation(
            target, venue.get("whatsOnUrl")
        ):
            continue
        clean = urllib.parse.urlunparse(parsed._replace(fragment=""))
        if clean in seen or not DETAIL_PATH_RE.search(parsed.path):
            continue
        is_exhibition_card = bool(
            re.match(r"\s*Exhibition\b", label, re.IGNORECASE)
        )
        if LISTING_END_RE.search(parsed.path) or (
            NON_EXHIBITION_RE.search(label) and not is_exhibition_card
        ):
            continue
        if (
            venue["id"] in STRICT_BRANCH_PATH_VENUES
            and not matches_venue_site(venue["id"], label, clean)
        ):
            continue
        seen.add(clean)
        score = 0
        if "exhibition" in parsed.path.lower():
            score += 4
        if re.fullmatch(
            r"/whats-on/tate-(?:britain|modern)/[^/]+/?",
            parsed.path,
            re.IGNORECASE,
        ):
            score += 5
        if EXHIBITION_HINT_RE.search(label):
            score += 2
        if re.search(r"/20\d{2}/", parsed.path):
            score += 1
        scored.append((score, index, clean))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [target for _, _, target in scored[:limit]]


def candidate_info_links(
    probe: PageProbe, venue: dict[str, Any], limit: int = 3
) -> list[str]:
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, (target, label) in enumerate(probe.anchors):
        parsed = urllib.parse.urlparse(target)
        if (
            parsed.scheme not in {"http", "https"}
            or not same_organisation(target, venue.get("website"))
        ):
            continue
        clean = urllib.parse.urlunparse(parsed._replace(fragment=""))
        if clean in seen:
            continue
        searchable = f"{parsed.path} {label}".lower()
        if not re.search(
            r"\b(visit|contact|location|find us|getting here|get here|access)\b",
            searchable,
        ):
            continue
        seen.add(clean)
        score = 2 if re.search(r"/(?:visit|contact|locations?)/?$", parsed.path, re.I) else 1
        scored.append((score, index, clean))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [target for _, _, target in scored[:limit]]


def parse_artlogic_listing(
    page_html: str,
    page_url: str,
    venue: dict[str, Any],
    today: date,
    window_end: date,
    shared_source: bool,
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    observed = 0
    for card in re.findall(r"<li\b[^>]*>(.*?)</li>", page_html, re.I | re.S):
        link_match = re.search(
            r'<a\b[^>]*href=["\']([^"\']*/exhibitions?/\d+/[^"\']*)["\']',
            card,
            re.I,
        )
        date_match = re.search(
            r'class=["\'][^"\']*\bdate\b[^"\']*["\'][^>]*>(.*?)</',
            card,
            re.I | re.S,
        )
        artist_match = re.search(r"<h2\b[^>]*>(.*?)</h2>", card, re.I | re.S)
        subtitle_match = re.search(
            r'class=["\'][^"\']*\bsubtitle\b[^"\']*["\'][^>]*>(.*?)</',
            card,
            re.I | re.S,
        )
        location_match = re.search(
            r'class=["\'][^"\']*\blocation\b[^"\']*["\'][^>]*>(.*?)</',
            card,
            re.I | re.S,
        )
        if not (link_match and date_match and artist_match):
            continue
        plain = lambda value: clean_text(
            html.unescape(re.sub(r"<[^>]+>", " ", value))
        )
        date_text = plain(date_match.group(1))
        ranges = date_ranges_from_text(date_text)
        if not ranges:
            continue
        start, end = ranges[0]
        artist = plain(artist_match.group(1))
        subtitle = plain(subtitle_match.group(1)) if subtitle_match else ""
        title = f"{artist}: {subtitle}" if subtitle else artist
        location = plain(location_match.group(1)) if location_match else ""
        description_match = re.search(
            r'class=["\'][^"\']*\bdescription\b[^"\']*["\'][^>]*>(.*?)</',
            card,
            re.I | re.S,
        )
        description = plain(description_match.group(1)) if description_match else ""
        image_match = re.search(
            r"data-responsive-src=[\"'](.*?)[\"']",
            card,
            re.I | re.S,
        )
        image = None
        if image_match:
            urls = re.findall(
                r"https?://[^'\"\s,}]+", html.unescape(image_match.group(1))
            )
            image = urls[-1] if urls else None
        item = {
            "@type": "ExhibitionEvent",
            "name": title,
            "description": description,
            "location": {"name": location},
            "url": urllib.parse.urljoin(page_url, html.unescape(link_match.group(1))),
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "image": image,
        }
        record, seen = event_from_item(
            item, venue, page_url, today, window_end, shared_source
        )
        observed += int(seen)
        if record:
            record["confidenceScore"] = 0.92
            records.append(record)
    return records, observed


def parse_xml_events(
    body: bytes,
    page_url: str,
    venue: dict[str, Any],
    today: date,
    window_end: date,
    shared_source: bool,
) -> tuple[list[dict[str, Any]], int]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return [], 0
    records: list[dict[str, Any]] = []
    observed = 0

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    for element in root.iter():
        if local(element.tag) not in {"item", "entry", "event"}:
            continue
        values: dict[str, str] = {}
        for child in element.iter():
            name = local(child.tag)
            if name == "link" and child.attrib.get("href"):
                values.setdefault("link", child.attrib["href"])
            elif child.text and name in {
                "title",
                "link",
                "description",
                "summary",
                "startdate",
                "enddate",
                "start",
                "end",
                "dtstart",
                "dtend",
            }:
                values.setdefault(name, child.text)
        start_value = values.get("startdate") or values.get("start") or values.get("dtstart")
        end_value = values.get("enddate") or values.get("end") or values.get("dtend")
        if not start_value or not end_value:
            continue
        item = {
            "@type": "ExhibitionEvent",
            "name": values.get("title"),
            "description": values.get("description") or values.get("summary"),
            "url": values.get("link"),
            "startDate": start_value,
            "endDate": end_value,
        }
        record, seen = event_from_item(
            item, venue, page_url, today, window_end, shared_source
        )
        observed += int(seen)
        if record:
            record["confidenceScore"] = 0.9
            records.append(record)
    return records, observed


def unfold_ical(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def parse_ical_events(
    text: str,
    page_url: str,
    venue: dict[str, Any],
    today: date,
    window_end: date,
    shared_source: bool,
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    current: dict[str, str] | None = None
    observed = 0
    for line in unfold_ical(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT" and current is not None:
            start = parse_date(current.get("DTSTART"))
            end = parse_date(current.get("DTEND"))
            if (
                start
                and end
                and "VALUE=DATE" in current.get("_DTEND_KEY", "")
                and end > start
            ):
                end -= timedelta(days=1)
            item = {
                "@type": "ExhibitionEvent",
                "name": current.get("SUMMARY"),
                "description": current.get("DESCRIPTION"),
                "url": current.get("URL"),
                "startDate": iso_or_none(start),
                "endDate": iso_or_none(end),
            }
            record, seen = event_from_item(
                item, venue, page_url, today, window_end, shared_source
            )
            observed += int(seen)
            if record:
                record["confidenceScore"] = 0.92
                records.append(record)
            current = None
            continue
        if current is not None and ":" in line:
            raw_key, value = line.split(":", 1)
            key = raw_key.split(";", 1)[0]
            current[key] = value.replace("\\n", " ").replace("\\,", ",")
            current[f"_{key}_KEY"] = raw_key
    return records, observed


def sitemap_links(body: bytes, venue: dict[str, Any], limit: int) -> list[str]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    links: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() != "loc" or not element.text:
            continue
        target = element.text.strip()
        if (
            same_organisation(target, venue.get("website"))
            and DETAIL_PATH_RE.search(urllib.parse.urlparse(target).path)
            and not LISTING_END_RE.search(urllib.parse.urlparse(target).path)
        ):
            links.append(target)
        if len(links) >= limit:
            break
    return links


def dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def merge_missing(
        preferred: dict[str, Any], alternate: dict[str, Any]
    ) -> dict[str, Any]:
        for field in ("imageUrl", "cachedThumbnail", "shortDescription"):
            if not preferred.get(field) and alternate.get(field):
                preferred[field] = alternate[field]
        return preferred

    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = (
            record["venueId"],
            normalized_title(record["title"]),
            record["startDate"],
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = record
        elif record["confidenceScore"] > existing["confidenceScore"]:
            by_key[key] = merge_missing(record, existing)
        else:
            merge_missing(existing, record)
    by_id: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    for record in sorted(
        by_key.values(), key=lambda item: (item["startDate"], item["venueId"], item["title"])
    ):
        base_id = record["id"]
        by_id[base_id] = by_id.get(base_id, 0) + 1
        if by_id[base_id] > 1:
            record["id"] = f"{base_id}-{by_id[base_id]}"
        result.append(record)
    return result


def resolve_cross_venue_duplicates(
    records: list[dict[str, Any]], venues_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep a shared exhibition identity only where branch evidence is unique."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        parsed_source = urllib.parse.urlsplit(clean_text(record.get("sourceUrl")))
        source = urllib.parse.urlunsplit(
            (
                parsed_source.scheme.casefold(),
                parsed_source.netloc.casefold(),
                parsed_source.path.rstrip("/"),
                "",
                "",
            )
        )
        key = (
            source,
            normalized_title(clean_text(record.get("title"))),
            clean_text(record.get("startDate")),
            clean_text(record.get("endDate")),
        )
        groups.setdefault(key, []).append(record)

    accepted: list[dict[str, Any]] = []
    for key, group in groups.items():
        venue_ids = {record["venueId"] for record in group}
        if len(venue_ids) < 2:
            accepted.extend(group)
            continue
        scored: list[tuple[int, dict[str, Any]]] = []
        for record in group:
            evidence = clean_text(
                [
                    record.get("title"),
                    record.get("shortDescription"),
                    urllib.parse.unquote(record.get("sourceUrl", "")),
                    record.get("_branchEvidence"),
                ]
            ).casefold()
            tokens = SITE_TOKENS.get(record["venueId"], ())
            conflicts = SITE_CONFLICT_TOKENS.get(record["venueId"], ())
            score = sum(2 for token in tokens if token in evidence) - sum(
                5 for token in conflicts if token in evidence
            )
            scored.append((score, record))
        best_score = max(score for score, _record in scored)
        winners = [record for score, record in scored if score == best_score and score > 0]
        if len(winners) == 1:
            accepted.append(winners[0])
        winner_id = winners[0]["venueId"] if len(winners) == 1 else None
        for _score, record in scored:
            if winner_id and record["venueId"] == winner_id:
                continue
            venue = venues_by_id.get(record["venueId"])
            if venue:
                reject_candidate(
                    venue,
                    record["title"],
                    record["sourceUrl"],
                    "location-branch-mismatch",
                    "The same exhibition identity mapped to multiple venue branches without explicit multi-branch evidence",
                    f"candidate venues: {', '.join(sorted(venue_ids))}; "
                    f"selected venue: {winner_id or 'none (ambiguous)'}",
                )
    return accepted


def enrich_missing_images(
    records: list[dict[str, Any]], fetcher: RespectfulFetcher
) -> None:
    for record in records:
        if record.get("imageUrl"):
            continue
        source_url = record.get("sourceUrl")
        if not isinstance(source_url, str):
            continue
        page = fetcher.fetch(source_url)
        if not page.ok or (
            "html" not in page.content_type.lower()
            and not page.body.lstrip().startswith(b"<!")
        ):
            continue
        probe = PageProbe(page.url)
        probe.feed(page.text())
        record["imageUrl"] = page_image(probe, page.url)
        if record.get("imageUrl"):
            record["_imageProvenance"] = "exhibition-official"
            continue
        if record.get("venueId") == "hannah-barry-gallery":
            gallery_url = source_url.rstrip("/") + "/?template=gallery"
            gallery = fetcher.fetch(gallery_url)
            if not gallery.ok:
                continue
            match = re.search(
                r'<a[^>]+class=["\'][^"\']*\brsImg\b[^"\']*["\'][^>]+'
                r'href=["\']([^"\']+\.(?:jpe?g|png|webp)(?:\?[^"\']*)?)["\']',
                gallery.text(),
                re.IGNORECASE,
            )
            if match:
                record["imageUrl"] = urllib.parse.quote(
                    html.unescape(match.group(1)), safe=":/?=&%"
                )
                record["_imageProvenance"] = "exhibition-official"


def apply_title_overrides(
    records: list[dict[str, Any]], config: dict[str, Any], today: date, window_end: date
) -> list[dict[str, Any]]:
    overrides = {
        row["sourceUrl"]: row for row in config.get("overrides", [])
    }
    for record in records:
        before = record["title"]
        decision = overrides.get(record["sourceUrl"])
        if decision:
            record["title"] = decision["title"]
            record["id"] = slugify(
                f"{record['venueId']}-{record['title']}-{record['startDate']}"
            )
            record["_titleAudit"] = {
                "titleBeforeOverride": before,
                "reasonCode": "official-title-override",
                "evidence": decision["evidence"],
            }
        else:
            record["_titleAudit"] = {
                "titleBeforeOverride": before,
                "reasonCode": "official-source-title",
                "evidence": "Generated title matches the accepted official source metadata.",
            }
    for item in config.get("supplementalExhibitions", []):
        start = parse_date(item.get("startDate"))
        end = parse_date(item.get("endDate"))
        if not start or not end or start > window_end or end < today:
            continue
        record_id = slugify(
            f"{item['venueId']}-{item['title']}-{item['startDate']}"
        )
        records.append(
            {
                "id": record_id,
                "venueId": item["venueId"],
                "title": item["title"],
                "startDate": item["startDate"],
                "endDate": item["endDate"],
                "shortDescription": clean_text(
                    item.get("shortDescription") or item.get("description"), 280
                ),
                "imageUrl": item.get("imageUrl"),
                "cachedThumbnail": None,
                "sourceUrl": item["sourceUrl"],
                "priceStatus": item.get("priceStatus", "unknown"),
                "confidenceScore": item.get("confidenceScore", 0.8),
                "lastVerified": today.isoformat(),
                "accent": accent_for(record_id),
                "_branchEvidence": clean_text(item.get("branchEvidence")),
                "_titleAudit": {
                    "titleBeforeOverride": None,
                    "reasonCode": "official-listing-supplement",
                    "evidence": item["evidence"],
                },
            }
        )
    return dedupe_records(records)


def apply_description_overrides(
    records: list[dict[str, Any]], config: dict[str, Any]
) -> None:
    overrides = {
        row["sourceUrl"]: row for row in config.get("overrides", [])
    }
    for record in records:
        before = clean_text(record.get("shortDescription"))
        decision = overrides.get(record["sourceUrl"])
        if decision:
            record["shortDescription"] = clean_text(decision["description"], 280)
            record["_descriptionAudit"] = {
                "descriptionBeforeOverride": before,
                "reasonCode": "official-description-override",
                "evidence": decision["evidence"],
            }
        else:
            record["_descriptionAudit"] = {
                "descriptionBeforeOverride": before,
                "reasonCode": (
                    "official-source-description"
                    if before
                    else "missing-official-description"
                ),
                "evidence": (
                    "Description extracted from official exhibition metadata."
                    if before
                    else "No concise exhibition-specific description was reliably extracted."
                ),
            }


def apply_price_overrides(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    venues: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    venue_policies = config.get("venuePolicies", {})
    exhibition_overrides = config.get("exhibitionOverrides", {})
    audits: list[dict[str, Any]] = []
    for record in records:
        before = record["priceStatus"]
        decision = exhibition_overrides.get(record["sourceUrl"])
        scope = "exhibition"
        evidence_url = record["sourceUrl"]
        if not decision:
            decision = venue_policies.get(record["venueId"])
            scope = "venue-policy"
            evidence_url = (decision or {}).get("sourceUrl", record["sourceUrl"])
        if decision and decision["priceStatus"] in {"free", "paid"}:
            record["priceStatus"] = decision["priceStatus"]
            reason_code = (
                "official-free-admission"
                if decision["priceStatus"] == "free"
                else "official-paid-admission"
                if decision["priceStatus"] == "paid"
                else "no-explicit-admission-evidence"
            )
            evidence = decision["evidence"]
            verified_at = decision.get("verifiedAt")
            price_confidence = 0.99
        elif (
            venues.get(record["venueId"], {}).get("type") == "independent"
            and (not decision or decision["priceStatus"] == "unknown")
            and (
                before == "unknown"
                or bool(decision and decision["priceStatus"] == "unknown")
            )
        ):
            record["priceStatus"] = "free"
            reason_code = "user-policy-independent-default-free"
            evidence = (
                "User policy defaults independent venues to free when no official paid "
                "admission, ticket restriction, or members-only evidence is present."
            )
            verified_at = record["lastVerified"]
            scope = "user-policy"
            evidence_url = record["sourceUrl"]
            price_confidence = 0.65
        else:
            if decision and decision["priceStatus"] == "unknown":
                record["priceStatus"] = "unknown"
            reason_code = (
                "source-price-extracted"
                if record["priceStatus"] != "unknown"
                else "no-explicit-admission-evidence"
            )
            evidence = (
                "Price status extracted from the official exhibition page."
                if record["priceStatus"] != "unknown"
                else "Official exhibition page and verified venue policies provide no explicit admission price evidence."
            )
            verified_at = record["lastVerified"]
            scope = "source-page"
            price_confidence = 0.85 if record["priceStatus"] != "unknown" else 0.4
        audits.append(
            {
                "exhibitionId": record["id"],
                "venueId": record["venueId"],
                "title": record["title"],
                "sourceUrl": record["sourceUrl"],
                "priceStatusBeforeOverride": before,
                "priceStatus": record["priceStatus"],
                "reasonCode": reason_code,
                "evidenceScope": scope,
                "evidenceUrl": evidence_url,
                "evidence": evidence,
                "verifiedAt": verified_at,
                "confidenceScore": price_confidence,
            }
        )
    return audits


def source_is_shared(venue: dict[str, Any], source_counts: dict[str, int]) -> bool:
    source = venue.get("whatsOnUrl")
    return bool(source and source_counts.get(source.rstrip("/"), 0) > 1)


def scrape_venue(
    venue: dict[str, Any],
    fetcher: RespectfulFetcher,
    today: date,
    window_end: date,
    max_details: int,
    source_counts: dict[str, int],
) -> dict[str, Any]:
    attempted_at = datetime.now(timezone.utc).isoformat()
    base_coverage = {
        "venueId": venue["id"],
        "name": venue["name"],
        "windowStart": today.isoformat(),
        "windowEnd": window_end.isoformat(),
        "windowKind": WINDOW_KIND,
        "status": "failed",
        "attemptedAt": attempted_at,
        "lastSuccess": None,
        "showCount": 0,
        "freshShowCount": 0,
        "sourceUrl": venue.get("whatsOnUrl"),
        "httpStatus": None,
        "robotsAllowed": None,
        "extractionMethods": [],
        "reviewStatus": venue.get("reviewStatus"),
        "error": None,
    }
    review_status = venue.get("reviewStatus")
    if venue.get("scrapeMethod") == "link-only" or not venue.get("whatsOnUrl"):
        status = (
            "unresolved"
            if review_status == "unverified"
            else review_status or "link-only"
        )
        base_coverage.update(
            {
                "status": status,
                "error": venue.get("sourceNote") or "No scrapeable official source",
            }
        )
        return {"coverage": base_coverage, "records": [], "metadata": {}}
    if is_instagram(venue.get("whatsOnUrl")):
        base_coverage.update(
            {
                "status": "instagram-only",
                "error": "Instagram is intentionally not scraped",
            }
        )
        return {"coverage": base_coverage, "records": [], "metadata": {}}

    shared_source = source_is_shared(venue, source_counts)
    detail_limit = (
        max(max_details, 30)
        if venue["id"] in STRICT_BRANCH_PATH_VENUES
        else max_details
    )
    listing = fetcher.fetch(venue["whatsOnUrl"])
    base_coverage["httpStatus"] = listing.status
    robots_allowed, robots_reason, _ = fetcher.robots_decision(venue["whatsOnUrl"])
    base_coverage["robotsAllowed"] = robots_allowed
    if listing.blocked:
        base_coverage.update({"status": "blocked", "error": listing.error or robots_reason})
        return {"coverage": base_coverage, "records": [], "metadata": {}}
    if not listing.ok:
        base_coverage.update({"status": "failed", "error": listing.error})
        return {"coverage": base_coverage, "records": [], "metadata": {}}

    records: list[dict[str, Any]] = []
    observed = 0
    extraction_methods: set[str] = set()
    metadata: dict[str, Any] = {}
    detail_links: list[str] = []
    info_links: list[str] = []
    content_type = listing.content_type.lower()
    if "html" in content_type or listing.body.lstrip().startswith(b"<!"):
        probe = PageProbe(listing.url)
        probe.feed(listing.text())
        ld_values = parse_json_ld(probe)
        if ld_values:
            extraction_methods.add("json-ld")
        metadata.update(metadata_from_probe(ld_values, probe, listing.url))
        for value in ld_values:
            for item in walk_objects(value):
                record, seen = event_from_item(
                    item, venue, listing.url, today, window_end, shared_source
                )
                observed += int(seen)
                if record:
                    records.append(record)
        artlogic_records, artlogic_observed = parse_artlogic_listing(
            listing.text(),
            listing.url,
            venue,
            today,
            window_end,
            shared_source,
        )
        if artlogic_observed:
            extraction_methods.add("artlogic-static-html")
            records.extend(artlogic_records)
            observed += artlogic_observed
        detail_links.extend(candidate_detail_links(probe, venue, detail_limit))
        info_links.extend(candidate_info_links(probe, venue))
        structured_links = list(dict.fromkeys(probe.feed_links + probe.calendar_links))
        for target in structured_links[:3]:
            feed = fetcher.fetch(target)
            if not feed.ok:
                continue
            if target.lower().endswith((".ics", ".ical")) or "calendar" in feed.content_type.lower():
                found, count = parse_ical_events(
                    feed.text(), feed.url, venue, today, window_end, shared_source
                )
                extraction_methods.add("ical")
            else:
                found, count = parse_xml_events(
                    feed.body, feed.url, venue, today, window_end, shared_source
                )
                extraction_methods.add("feed")
            records.extend(found)
            observed += count
    elif "calendar" in content_type or listing.url.lower().endswith((".ics", ".ical")):
        records, observed = parse_ical_events(
            listing.text(), listing.url, venue, today, window_end, shared_source
        )
        extraction_methods.add("ical")
    else:
        records, observed = parse_xml_events(
            listing.body, listing.url, venue, today, window_end, shared_source
        )
        extraction_methods.add("feed")

    if len(detail_links) < detail_limit:
        for sitemap_url in fetcher.sitemaps_for(venue["whatsOnUrl"])[:2]:
            sitemap = fetcher.fetch(sitemap_url)
            if sitemap.ok:
                extraction_methods.add("sitemap")
                detail_links.extend(
                    sitemap_links(
                        sitemap.body,
                        venue,
                        detail_limit - len(detail_links),
                    )
                )
    detail_links = list(dict.fromkeys(detail_links))[:detail_limit]
    blocked_details = 0
    for target in detail_links:
        detail = fetcher.fetch(target)
        if detail.blocked:
            blocked_details += 1
            continue
        if not detail.ok:
            continue
        probe = PageProbe(detail.url)
        probe.feed(detail.text())
        values = parse_json_ld(probe)
        if values:
            extraction_methods.add("detail-json-ld")
        detail_metadata = metadata_from_probe(values, probe, detail.url)
        for key, value in detail_metadata.items():
            metadata.setdefault(key, value)
        detail_observed_before = observed
        detail_record_count_before = len(records)
        for value in values:
            for item in walk_objects(value):
                record, seen = event_from_item(
                    item, venue, detail.url, today, window_end, shared_source
                )
                observed += int(seen)
                if record:
                    records.append(record)
        detail_records = records[detail_record_count_before:]
        if observed == detail_observed_before or (
            detail_records
            and all(
                record["startDate"] == record["endDate"]
                for record in detail_records
            )
        ):
            record, seen = generic_page_event(
                probe, venue, detail.url, today, window_end, shared_source
            )
            observed += int(seen)
            if record:
                extraction_methods.add("html-time")
                records.append(record)

    if not (metadata.get("address") and metadata.get("postcode")):
        website = venue.get("website")
        targets: list[str] = []
        if website and website.rstrip("/") != venue["whatsOnUrl"].rstrip("/"):
            targets.append(website)
        targets.extend(info_links)
        visited: set[str] = set()
        for target in targets[:4]:
            if target in visited:
                continue
            visited.add(target)
            page = fetcher.fetch(target)
            if not page.ok or "html" not in page.content_type.lower():
                continue
            info_probe = PageProbe(page.url)
            info_probe.feed(page.text())
            info_values = parse_json_ld(info_probe)
            info_metadata = metadata_from_probe(
                info_values, info_probe, page.url
            )
            for key, value in info_metadata.items():
                metadata.setdefault(key, value)
            if page.url == website or target == website:
                for candidate in candidate_info_links(info_probe, venue):
                    if candidate not in visited:
                        info_links.append(candidate)
            if metadata.get("address") and metadata.get("postcode"):
                break
        if not (metadata.get("address") and metadata.get("postcode")):
            for target in info_links[:3]:
                if target in visited:
                    continue
                visited.add(target)
                page = fetcher.fetch(target)
                if not page.ok or "html" not in page.content_type.lower():
                    continue
                info_probe = PageProbe(page.url)
                info_probe.feed(page.text())
                info_metadata = metadata_from_probe(
                    parse_json_ld(info_probe), info_probe, page.url
                )
                for key, value in info_metadata.items():
                    metadata.setdefault(key, value)
                if metadata.get("address") and metadata.get("postcode"):
                    break

    records = dedupe_records(records)
    if records:
        status = "success"
    elif observed:
        status = "no-current-shows"
    elif detail_links and blocked_details == len(detail_links):
        status = "blocked"
    else:
        status = "unresolved"
    error = None
    if status == "unresolved":
        error = (
            f"Fetched official listing {listing.url}; examined {len(detail_links)} "
            "official detail link(s), structured metadata, feeds and declared "
            "sitemaps where available, but found no verifiable dated exhibition item"
        )
    elif status == "blocked":
        error = "Linked exhibition pages were blocked; no bypass attempted"
    base_coverage.update(
        {
            "status": status,
            "lastSuccess": today.isoformat()
            if status in {"success", "no-current-shows"}
            else None,
            "showCount": len(records),
            "freshShowCount": len(records),
            "extractionMethods": sorted(extraction_methods),
            "error": error,
        }
    )
    if metadata.get("openingHours"):
        metadata["hoursLastChecked"] = today.isoformat()
    return {"coverage": base_coverage, "records": records, "metadata": metadata}


def area_for_postcode(postcode: str | None) -> str | None:
    if not postcode:
        return None
    outward = postcode.upper().split()[0]
    if outward.startswith("SE1"):
        return "South Bank & Bankside"
    if outward.startswith(("SW7", "W6", "W8", "W11", "W14")):
        return "South Kensington & West"
    if outward.startswith(("E15", "E20", "E10", "E11", "E17")):
        return "Stratford & East"
    if outward.startswith(("EC", "E1", "E2", "E3", "E5", "E8", "E9", "N1")):
        return "City & East"
    if outward.startswith(("WC", "W1", "NW1")):
        return "Central"
    if outward.startswith(("NW", "N")):
        return "North"
    if outward.startswith("SE"):
        return "South East"
    if outward.startswith("SW"):
        return "South West & Lambeth"
    if outward.startswith("W"):
        return "South Kensington & West"
    return None


def postcode_lookup(
    postcode: str, fetcher: RespectfulFetcher
) -> dict[str, Any] | None:
    encoded = urllib.parse.quote(postcode)
    result = fetcher.fetch(f"https://api.postcodes.io/postcodes/{encoded}")
    if not result.ok:
        return None
    try:
        payload = json.loads(result.text())
        data = payload.get("result") or {}
        float(data["latitude"])
        float(data["longitude"])
        return data
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def geocode_postcode(
    postcode: str, fetcher: RespectfulFetcher
) -> dict[str, float] | None:
    data = postcode_lookup(postcode, fetcher)
    if not data:
        return None
    lat = float(data["latitude"])
    lng = float(data["longitude"])
    if 51.1 <= lat <= 51.8 and -0.7 <= lng <= 0.4:
        return {"lat": round(lat, 6), "lng": round(lng, 6)}
    return None


def merge_non_null(*sources: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source in sources:
        for key, value in source.items():
            if value is not None:
                result[key] = value
    return result


def valid_street_address(value: Any) -> bool:
    address = clean_text(value)
    if not address:
        return False
    if re.search(r"\b(null|undefined|unknown|n/?a|tbc|placeholder)\b", address, re.I):
        return False
    if POSTCODE_RE.fullmatch(address):
        return False
    if FOREIGN_LOCATION_RE.search(address):
        return False
    return bool(re.search(r"[A-Za-z]", address))


def venue_output_record(
    seed: dict[str, Any],
    previous: dict[str, Any],
    discovered: dict[str, Any],
    override: dict[str, Any],
    coverage: dict[str, Any],
    fetcher: RespectfulFetcher,
) -> dict[str, Any]:
    merged = merge_non_null(seed, previous, discovered, override)
    postcode = merged.get("postcode")
    lookup = postcode_lookup(postcode, fetcher) if postcode else None
    postcode_london_verified = bool(
        lookup
        and str(lookup.get("region", "")).casefold() == "london"
        and str(lookup.get("country", "")).casefold() == "england"
    )
    address = merged.get("address")
    london_verified = bool(postcode_london_verified and valid_street_address(address))
    coordinates = None
    if london_verified and lookup:
        coordinates = {
            "lat": round(float(lookup["latitude"]), 6),
            "lng": round(float(lookup["longitude"]), 6),
        }
    if not london_verified:
        address = None
        postcode = None
    area = (merged.get("area") or area_for_postcode(postcode)) if london_verified else None
    status = coverage["status"]
    scrape_method = seed.get("scrapeMethod", "link-only")
    if status in {
        "blocked",
        "failed",
        "ambiguous",
        "closed",
        "instagram-only",
        "unverified",
        "unresolved",
        "temporarily-closed-unverified",
        "location-closed-unverified",
    }:
        scrape_method = "link-only"
    return {
        "id": seed["id"],
        "name": seed["name"],
        "type": seed["type"],
        "address": address,
        "postcode": postcode if london_verified else None,
        "coordinates": coordinates,
        "area": area,
        "website": seed.get("website"),
        "whatsOnUrl": seed.get("whatsOnUrl"),
        "openingHours": merged.get("openingHours"),
        "hoursLastChecked": merged.get("hoursLastChecked"),
        "scrapeMethod": scrape_method,
        "lastSuccessfulScrape": coverage.get("lastSuccess"),
        "priorityRank": PRIORITY_RANK.get(seed["id"]),
        "_locationVerified": london_verified,
        "_addressSourceUrl": (
            override.get("addressSourceUrl")
            or discovered.get("addressSourceUrl")
            or seed.get("website")
            or seed.get("whatsOnUrl")
        ),
        "_previousAddress": previous.get("address"),
        "_previousPostcode": previous.get("postcode"),
        "_locationEvidence": (
            f"Official venue address {clean_text(address)}, {format_postcode(postcode)}; "
            f"postcode resolves to {lookup.get('admin_district')}, {lookup.get('region')}"
            if london_verified and lookup
            else "No complete official street address and postcode were verified to the London region"
        ),
    }


def still_in_window(record: dict[str, Any], today: date, window_end: date) -> bool:
    start = parse_date(record.get("startDate"))
    end = parse_date(record.get("endDate"))
    return bool(start and end and start <= window_end and end >= today and end >= start)


def retained_record_is_eligible(
    record: dict[str, Any],
    venue: dict[str, Any],
    today: date,
    window_end: date,
) -> bool:
    title = clean_text(record.get("title"))
    description = clean_text(record.get("shortDescription"))
    source_url = clean_text(record.get("sourceUrl"))
    return bool(
        still_in_window(record, today, window_end)
        and title
        and not NON_EXHIBITION_RE.search(title)
        and not OUT_OF_SCOPE_TITLE_RE.search(title)
        and not generic_listing_reason(
            title, source_url, description, venue["name"]
        )
    )


def branch_specific_source(venue: dict[str, Any], source_url: str) -> bool:
    whats_on = venue.get("whatsOnUrl")
    if not whats_on:
        return False
    source_path = urllib.parse.urlparse(source_url).path.rstrip("/") + "/"
    branch_path = urllib.parse.urlparse(whats_on).path.rstrip("/") + "/"
    venue_markers = [
        token.replace(" ", "-").replace("&", "and")
        for token in SITE_TOKENS.get(venue["id"], ())
        if len(token) > 4
    ]
    return (
        source_path.startswith(branch_path)
        and any(marker in branch_path.lower() for marker in venue_markers)
    )


def audit_exhibition_location(
    record: dict[str, Any],
    venue: dict[str, Any],
    coverage: dict[str, Any],
    fetcher: RespectfulFetcher,
) -> tuple[bool, str, str]:
    if not coverage.get("locationVerified"):
        return (
            False,
            "venue-location-unverified",
            "Venue lacks an official-source postcode verified to the London region",
        )
    page = fetcher.fetch(record["sourceUrl"])
    if not page.ok:
        return (
            False,
            "event-location-unverifiable",
            f"Official exhibition page could not be read: {page.error or page.status}",
        )
    probe = PageProbe(page.url)
    probe.feed(page.text())
    values = parse_json_ld(probe)
    event_locations: list[str] = []
    for value in values:
        for item in walk_objects(value):
            if any(entry.endswith("event") for entry in type_names(item)):
                location = item.get("location")
                if location:
                    event_locations.append(
                        clean_text(json.dumps(location, ensure_ascii=False, default=str))
                    )
    location_blob = " ".join(event_locations)
    page_title = clean_text(probe.meta.get("og:title") or probe.title, 300)
    page_text = probe.text[:500_000]
    title_london = bool(re.search(r"\bLondon\b", page_title, re.IGNORECASE))
    location_london = bool(
        re.search(r"\bLondon\b", location_blob, re.IGNORECASE)
        or london_postcodes_in(location_blob)
    )
    branch_london = branch_specific_source(venue, record["sourceUrl"])
    assigned_london = bool(LONDON_ASSIGNMENT_RE.search(page_text[:120_000]))
    item_branch_evidence = clean_text(record.get("_branchEvidence"))
    item_branch_london = bool(
        re.search(r"\bLondon\b", item_branch_evidence, re.IGNORECASE)
        and not FOREIGN_LOCATION_RE.search(item_branch_evidence)
        and matches_venue_site(
            venue["id"], item_branch_evidence, record["sourceUrl"]
        )
    )
    strong_london = (
        title_london
        or location_london
        or branch_london
        or assigned_london
        or item_branch_london
    )
    weak_london = bool(
        re.search(r"\bLondon\b", page_text, re.IGNORECASE)
        or london_postcodes_in(page_text)
    )
    foreign_title = FOREIGN_LOCATION_RE.search(page_title)
    foreign_location = FOREIGN_LOCATION_RE.search(location_blob)
    foreign_source = FOREIGN_LOCATION_RE.search(
        urllib.parse.unquote(record["sourceUrl"])
    )
    if (foreign_title or foreign_location or foreign_source) and not (
        title_london or location_london or branch_london
    ):
        evidence_match = foreign_title or foreign_location or foreign_source
        assert evidence_match is not None
        evidence = evidence_match.group(0)
        return (
            False,
            "non-london-location",
            f"Official event title/location assigns the exhibition to {evidence}, not London",
        )
    if venue["id"] in MULTI_LOCATION_VENUES and not strong_london:
        return (
            False,
            "missing-london-branch-evidence",
            "Multi-location gallery page does not explicitly assign this exhibition to London",
        )
    if not strong_london and not weak_london:
        return (
            False,
            "missing-london-event-evidence",
            "Official exhibition page contains no explicit London location or London postcode",
        )
    evidence_parts = []
    if title_london:
        evidence_parts.append(f"page title: {page_title}")
    if location_london:
        evidence_parts.append(f"structured location: {clean_text(location_blob, 180)}")
    if branch_london:
        evidence_parts.append("official location-specific branch URL")
    if assigned_london:
        evidence_parts.append("page text explicitly assigns the event to London")
    if item_branch_london:
        evidence_parts.append("item-scoped official listing assigns the exhibition to London")
    if not evidence_parts:
        postcodes = london_postcodes_in(page_text)
        evidence_parts.append(
            f"official page London evidence: {postcodes[0] if postcodes else 'London'}"
        )
    return True, "verified-london", "; ".join(evidence_parts)


def dedupe_rejections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("venueId"),
            normalized_title(row.get("title") or ""),
            row.get("sourceUrl"),
            row.get("reasonCode"),
            row.get("evidence"),
        )
        unique[key] = row
    return sorted(
        unique.values(),
        key=lambda row: (
            PRIORITY_RANK.get(row["venueId"], 10_000),
            row["venueId"],
            row.get("title") or "",
            row["reasonCode"],
        ),
    )


def emit_typescript(venues: list[dict[str, Any]], exhibitions: list[dict[str, Any]]) -> None:
    venue_json = json.dumps(venues, ensure_ascii=False, indent=2)
    exhibition_json = json.dumps(exhibitions, ensure_ascii=False, indent=2)
    VENUES_TS_PATH.write_text(
        'import type { Venue } from "../types";\n\n'
        "/** Generated by scripts/ingest.py. Edit data/venue-seed.json or "
        "data/venue-overrides.json instead. */\n"
        f"export const venues: Venue[] = {venue_json};\n",
        encoding="utf-8",
    )
    EXHIBITIONS_TS_PATH.write_text(
        'import type { Exhibition } from "../types";\n\n'
        "/** Generated from official venue sources by scripts/ingest.py. */\n"
        f"export const exhibitions: Exhibition[] = {exhibition_json};\n",
        encoding="utf-8",
    )


def write_coverage_csv(rows: list[dict[str, Any]]) -> None:
    fields = [
        "venueId",
        "name",
        "status",
        "windowStart",
        "windowEnd",
        "windowKind",
        "priorityRank",
        "locationVerified",
        "locationEvidence",
        "lastSuccess",
        "showCount",
        "freshShowCount",
        "freeShowCount",
        "paidShowCount",
        "unknownPriceShowCount",
        "rejectedNonLondonCount",
        "attemptedAt",
        "sourceUrl",
        "httpStatus",
        "robotsAllowed",
        "extractionMethods",
        "reviewStatus",
        "statusEvidence",
        "error",
    ]
    with COVERAGE_CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat["extractionMethods"] = "|".join(row.get("extractionMethods", []))
            writer.writerow({key: flat.get(key) for key in fields})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        help="Window start in YYYY-MM-DD form (default: today in Europe/London)",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--max-details", type=int, default=20)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--no-retain",
        action="store_true",
        help="Do not retain previously verified records for failed venues",
    )
    parser.add_argument(
        "--venue",
        action="append",
        default=[],
        help="Only process the named venue id (repeatable; mainly for diagnostics)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with REJECTIONS_LOCK:
        REJECTIONS.clear()
    today = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(ZoneInfo("Europe/London")).date()
    )
    window_end = add_calendar_months(today)
    seed_payload = read_json(SEED_PATH, {})
    seeds: list[dict[str, Any]] = seed_payload.get("venues", [])
    if args.venue:
        selected = set(args.venue)
        seeds = [venue for venue in seeds if venue["id"] in selected]
        missing = selected - {venue["id"] for venue in seeds}
        if missing:
            print(f"Unknown venue ids: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    overrides = read_json(OVERRIDES_PATH, {}).get("venues", {})
    price_overrides = read_json(PRICE_OVERRIDES_PATH, {})
    title_overrides = read_json(TITLE_OVERRIDES_PATH, {})
    description_overrides = read_json(DESCRIPTION_OVERRIDES_PATH, {})
    previous_venues = {
        venue["id"]: venue for venue in read_json(VENUES_JSON_PATH, [])
    }
    previous_exhibitions: list[dict[str, Any]] = read_json(EXHIBITIONS_JSON_PATH, [])
    previous_coverage = {
        row["venueId"]: row for row in read_json(COVERAGE_JSON_PATH, [])
    }
    source_counts: dict[str, int] = {}
    for venue in seeds:
        if venue.get("whatsOnUrl"):
            key = venue["whatsOnUrl"].rstrip("/")
            source_counts[key] = source_counts.get(key, 0) + 1

    fetcher = RespectfulFetcher(args.delay, args.refresh)
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                scrape_venue,
                venue,
                fetcher,
                today,
                window_end,
                max(0, args.max_details),
                source_counts,
            ): venue
            for venue in seeds
        }
        for future in as_completed(futures):
            venue = futures[future]
            try:
                results[venue["id"]] = future.result()
            except Exception as error:  # keep one broken venue from losing the run
                results[venue["id"]] = {
                    "records": [],
                    "metadata": {},
                    "coverage": {
                        "venueId": venue["id"],
                        "name": venue["name"],
                        "windowStart": today.isoformat(),
                        "windowEnd": window_end.isoformat(),
                        "windowKind": WINDOW_KIND,
                        "status": "failed",
                        "attemptedAt": datetime.now(timezone.utc).isoformat(),
                        "lastSuccess": None,
                        "showCount": 0,
                        "freshShowCount": 0,
                        "sourceUrl": venue.get("whatsOnUrl"),
                        "httpStatus": None,
                        "robotsAllowed": None,
                        "extractionMethods": [],
                        "reviewStatus": venue.get("reviewStatus"),
                        "error": f"{type(error).__name__}: {error}",
                    },
                }

    all_records: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    venue_rows: list[dict[str, Any]] = []
    previous_by_venue: dict[str, list[dict[str, Any]]] = {}
    seed_by_id_for_retention = {seed["id"]: seed for seed in seeds}
    for record in previous_exhibitions:
        venue = seed_by_id_for_retention.get(record.get("venueId"))
        if not venue:
            continue
        if retained_record_is_eligible(record, venue, today, window_end):
            previous_by_venue.setdefault(record["venueId"], []).append(record)
            continue
        generic_reason = generic_listing_reason(
            clean_text(record.get("title")),
            clean_text(record.get("sourceUrl")),
            clean_text(record.get("shortDescription")),
            venue["name"],
        )
        if generic_reason:
            reject_candidate(
                venue,
                clean_text(record.get("title")),
                clean_text(record.get("sourceUrl")),
                "generic-listing-not-exhibition",
                generic_reason,
                clean_text(record.get("shortDescription"))
                or clean_text(record.get("title")),
            )

    for seed in seeds:
        result = results[seed["id"]]
        coverage = result["coverage"]
        prior_coverage = previous_coverage.get(seed["id"], {})
        successful = coverage["status"] in {"success", "no-current-shows"}
        if not coverage.get("lastSuccess") and not args.no_retain:
            coverage["lastSuccess"] = prior_coverage.get("lastSuccess")
        records = result["records"]
        verified_zero = seed.get("verifiedZero", {})
        if (
            not records
            and verified_zero.get("windowStart") == today.isoformat()
            and verified_zero.get("windowEnd") == window_end.isoformat()
        ):
            coverage["status"] = "no-current-shows"
            coverage["lastSuccess"] = today.isoformat()
            coverage["error"] = None
            coverage["statusEvidence"] = verified_zero["evidence"]
            coverage["extractionMethods"] = sorted(
                set(coverage.get("extractionMethods", []))
                | {"browser-rendered-official"}
            )
            successful = True
        if not successful:
            retained = [] if args.no_retain else previous_by_venue.get(seed["id"], [])
            records = retained
            coverage["showCount"] = len(retained)
            if retained:
                coverage["error"] = (
                    (coverage.get("error") or "Refresh did not verify current data")
                    + f"; retained {len(retained)} previously verified record(s)"
                )
        all_records.extend(records)
        coverage_rows.append(coverage)
        venue_rows.append(
            venue_output_record(
                seed,
                previous_venues.get(seed["id"], {}),
                result["metadata"],
                overrides.get(seed["id"], {}),
                coverage,
                fetcher,
            )
        )

    all_records = dedupe_records(all_records)
    all_records = resolve_cross_venue_duplicates(
        all_records, {seed["id"]: seed for seed in seeds}
    )
    all_records = apply_title_overrides(
        all_records, title_overrides, today, window_end
    )
    all_records = [
        normalize_title_site_affixes(record, seed_by_id_for_retention[record["venueId"]])
        for record in all_records
    ]
    all_records = resolve_cross_venue_duplicates(
        all_records, {seed["id"]: seed for seed in seeds}
    )
    apply_description_overrides(all_records, description_overrides)
    coverage_by_id = {row["venueId"]: row for row in coverage_rows}
    venue_by_id = {row["id"]: row for row in venue_rows}
    occurrence_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in all_records:
        key = (
            record["venueId"],
            normalized_title(record["title"]),
            record["sourceUrl"],
        )
        occurrence_groups.setdefault(key, []).append(record)
    recurring_ids: set[str] = set()
    for records in occurrence_groups.values():
        if len(records) < 2:
            continue
        ranged_records = [
            record
            for record in records
            if record["startDate"] != record["endDate"]
        ]
        occurrence_records = [
            record
            for record in records
            if record["startDate"] == record["endDate"]
        ]
        if ranged_records:
            removable = occurrence_records
            reason = "Daily occurrence duplicates were replaced by the verified exhibition date range"
        elif len(occurrence_records) > 1:
            removable = occurrence_records
            reason = "Daily occurrence dates do not establish the exhibition's full run"
        else:
            continue
        for record in removable:
            recurring_ids.add(record["id"])
            reject_candidate(
                venue_by_id[record["venueId"]],
                record["title"],
                record["sourceUrl"],
                "recurring-occurrence-not-exhibition-range",
                reason,
                f"{record['startDate']} occurrence",
            )
    all_records = [
        record for record in all_records if record["id"] not in recurring_ids
    ]
    venue_audits: list[dict[str, Any]] = []
    address_audits: list[dict[str, Any]] = []
    for venue in venue_rows:
        coverage = coverage_by_id[venue["id"]]
        location_verified = bool(venue.pop("_locationVerified"))
        address_source_url = venue.pop("_addressSourceUrl")
        previous_address = venue.pop("_previousAddress")
        previous_postcode = venue.pop("_previousPostcode")
        location_evidence = str(venue.pop("_locationEvidence"))
        coverage["priorityRank"] = venue["priorityRank"]
        coverage["locationVerified"] = location_verified
        coverage["locationEvidence"] = location_evidence
        venue_audits.append(
            {
                "venueId": venue["id"],
                "name": venue["name"],
                "priorityRank": venue["priorityRank"],
                "accepted": location_verified,
                "reasonCode": (
                    "verified-london-venue"
                    if location_verified
                    else "venue-location-unverified"
                ),
                "evidence": location_evidence,
                "postcode": venue["postcode"],
                "coordinates": venue["coordinates"],
            }
        )
        address_audits.append(
            {
                "venueId": venue["id"],
                "name": venue["name"],
                "priorityRank": venue["priorityRank"],
                "status": (
                    "verified-official-london-address"
                    if location_verified
                    else "unresolved-official-address"
                ),
                "accepted": location_verified,
                "address": venue["address"],
                "postcode": venue["postcode"],
                "coordinates": venue["coordinates"],
                "sourceUrl": address_source_url,
                "evidence": location_evidence,
                "previousAddress": previous_address,
                "previousPostcode": previous_postcode,
            }
        )

    accepted_records: list[dict[str, Any]] = []
    exhibition_audits: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        audit_futures = {
            executor.submit(
                audit_exhibition_location,
                record,
                venue_by_id[record["venueId"]],
                coverage_by_id[record["venueId"]],
                fetcher,
            ): record
            for record in all_records
        }
        for future in as_completed(audit_futures):
            record = audit_futures[future]
            venue = venue_by_id[record["venueId"]]
            try:
                accepted, reason_code, evidence = future.result()
            except Exception as error:
                accepted = False
                reason_code = "event-location-audit-failed"
                evidence = f"{type(error).__name__}: {error}"
            exhibition_audits.append(
                {
                    "exhibitionId": record["id"],
                    "venueId": record["venueId"],
                    "title": record["title"],
                    "sourceUrl": record["sourceUrl"],
                    "accepted": accepted,
                    "reasonCode": reason_code,
                    "evidence": evidence,
                }
            )
            if accepted:
                accepted_records.append(record)
            else:
                reject_candidate(
                    venue,
                    record["title"],
                    record["sourceUrl"],
                    reason_code,
                    "Rejected by the London location audit",
                    evidence,
                )
    all_records = dedupe_records(accepted_records)
    enrich_missing_images(all_records, fetcher)
    title_audits: list[dict[str, Any]] = []
    description_audits: list[dict[str, Any]] = []
    for record in all_records:
        record.pop("_branchEvidence", None)
        description_audit = record.pop(
            "_descriptionAudit",
            {
                "descriptionBeforeOverride": record.get("shortDescription", ""),
                "reasonCode": (
                    "official-source-description"
                    if record.get("shortDescription")
                    else "missing-official-description"
                ),
                "evidence": "Description state retained after deduplication.",
            },
        )
        description_audits.append(
            {
                "exhibitionId": record["id"],
                "venueId": record["venueId"],
                "title": record["title"],
                "description": record.get("shortDescription", ""),
                "descriptionBeforeOverride": description_audit[
                    "descriptionBeforeOverride"
                ],
                "sourceUrl": record["sourceUrl"],
                "reasonCode": description_audit["reasonCode"],
                "evidence": description_audit["evidence"],
                "verifiedAt": today.isoformat(),
            }
        )
        audit = record.pop(
            "_titleAudit",
            {
                "titleBeforeOverride": record["title"],
                "reasonCode": "official-source-title",
                "evidence": "Generated title matches the accepted official source metadata.",
            },
        )
        title_audits.append(
            {
                "exhibitionId": record["id"],
                "venueId": record["venueId"],
                "title": record["title"],
                "titleBeforeOverride": audit["titleBeforeOverride"],
                "sourceUrl": record["sourceUrl"],
                "reasonCode": audit["reasonCode"],
                "evidence": audit["evidence"],
                "verifiedAt": today.isoformat(),
            }
        )
    price_audits = apply_price_overrides(
        all_records, price_overrides, venue_by_id
    )

    rejection_rows = dedupe_rejections(REJECTIONS)
    location_rejection_codes = {
        "non-london-location",
        "location-branch-mismatch",
        "missing-london-branch-evidence",
        "missing-london-event-evidence",
        "venue-location-unverified",
        "event-location-unverifiable",
        "event-location-audit-failed",
    }
    explicit_non_london_codes = {
        "non-london-location",
        "location-branch-mismatch",
        "missing-london-branch-evidence",
    }
    accepted_by_venue: dict[str, int] = {}
    for record in all_records:
        accepted_by_venue[record["venueId"]] = (
            accepted_by_venue.get(record["venueId"], 0) + 1
        )
    for coverage in coverage_rows:
        venue_id = coverage["venueId"]
        show_count = accepted_by_venue.get(venue_id, 0)
        venue_records = [
            record for record in all_records if record["venueId"] == venue_id
        ]
        coverage["showCount"] = show_count
        coverage["freshShowCount"] = show_count
        coverage["freeShowCount"] = sum(
            record["priceStatus"] == "free" for record in venue_records
        )
        coverage["paidShowCount"] = sum(
            record["priceStatus"] == "paid" for record in venue_records
        )
        coverage["unknownPriceShowCount"] = sum(
            record["priceStatus"] == "unknown" for record in venue_records
        )
        coverage["rejectedNonLondonCount"] = sum(
            1
            for row in rejection_rows
            if row["venueId"] == venue_id
            and row["reasonCode"] in location_rejection_codes
        )
        if show_count:
            coverage["status"] = "success"
        elif coverage["status"] in {"success", "no-current-shows"}:
            coverage["status"] = (
                "no-current-shows"
                if coverage["locationVerified"]
                and not coverage.get("freshShowCount", 0)
                else "unresolved"
            )
            if coverage["status"] == "unresolved":
                coverage["error"] = (
                    f"Official-source extraction found {coverage.get('freshShowCount', 0)} "
                    "candidate record(s), but none passed the London venue/address and "
                    "event-location audits; see location-audit.json and rejections.json"
                )
        if not coverage["locationVerified"]:
            venue_by_id[venue_id]["scrapeMethod"] = "link-only"

    coverage_rows.sort(
        key=lambda row: (
            row.get("priorityRank") or 10_000,
            row["name"].casefold(),
        )
    )
    venue_rows.sort(
        key=lambda row: (
            row.get("priorityRank") or 10_000,
            row["name"].casefold(),
        )
    )
    exhibition_audits.sort(
        key=lambda row: (
            PRIORITY_RANK.get(row["venueId"], 10_000),
            row["venueId"],
            row["title"],
        )
    )
    status_counts: dict[str, int] = {}
    for row in coverage_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    successful_scrapes = sum(
        status_counts.get(status, 0) for status in ("success", "no-current-shows")
    )
    link_only_or_problem = len(coverage_rows) - successful_scrapes
    active_venue_ids = {record["venueId"] for record in all_records}
    active_venues = [venue for venue in venue_rows if venue["id"] in active_venue_ids]
    priority_active_groups = sum(
        any(venue_id in active_venue_ids for venue_id in group)
        for group in PRIORITY_GROUPS
    )
    seed_by_id = {seed["id"]: seed for seed in seeds}
    priority_gaps = []
    for rank, group in enumerate(PRIORITY_GROUPS, start=1):
        if any(venue_id in active_venue_ids for venue_id in group):
            continue
        group_coverages = [
            coverage_by_id[venue_id]
            for venue_id in group
            if venue_id in coverage_by_id
        ]
        priority_gaps.append(
            {
                "rank": rank,
                "name": "Gagosian"
                if len(group) > 1
                else seed_by_id.get(group[0], {}).get("name", group[0]),
                "venueIds": list(group),
                "statuses": sorted(
                    {row["status"] for row in group_coverages}
                ),
                "locationVerified": any(
                    row.get("locationVerified", False) for row in group_coverages
                ),
            }
        )
    open_today_records = [
        record
        for record in all_records
        if record["startDate"] <= today.isoformat() <= record["endDate"]
    ]
    price_audit_by_id = {
        row["exhibitionId"]: row for row in price_audits
    }
    open_today_price_counts = {
        status: sum(record["priceStatus"] == status for record in open_today_records)
        for status in ("free", "paid", "unknown")
    }
    open_today_price_counts_before = {
        status: sum(
            price_audit_by_id[record["id"]]["priceStatusBeforeOverride"] == status
            for record in open_today_records
        )
        for status in ("free", "paid", "unknown")
    }
    image_audits = [
        {
            "exhibitionId": record["id"],
            "venueId": record["venueId"],
            "title": record["title"],
            "sourceUrl": record["sourceUrl"],
            "status": (
                record.get("_imageProvenance", "official-remote-image")
                if record.get("imageUrl")
                else "missing-official-image"
            ),
            "imageUrl": record.get("imageUrl"),
            "cachedThumbnail": record.get("cachedThumbnail"),
            "reason": (
                (
                    "Official exhibition installation image extracted from the gallery's dedicated image template."
                    if record.get("_imageProvenance") == "exhibition-official"
                    else "Usable image extracted from official structured or social metadata."
                )
                if record.get("imageUrl")
                else "No usable image was exposed in accepted structured data or official page social metadata."
            ),
            "verifiedAt": record["lastVerified"],
        }
        for record in all_records
    ]
    for record in all_records:
        record.pop("_imageProvenance", None)
    summary = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "windowStart": today.isoformat(),
        "windowEnd": window_end.isoformat(),
        "windowKind": WINDOW_KIND,
        "windowInclusiveDays": (window_end - today).days + 1,
        "userAgent": USER_AGENT,
        "totalVenues": len(venue_rows),
        "successfulScrapes": successful_scrapes,
        "linkOnlyBlockedFailedOrUnverified": link_only_or_problem,
        "exhibitionsFound": len(all_records),
        "activeLondonVenues": len(active_venues),
        "rejectedCandidates": len(rejection_rows),
        "rejectedNonLondonRecords": sum(
            row["reasonCode"] in explicit_non_london_codes
            for row in rejection_rows
        ),
        "rejectedLocationUnverifiedRecords": sum(
            row["reasonCode"] in location_rejection_codes
            and row["reasonCode"] not in explicit_non_london_codes
            for row in rejection_rows
        ),
        "priorityInstitutionCount": len(PRIORITY_GROUPS),
        "priorityVenueRecordCount": sum(len(group) for group in PRIORITY_GROUPS),
        "priorityInstitutionsWithVerifiedShows": priority_active_groups,
        "priorityExhibitionsFound": sum(
            record["venueId"] in PRIORITY_RANK for record in all_records
        ),
        "addressVerifiedVenues": sum(row["accepted"] for row in address_audits),
        "addressUnresolvedVenues": sum(
            not row["accepted"] for row in address_audits
        ),
        "titleOverridesApplied": sum(
            row["reasonCode"] != "official-source-title"
            for row in title_audits
        ),
        "independentPolicyFreeExhibitions": sum(
            row["reasonCode"] == "user-policy-independent-default-free"
            for row in price_audits
        ),
        "exhibitionsWithImages": sum(
            bool(record.get("imageUrl")) for record in all_records
        ),
        "exhibitionsMissingImages": sum(
            not record.get("imageUrl") for record in all_records
        ),
        "openTodayPriceCountsBeforePolicy": open_today_price_counts_before,
        "openTodayPriceCounts": open_today_price_counts,
        "priorityGaps": priority_gaps,
        "statusCounts": dict(sorted(status_counts.items())),
        "accuracyClaim": None,
        "accuracyNote": "No accuracy percentage is claimed; spot-check measurement has not been run.",
    }
    write_json(VENUES_JSON_PATH, venue_rows)
    write_json(EXHIBITIONS_JSON_PATH, all_records)
    write_json(COVERAGE_JSON_PATH, coverage_rows)
    write_json(
        REJECTIONS_PATH,
        {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "windowStart": today.isoformat(),
            "windowEnd": window_end.isoformat(),
            "windowKind": WINDOW_KIND,
            "total": len(rejection_rows),
            "records": rejection_rows,
        },
    )
    write_json(
        LOCATION_AUDIT_PATH,
        {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "windowStart": today.isoformat(),
            "windowEnd": window_end.isoformat(),
            "windowKind": WINDOW_KIND,
            "venues": venue_audits,
            "exhibitions": exhibition_audits,
        },
    )
    write_json(
        PRICE_AUDIT_PATH,
        {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "windowStart": today.isoformat(),
            "windowEnd": window_end.isoformat(),
            "windowKind": WINDOW_KIND,
            "records": sorted(
                price_audits,
                key=lambda row: (
                    PRIORITY_RANK.get(row["venueId"], 10_000),
                    row["venueId"],
                    row["title"],
                ),
            ),
        },
    )
    write_json(
        TITLE_AUDIT_PATH,
        {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "windowStart": today.isoformat(),
            "windowEnd": window_end.isoformat(),
            "windowKind": WINDOW_KIND,
            "rejectedRecords": [
                {
                    "venueId": row["venueId"],
                    "title": row.get("title"),
                    "sourceUrl": row.get("sourceUrl"),
                    "reasonCode": row["reasonCode"],
                    "evidence": row.get("evidence"),
                }
                for row in rejection_rows
                if row["reasonCode"] == "generic-listing-not-exhibition"
            ],
            "records": sorted(
                title_audits,
                key=lambda row: (
                    PRIORITY_RANK.get(row["venueId"], 10_000),
                    row["venueId"],
                    row["title"],
                ),
            ),
        },
    )
    write_json(
        DESCRIPTION_AUDIT_PATH,
        {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "windowStart": today.isoformat(),
            "windowEnd": window_end.isoformat(),
            "windowKind": WINDOW_KIND,
            "missingDescriptionCount": sum(
                not row["description"] for row in description_audits
            ),
            "records": sorted(
                description_audits,
                key=lambda row: (
                    PRIORITY_RANK.get(row["venueId"], 10_000),
                    row["venueId"],
                    row["title"],
                ),
            ),
        },
    )
    write_json(
        ADDRESS_AUDIT_PATH,
        {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "windowStart": today.isoformat(),
            "windowEnd": window_end.isoformat(),
            "windowKind": WINDOW_KIND,
            "totalVenues": len(address_audits),
            "verified": sum(row["accepted"] for row in address_audits),
            "unresolved": sum(not row["accepted"] for row in address_audits),
            "records": address_audits,
        },
    )
    write_json(
        IMAGE_AUDIT_PATH,
        {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "windowStart": today.isoformat(),
            "windowEnd": window_end.isoformat(),
            "windowKind": WINDOW_KIND,
            "records": sorted(
                image_audits,
                key=lambda row: (
                    PRIORITY_RANK.get(row["venueId"], 10_000),
                    row["venueId"],
                    row["title"],
                ),
            ),
        },
    )
    write_json(SUMMARY_PATH, summary)
    write_coverage_csv(coverage_rows)
    emit_typescript(active_venues, all_records)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
