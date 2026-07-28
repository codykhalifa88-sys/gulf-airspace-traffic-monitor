# Data samples

Trimmed, real snapshots used for local development and as committed test
fixtures (the same files also live under `tests/fixtures/`). The full
pipeline pulls fresh live data from these same sources at run time — these
samples exist so the repo is self-contained for reviewers and so tests don't
depend on network access or a moving target.

## OpenSky Network state vectors (`opensky_states_gulf_sample.json`)

- Source: `https://opensky-network.org/api/states/all` with the Middle East
  bounding box (`lamin=12.0&lomin=31.0&lamax=37.5&lomax=63.3`)
- **Real, live-captured response** during development (2026-07), not
  synthetic — 30 real aircraft state vectors, including real Gulf carriers
  (Saudi Arabian Airlines, Etihad, Oman Air) and Pakistan International (a
  real migrant-worker-corridor flight).
- Access: anonymous, no signup required (400 requests / 2.2hr rate limit).
  Each state is a 17-field array, not an object — see
  `docs/data_dictionary.md` for the confirmed real field order.
- License/terms: OpenSky Network's public API terms
  (https://opensky-network.org/about/terms-of-use)

## GDELT Event Database v2 export (`gdelt_export_sample.CSV.zip`)

- Source: `http://data.gdeltproject.org/gdeltv2/lastupdate.txt` →
  `<timestamp>.export.CSV.zip` (the bulk-file pattern, not the rate-limited
  DOC 2.0 query API)
- **Real, trimmed slice** of an actual GDELT export file captured during
  development: 5 rows genuinely inside the Middle East bounding box (4 of
  which also meet the `QuadClass >= 3` conflict-relevance filter — 3 in the
  Gulf itself, 1 near Amman, Jordan) plus ~15 real non-Middle-East rows,
  included specifically to prove the bbox filter actually excludes them
  rather than accidentally passing everything through.
- No header row — GDELT's real, documented 61-column tab-delimited layout,
  verified against this actual downloaded file (see
  `pipeline/transform/silver.py:_GDELT_COLUMNS`).
- Confirmed real gotcha in this sample: `ActionGeo_CountryCode` is FIPS
  10-4, not ISO 3166 (Iraq is `IZ`, not ISO's `IQ`) — see
  `docs/data_dictionary.md`.
- License: GDELT Project data is free and open for any use
  (https://www.gdeltproject.org/about.html#termsofuse)

## Why no committed restricted-zone or airline reference data

`pipeline/reference/restricted_airspace.py` and `pipeline/reference/airlines.py`
are small, hand-maintained Python dicts (bounding boxes, ICAO callsign
prefixes) rather than downloaded data files — there's no upstream source to
snapshot, and the citations backing the cost-impact figures are documented
directly in that module's docstring and in `docs/data_dictionary.md`.
