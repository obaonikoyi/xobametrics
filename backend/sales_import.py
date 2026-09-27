"""
Distributor sales and streaming reports (DistroKid, TuneCore, CD Baby, Ditto,
Symphonic, AWAL and anything shaped like them).

These files hold one row per song, store, country and month, usually for
every song an artist has out. They are read into `sales_lines`, one row per
content item, country and month, and each item's snapshots are then rebuilt
from everything stored for it. Uploading an overlapping or repeated file
therefore replaces the months it covers instead of adding them twice.

Only the columns are recognised, never a vendor name, so a distributor that
renames a column needs one more alias here, nothing else.
"""
import csv
import io
import re
from datetime import date

# Header aliases, compared after lower-casing and dropping everything that is
# not a letter or digit ("# Units Sold" -> "unitssold").
COLUMNS = {
    "title": ["title", "songtitle", "tracktitle", "track", "song", "trackname", "songname", "product", "itemtitle"],
    "release": ["releasetitle", "album", "albumtitle", "release", "releasename", "productname"],
    "artist": ["artist", "artistname", "releaseartist", "trackartist", "primaryartist"],
    "isrc": ["isrc", "optionalisrc", "trackisrc"],
    "store": ["store", "storename", "service", "partner", "dsp", "retailer", "platform", "channel", "shop"],
    "country": ["countryofsale", "country", "territory", "countrycode", "salecountry", "territorycode", "region"],
    "month": ["salemonth", "salesperiod", "salesmonth", "period", "month", "transactionmonth",
              "usagemonth", "activitymonth", "statementperiod", "reportingperiod"],
    "reported": ["reportingdate", "reportdate", "posteddate", "statementdate"],
    "units": ["quantity", "unitssold", "units", "qty", "streams", "plays", "quantitystreamsdownloads", "count"],
    "earnings": ["earningsusd", "earnings", "totalearned", "netsales", "payable", "royalty", "royalties",
                 "netrevenue", "revenue", "netearnings", "amount", "amountusd", "totalpayable"],
}
REQUIRED = ("title", "store", "units")

# Store names -> our platform keys. Matched on the lower-cased name.
STORES = [
    ("youtube music", "youtube_music"), ("youtube", "youtube_music"),
    ("spotify", "spotify"), ("apple", "apple_music"), ("itunes", "apple_music"),
    ("amazon", "amazon_music"), ("deezer", "deezer"), ("tidal", "tidal"), ("boomplay", "boomplay"),
    ("audiomack", "audiomack"), ("pandora", "pandora"), ("iheart", "iheartradio"), ("qobuz", "qobuz"),
    ("tiktok", "tiktok"), ("resso", "tiktok"), ("instagram", "instagram"), ("facebook", "instagram"),
    ("meta", "instagram"), ("soundcloud", "soundcloud"), ("beatport", "beatport"), ("bandcamp", "bandcamp"),
]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (header or "").lower())


def find_columns(headers: list[str]) -> dict:
    """Canonical name -> the file's header, exact alias matches first."""
    keyed = {_key(h): h for h in headers if h}
    found = {}
    for name, aliases in COLUMNS.items():
        for alias in aliases:
            if alias in keyed and keyed[alias] not in found.values():
                found[name] = keyed[alias]
                break
    return found


def is_sales_report(headers: list[str]) -> bool:
    cols = find_columns(headers)
    return all(c in cols for c in REQUIRED) and ("month" in cols or "reported" in cols)


def read_table(raw: bytes) -> tuple[list[str], list[dict]]:
    """CSV, TSV or tab-delimited .txt, with or without a byte-order mark."""
    text = raw.decode("utf-8-sig", errors="replace")
    first = text.split("\n", 1)[0]
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = [h.strip() for h in (reader.fieldnames or [])]
    rows = []
    for row in reader:
        rows.append({(k or "").strip(): (v or "").strip() if isinstance(v, str) else v for k, v in row.items()})
    return headers, rows


def platform_for(store: str) -> str:
    s = (store or "").lower()
    for needle, platform in STORES:
        if needle in s:
            return platform
    return "csv"


