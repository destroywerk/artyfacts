import unittest
from datetime import date

from scripts.ingest import (
    extract_private_views,
    merge_private_views,
    page_description,
)


class PrivateViewExtractionTests(unittest.TestCase):
    def test_extracts_explicit_private_view_date_and_time(self):
        occurrences = extract_private_views(
            "Private View: Wednesday, 7th October 2026, 6-8pm",
            "https://example.com/exhibitions/show",
            date(2026, 10, 8),
            date(2026, 11, 7),
        )

        self.assertEqual(
            occurrences,
            [
                {
                    "date": "2026-10-07",
                    "startTime": "18:00",
                    "endTime": "20:00",
                    "label": "Private view",
                    "sourceUrl": "https://example.com/exhibitions/show",
                }
            ],
        )

    def test_does_not_infer_private_view_from_exhibition_dates(self):
        self.assertEqual(
            extract_private_views(
                "The exhibition runs 8 October to 7 November 2026.",
                "https://example.com/exhibitions/show",
                date(2026, 10, 8),
                date(2026, 11, 7),
            ),
            [],
        )

    def test_selects_nearest_opening_when_touring_text_lists_several(self):
        occurrences = extract_private_views(
            "Matt's Gallery, London: PV Sunday 27 September, 2-5pm. "
            "Flatland: PV Saturday 3 October, 3-7pm. "
            "KARST: PV Thursday 15 October, 6-9pm.",
            "https://example.com/exhibitions/show",
            date(2026, 9, 30),
            date(2026, 11, 22),
        )

        self.assertEqual(occurrences[0]["date"], "2026-09-27")
        self.assertEqual(occurrences[0]["startTime"], "14:00")
        self.assertEqual(occurrences[0]["endTime"], "17:00")

    def test_retention_merge_preserves_provenance_without_duplicates(self):
        retained = [
            {
                "date": "2026-10-08",
                "label": "Opening reception",
                "sourceUrl": "https://example.com/show",
            }
        ]
        self.assertEqual(merge_private_views(retained, retained), retained)


class DescriptionFallbackTests(unittest.TestCase):
    def test_uses_official_body_intro_when_metadata_is_empty(self):
        probe = type(
            "Probe",
            (),
            {
                "meta": {},
                "text": (
                    "Tickets Visit Tate. This major exhibition features the work "
                    "of two celebrated British artists. Vanessa Bell and Duncan "
                    "Grant worked together for more than 50 years."
                ),
            },
        )()

        self.assertIn(
            "This major exhibition",
            page_description(probe, "Vanessa Bell & Duncan Grant"),
        )


if __name__ == "__main__":
    unittest.main()
