# Setlistr v2 (Phase 1 scaffold)

Same behavior as v1, restructured into modules so new features have a home.

```
app.py                  entry point: page config, Spotify sidebar login, st.navigation
pages/1_Builder.py      playlist builder UI
pages/2_Passport.py     concert passport dashboard
pages/5_Shows.py        My Shows: upcoming shows with tickets (upcoming_shows.csv) + watchlist (watchlist.csv)
services/auth.py        credentials + owner/friend Spotify sessions
services/setlistfm.py   setlist.fm API calls (timeouts, 429 retry) + stats scrape
services/spotify_match.py  tiered track matching (no Streamlit imports)
analytics/setlist_stats.py pure show filtering + song table logic
data/store.py           attended_shows.csv loader (swap for a DB in Phase 2)
tests/test_matching.py  matcher tests
```

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
python -m pytest
```
Put `attended_shows.csv` in the project root and secrets in `.streamlit/secrets.toml`
(`SETLIST_API_KEY`, `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, optional `SPOTIFY_REFRESH_TOKEN`).
On Streamlit Cloud, set the main file to `app.py`.

## My Shows page: setup for adding shows in the app
The watchlist lives in `watchlist.csv`. Adding, editing or removing shows on the My Shows page
saves a commit to that file, so it needs two optional secrets (Streamlit Cloud: app menu →
Settings → Secrets):

- `GITHUB_TOKEN`: a fine-grained token from github.com/settings/personal-access-tokens/new,
  limited to the setlistr repo, with Repository permissions → Contents: Read and write.
- `TICKETMASTER_API_KEY` (optional): the free "Consumer Key" from developer.ticketmaster.com.
  Turns on artist search and reads Ticketmaster/Live Nation links. Other links (Dice, AXS,
  venue sites) are read from the page itself where the site allows it.

Editing only shows up for the owner (the `?me=<OWNER_KEY>` link). Everyone else sees the lists read-only.

## Changes from v1
- Friend logins can no longer trigger playlist creation in the owner's account.
- Deep Cuts no longer treats songs missing from the stats scrape as 2% "rare" tracks.
- setlist.fm calls have timeouts and retry on HTTP 429.