def parse_month(value: str) -> date | None:
    """The first day of the month a row's sales belong to."""
    v = (value or "").strip()
    if not v:
        return None
    m = re.match(r"^(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?", v)  # 2026-07, 2026-07-01, 2026/07
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
    else:
        m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", v)  # 07/01/2026 (month first)
        if m:
            y, mo = int(m.group(3)), int(m.group(1))
        else:
            m = re.match(r"^(\d{1,2})[-/.](\d{4})$", v)  # 07/2026
            if m:
                y, mo = int(m.group(2)), int(m.group(1))
            else:
                m = re.match(r"^([A-Za-z]{3})[A-Za-z]*[\s\-,]+(\d{4})", v)  # Jul 2026, July-2026
                if not m or m.group(1).lower() not in MONTHS:
                    return None
                y, mo = int(m.group(2)), MONTHS[m.group(1).lower()]
    if not (1 <= mo <= 12 and 1990 <= y <= 2100):
        return None
    return date(y, mo, 1)


def number(value) -> float | None:
    s = str(value or "").strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    if s in ("", "-", "na", "n/a"):
        return 0.0
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def normalise_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"\s*[\(\[](feat|ft|with|prod)[^\)\]]*[\)\]]", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def parse_report(headers: list[str], rows: list[dict]) -> dict:
    """
    Group the file into one entry per song, store, country and month.
    Rows that cannot be read are counted, not guessed.
    """
    cols = find_columns(headers)
    month_col = cols.get("month") or cols.get("reported")
    lines: dict[tuple, dict] = {}
    skipped = {"no_title": 0, "bad_month": 0, "bad_number": 0}
    artists: dict[str, int] = {}
    for row in rows:
        title = (row.get(cols["title"]) or "").strip()
        if not title:
            skipped["no_title"] += 1
            continue
        month = parse_month(row.get(month_col, ""))
        if not month:
            skipped["bad_month"] += 1
            continue
        units = number(row.get(cols["units"]))
        earnings = number(row.get(cols["earnings"])) if "earnings" in cols else 0.0
        if units is None or earnings is None:
            skipped["bad_number"] += 1
            continue
        artist = (row.get(cols["artist"]) or "").strip() if "artist" in cols else ""
        store = (row.get(cols["store"]) or "").strip() or "Unknown store"
        country = (row.get(cols["country"]) or "").strip().upper() if "country" in cols else ""
        if len(country) != 2:
            country = (row.get(cols["country"]) or "").strip() if "country" in cols else ""
        isrc = (row.get(cols["isrc"]) or "").strip().upper() if "isrc" in cols else ""
        song = isrc or normalise_title(title)
        key = (artist, song, platform_for(store), country or "??", month)
        line = lines.setdefault(key, {
            "artist": artist, "song_key": song, "title": title, "isrc": isrc or None,
            "release": (row.get(cols["release"]) or "").strip() if "release" in cols else "",
            "platform": platform_for(store), "store": store, "country": country or "??",
            "month": month, "units": 0.0, "earnings": 0.0,
        })
        line["units"] += units
        line["earnings"] += earnings
        artists[artist] = artists.get(artist, 0) + 1
    return {"columns": cols, "lines": list(lines.values()), "skipped": skipped,
            "artists": sorted(artists, key=lambda a: -artists[a])}


def summarise(parsed: dict) -> dict:
    """What the preview shows before anything is written."""
    lines = parsed["lines"]
    songs: dict[tuple, dict] = {}
    for ln in lines:
        s = songs.setdefault((ln["artist"], ln["song_key"]), {
            "artist": ln["artist"], "title": ln["title"], "isrc": ln["isrc"], "units": 0, "stores": set(),
        })
        s["units"] += ln["units"]
        s["stores"].add(ln["platform"])
    months = sorted({ln["month"] for ln in lines})
    return {
        "songs": sorted(({**s, "units": int(s["units"]), "stores": sorted(s["stores"])} for s in songs.values()),
                        key=lambda s: -s["units"]),
        "artists": parsed["artists"],
        "stores": sorted({ln["platform"] for ln in lines}),
        "countries": len({ln["country"] for ln in lines if ln["country"] != "??"}),
        "first_month": months[0].isoformat() if months else None,
        "last_month": months[-1].isoformat() if months else None,
        "units": int(sum(ln["units"] for ln in lines)),
        "earnings": round(sum(ln["earnings"] for ln in lines), 2),
        "skipped": parsed["skipped"],
        "columns": parsed["columns"],
    }
