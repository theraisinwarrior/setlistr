"""Compare two people's concert histories. Pure pandas, no Streamlit."""
import pandas as pd

SKIP_ARTISTS = {"various artists"}


def _norm(value) -> str:
    return " ".join(str(value).lower().split()) if pd.notna(value) else ""


def _artist_key(row) -> str:
    mbid = row.get("artist_mbid") if hasattr(row, "get") else None
    return f"mbid:{mbid}" if isinstance(mbid, str) and mbid else f"name:{_norm(row['artist'])}"


def _prep(df_att: pd.DataFrame) -> pd.DataFrame:
    d = df_att.dropna(subset=["eventDate_dt"]).copy()
    d = d[~d["artist"].map(_norm).isin(SKIP_ARTISTS)]
    d["akey"] = d.apply(_artist_key, axis=1)
    d["day"] = d["eventDate_dt"].dt.normalize()
    d["vkey"] = d["venue"].map(_norm)
    return d


def _artist_summary(d: pd.DataFrame) -> pd.DataFrame:
    """One row per artist: display name, shows seen, last seen date."""
    g = d.groupby("akey").agg(name=("artist", "first"), times=("day", "nunique"), last=("day", "max"))
    return g


def compare_histories(df_me: pd.DataFrame, df_friend: pd.DataFrame, top_n: int = 10) -> dict:
    """Shared shows, shared artists, shared venues, and each person's unique favorites."""
    me, fr = _prep(df_me), _prep(df_friend)

    # Same concert = same day at the same venue
    my_nights = me.groupby(["day", "vkey"]).agg(venue=("venue", "first"), city=("city", "first"),
                                                 mine=("artist", lambda s: sorted(set(s))))
    fr_nights = fr.groupby(["day", "vkey"]).agg(theirs=("artist", lambda s: sorted(set(s))))
    both = my_nights.join(fr_nights, how="inner").reset_index().sort_values("day", ascending=False)
    same_shows = pd.DataFrame({
        "Date": both["day"].dt.strftime("%b %d, %Y"),
        "Venue": both["venue"],
        "City": both["city"],
        "Lineup": [", ".join(sorted(set(a) | set(b))) for a, b in zip(both["mine"], both["theirs"])],
    })

    mine, theirs = _artist_summary(me), _artist_summary(fr)
    shared = mine.join(theirs, how="inner", lsuffix="_me", rsuffix="_fr")
    shared = shared.assign(total=shared["times_me"] + shared["times_fr"]).sort_values(
        ["total", "name_me"], ascending=[False, True])
    shared_artists = pd.DataFrame({
        "Artist": shared["name_me"],
        "You": shared["times_me"].astype(int),
        "Them": shared["times_fr"].astype(int),
        "Your Last Time": shared["last_me"].dt.strftime("%b %Y"),
        "Their Last Time": shared["last_fr"].dt.strftime("%b %Y"),
    }).reset_index(drop=True)

    def only(a, b):
        o = a[~a.index.isin(b.index)].sort_values(["times", "last"], ascending=[False, False]).head(top_n)
        return pd.DataFrame({"Artist": o["name"], "Times Seen": o["times"].astype(int),
                             "Last Time": o["last"].dt.strftime("%b %Y")}).reset_index(drop=True)

    my_venues = set(me["vkey"])
    fr_venue_names = fr.drop_duplicates("vkey").set_index("vkey")["venue"]
    shared_venues = sorted(fr_venue_names[fr_venue_names.index.isin(my_venues)].tolist())

    return {
        "same_shows": same_shows,
        "shared_artists": shared_artists,
        "only_me": only(mine, theirs),
        "only_them": only(theirs, mine),
        "shared_venues": shared_venues,
        "stats": {
            "my_concerts": int(me[["day", "vkey"]].drop_duplicates().shape[0]),
            "their_concerts": int(fr[["day", "vkey"]].drop_duplicates().shape[0]),
            "my_artists": len(mine), "their_artists": len(theirs),
            "shared_artists": len(shared_artists), "same_shows": len(same_shows),
            "shared_venues": len(shared_venues),
        },
    }
