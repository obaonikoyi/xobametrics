"""Distributor report import: detection, grouping, idempotent re-import, countries.

Execute with: python -m unittest discover -s backend/tests -p 'test_imports.py'
(needs TEST_DATABASE_URL, see support.py).
"""
import unittest
from datetime import date

from support import ApiTestCase, requires_postgres

import sales_import

DISTROKID = "\n".join([
    "\t".join(["Reporting Date", "Sale Month", "Store", "Artist", "Title", "ISRC", "UPC", "Quantity",
               "Team Percentage", "Song/Album", "Country of Sale", "Songwriter Royalties Withheld", "Earnings (USD)"]),
    "2026-08-15\t2026-06\tSpotify\tLuna\tNeon Rain\tQZ1234500001\t123\t1000\t100\tSong\tNG\t0\t3.10",
    "2026-08-15\t2026-06\tSpotify\tLuna\tNeon Rain\tQZ1234500001\t123\t400\t100\tSong\tUS\t0\t1.60",
    "2026-08-15\t2026-06\tApple Music\tLuna\tNeon Rain\tQZ1234500001\t123\t200\t100\tSong\tNG\t0\t1.20",
    "2026-08-15\t2026-06\tiTunes\tLuna\tNeon Rain\tQZ1234500001\t123\t5\t100\tSong\tNG\t0\t3.50",
    "2026-09-15\t2026-07\tSpotify\tLuna\tNeon Rain\tQZ1234500001\t123\t1500\t100\tSong\tNG\t0\t4.80",
    "2026-09-15\t2026-07\tBoomplay\tLuna\tMidnight Signal (feat. Kay)\tQZ1234500002\t124\t300\t100\tSong\tGH\t0\t0.30",
    "2026-09-15\t2026-07\tSome Tiny Store\tLuna\tMidnight Signal (feat. Kay)\tQZ1234500002\t124\t7\t100\tSong\tNG\t0\t0.01",
    "2026-09-15\t2026-07\tSpotify\tOther Act\tNot Mine\tQZ9999900001\t999\t50\t100\tSong\tUS\t0\t0.20",
    "2026-09-15\tbad month\tSpotify\tLuna\tNeon Rain\tQZ1234500001\t123\t1\t100\tSong\tNG\t0\t0",
])

TUNECORE = "\n".join([
    "Sales Period,Posted Date,Store Name,Country of Sale,Artist,Release Type,Release Title,Song Title,Label,UPC,"
    "Optional UPC,TC Song ID,Optional ISRC,Sales Type,# Units Sold,Per Unit Price,Net Sales,Net Sales Currency,"
    "Exchange Rate,Total Earned,Currency",
    '2026-07-01,2026-09-01,Deezer,FR,Luna,Single,Neon Rain,Neon Rain,,1,,1,QZ1234500001,Streaming,"1,200",0,1,USD,1,1.00,USD',
])


