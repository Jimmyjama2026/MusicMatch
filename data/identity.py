"""Canonical text identities; matching a recording still requires source evidence."""
import re
import unicodedata


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().replace("’", "'").split())


def credited_artists(song):
    names = (normalized(name) for name in str(song.get("artists", "")).split(";"))
    return tuple(dict.fromkeys(name for name in names if name))


def song_identity(song):
    """Full-credit identity for exclusions, not an assertion of recording equality."""
    return normalized(song.get("track_name", "")), tuple(sorted(credited_artists(song)))


def artist_ids(song):
    """Keep provider namespaces separate; malformed IDs do not become evidence."""
    raw = song.get("id_artists", ())
    if isinstance(raw, str):
        raw = re.findall(r"['\"]([A-Za-z0-9]{22})['\"]", raw) if raw.strip().startswith("[") and raw.strip().endswith("]") else ()
    if isinstance(raw, (list, tuple)):
        ids = tuple(sorted({"spotify:" + item for item in raw if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9]{22}", item)}))
        if ids:
            return ids
    raw = song.get("artist_mbids", ())
    if isinstance(raw, (list, tuple)):
        return tuple(sorted({"musicbrainz:" + item for item in raw if isinstance(item, str) and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", item)}))
    return ()