@requires_postgres
class DistributorImport(ApiTestCase):
    def setUp(self):
        body = self.register(f"imports-{self._testMethodName}@example.com")
        self.token, self.profile = body["token"], self.profile_id(body["token"])

    def post(self, path, name, text, **form):
        return self.client.post(
            path, headers={**self.auth(self.token), "X-Requested-With": "XobaMetrics"},
            data={"profile_id": self.profile, **form}, files={"file": (name, text.encode(), "text/plain")},
        )

    def commit(self, name="distrokid.tsv", text=DISTROKID, **form):
        response = self.post("/api/imports/commit", name, text, **form)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def snapshots(self, platform):
        return self.sql(
            "SELECT s.date, s.plays FROM metric_snapshots s JOIN content_items c ON c.id = s.content_item_id "
            "WHERE c.profile_id = $1 AND c.platform = $2 AND s.source = 'distributor' ORDER BY s.date",
            self.profile, platform)

    def test_preview_describes_without_writing(self):
        body = self.post("/api/imports/preview", "distrokid.tsv", DISTROKID).json()
        self.assertEqual(body["kind"], "sales_report")
        self.assertEqual([s["title"] for s in body["songs"]], ["Neon Rain", "Midnight Signal (feat. Kay)", "Not Mine"])
        self.assertEqual(body["songs"][0]["units"], 3105)
        self.assertEqual(body["artists"], ["Luna", "Other Act"])
        self.assertEqual((body["first_month"], body["last_month"]), ("2026-06-01", "2026-07-01"))
        self.assertEqual(body["skipped"]["bad_month"], 1)
        self.assertIn("boomplay", body["stores"])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM releases WHERE profile_id = $1", self.profile)[0]["n"], 0)

    def test_import_builds_releases_items_and_monthly_totals(self):
        result = self.commit(artists='["Luna"]')
        self.assertEqual(result["songs"], 2)
        releases = {r["title"]: r for r in self.sql("SELECT title, release_date, source FROM releases WHERE profile_id = $1", self.profile)}
        self.assertEqual(set(releases), {"Neon Rain", "Midnight Signal (feat. Kay)"})
        self.assertEqual(releases["Neon Rain"]["release_date"], "2026-06-01")
        platforms = {r["platform"] for r in self.sql("SELECT platform FROM content_items WHERE profile_id = $1", self.profile)}
        self.assertEqual(platforms, {"spotify", "apple_music", "boomplay", "csv"})
        # Running totals at each month end: 1,400 in June, +1,500 in July.
        self.assertEqual(self.snapshots("spotify"), [{"date": "2026-06-30", "plays": 1400}, {"date": "2026-07-31", "plays": 2900}])
        # Apple Music and iTunes are one platform.
        self.assertEqual(self.snapshots("apple_music"), [{"date": "2026-06-30", "plays": 205}])

    def test_reimport_replaces_instead_of_adding(self):
        self.commit(artists='["Luna"]')
        self.commit(artists='["Luna"]')
        self.assertEqual(self.snapshots("spotify")[-1]["plays"], 2900)
        # A corrected July replaces July; June stays.
        corrected = DISTROKID.replace("\t1500\t", "\t1700\t")
        self.commit(text=corrected, artists='["Luna"]')
        self.assertEqual(self.snapshots("spotify"), [{"date": "2026-06-30", "plays": 1400}, {"date": "2026-07-31", "plays": 3100}])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM releases WHERE profile_id = $1", self.profile)[0]["n"], 2)

    def test_existing_release_is_matched_by_title_and_another_distributor_adds_to_it(self):
        created = self.client.post("/api/releases", headers=self.auth(self.token), json={
            "profile_id": self.profile, "title": "Neon Rain", "release_date": "2026-05-20"})
        self.assertEqual(created.status_code, 200, created.text)
        self.commit(artists='["Luna"]')
        self.commit(name="tunecore.csv", text=TUNECORE)
        rows = self.sql("SELECT r.release_date, count(c.id) AS items FROM releases r JOIN content_items c ON c.release_id = r.id "
                        "WHERE r.profile_id = $1 AND r.title = 'Neon Rain' GROUP BY r.release_date", self.profile)
        self.assertEqual(rows, [{"release_date": "2026-05-20", "items": 3}])  # spotify, apple_music, deezer
        self.assertEqual(self.snapshots("deezer"), [{"date": "2026-07-31", "plays": 1200}])

    def test_countries_across_stores(self):
        self.commit(artists='["Luna"]')
        body = self.client.get(f"/api/imports/countries?profile_id={self.profile}", headers=self.auth(self.token)).json()
        total = 1000 + 400 + 200 + 5 + 1500 + 300 + 7
        self.assertEqual(body["total_units"], total)
        # The period starts where the reports start, not a year back.
        self.assertEqual((body["first_month"], body["last_month"]), ("2026-06-01", "2026-07-01"))
        self.assertEqual([c["country"] for c in body["countries"]], ["NG", "US", "GH"])
        self.assertEqual(body["countries"][0]["units"], 1000 + 200 + 5 + 1500 + 7)
        self.assertEqual(body["stores"][0], {"platform": "spotify", "units": 2900, "share": round(2900 / total, 4)})
        release = self.sql("SELECT id FROM releases WHERE title = 'Midnight Signal (feat. Kay)' AND profile_id = $1", self.profile)[0]["id"]
        one = self.client.get(f"/api/imports/countries?profile_id={self.profile}&release_id={release}",
                              headers=self.auth(self.token)).json()
        self.assertEqual([c["country"] for c in one["countries"]], ["GH", "NG"])

    def test_daily_export_is_left_to_the_simple_upload(self):
        body = self.post("/api/imports/preview", "spotify-neon-rain.csv", "date,streams\n2026-07-01,10\n").json()
        self.assertEqual((body["kind"], body["platform_hint"]), ("daily", "spotify"))

    def test_guards(self):
        self.assertEqual(self.post("/api/imports/preview", "statement.xlsx", "x").status_code, 400)
        other = self.register("imports-other@example.com")["token"]
        response = self.client.post("/api/imports/preview", headers={**self.auth(other), "X-Requested-With": "XobaMetrics"},
                                    data={"profile_id": self.profile}, files={"file": ("a.tsv", DISTROKID.encode(), "text/plain")})
        self.assertEqual(response.status_code, 404)
        response = self.client.post("/api/imports/preview", headers=self.auth(self.token),
                                    data={"profile_id": self.profile}, files={"file": ("a.tsv", DISTROKID.encode(), "text/plain")})
        self.assertEqual(response.status_code, 403)


class ParsingHelpers(unittest.TestCase):
    def test_months(self):
        for value in ("2026-07", "2026-07-15", "2026/07", "07/15/2026", "07/2026", "Jul 2026", "July-2026", "July, 2026"):
            self.assertEqual(sales_import.parse_month(value), date(2026, 7, 1), value)
        for value in ("", "soon", "13/2026", "2026-13"):
            self.assertIsNone(sales_import.parse_month(value), value)

    def test_stores(self):
        self.assertEqual(sales_import.platform_for("YouTube Music"), "youtube_music")
        self.assertEqual(sales_import.platform_for("Apple Music / iTunes"), "apple_music")
        self.assertEqual(sales_import.platform_for("Facebook / Instagram"), "instagram")
        self.assertEqual(sales_import.platform_for("Anghami"), "csv")

    def test_numbers_and_titles(self):
        self.assertEqual(sales_import.number("1,200"), 1200)
        self.assertEqual(sales_import.number("(3.50)"), -3.5)
        self.assertIsNone(sales_import.number("lots"))
        self.assertEqual(sales_import.normalise_title("Midnight Signal (feat. Kay)"), "midnight signal")

    def test_detection(self):
        headers, _ = sales_import.read_table(TUNECORE.encode())
        self.assertTrue(sales_import.is_sales_report(headers))
        self.assertFalse(sales_import.is_sales_report(["date", "streams", "listeners"]))


if __name__ == "__main__":
    unittest.main()
