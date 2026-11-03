"""Explicit offline acquisition: never imported or called by the GUI.

Public core metadata only; raw responses are cached for resumable pagination.
Transfer accounting is conservative across crashes (a response allowance is
reserved on disk before opening the connection). Run only one collector at once.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from email.parser import BytesParser
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from uuid import UUID

MB = "https://musicbrainz.org/ws/2/"
LB = "https://api.listenbrainz.org/1/"
DEFAULT_UA = "MusicMatch/0.2 (https://github.com/Jimmyjama2026/MusicMatch)"


class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https" or urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            raise ValueError("Redirect outside approved HTTPS origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_approved(request, timeout):
    return build_opener(SameOriginRedirect()).open(request, timeout=timeout)


class CurlResponse:
    """Native verified HTTPS transport for Windows environments with Python TLS issues."""
    def __init__(self, request, timeout):
        self.url = request.full_url
        args = ["curl.exe", "--silent", "--show-error", "--include", "--suppress-connect-headers", "--proto", "=https", "--max-time", str(timeout), "--max-filesize", "2000000"]
        for name, value in request.header_items():
            args.extend(["--header", f"{name}: {value}"])
        args.append(self.url)
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            header_bytes = 0
            for _ in range(5):
                status = self.process.stdout.readline(8192)
                headers = bytearray()
                while True:
                    line = self.process.stdout.readline(8192)
                    if not line or line in (b"\r\n", b"\n"):
                        break
                    headers.extend(line)
                    header_bytes += len(line)
                    if header_bytes > 32768:
                        raise ValueError("Oversized HTTP headers")
                self.headers = BytesParser().parsebytes(bytes(headers))
                fields = status.split()
                if len(fields) < 2 or not fields[0].startswith(b"HTTP/"):
                    raise ConnectionError("Native curl HTTPS failed before an HTTP response")
                code = int(fields[1])
                if code >= 200:
                    break
            else:
                raise ValueError("Too many informational HTTP responses")
            if code >= 400:
                raise HTTPError(self.url, code, "Provider error", self.headers, self)
            if code != 200:
                raise ValueError(f"Unexpected HTTP status {code}; redirects not followed")
        except HTTPError:
            raise
        except Exception:
            self.close()
            raise

    def geturl(self):
        return self.url

    @property
    def closed(self):
        return self.process.stdout.closed

    def read(self, size=-1):
        chunk = self.process.stdout.read(size)
        if not chunk and self.process.poll() not in (None, 0):
            raise ConnectionError("Native curl failed during response transfer")
        return chunk

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class BudgetExceeded(RuntimeError):
    pass


class ResponseTooLarge(RuntimeError):
    pass


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def valid_mbid(value):
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, TypeError, AttributeError):
        return False


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class JsonClient:
    def __init__(self, root, user_agent=DEFAULT_UA, transfer_limit=90_000_000,
                 disk_limit=90_000_000, response_limit=2_000_000,
                 opener=open_approved, sleeper=time.sleep, clock=time.monotonic):
        if not user_agent or "(" not in user_agent or "\n" in user_agent:
            raise ValueError("An identifying application/version (contact URL) is required")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache = self.root / "cache"
        self.cache.mkdir(exist_ok=True)
        self.ledger_path = self.root / "transfer.json"
        self.ledger = json.loads(self.ledger_path.read_text()) if self.ledger_path.exists() else {"payload_bytes": 0}
        self.transfer_limit = min(transfer_limit, 90_000_000)
        self.disk_limit = min(disk_limit, 90_000_000)
        self.response_limit = min(response_limit, 2_000_000)
        self.user_agent, self.opener = user_agent, opener
        self.sleep, self.clock, self.last_request = sleeper, clock, None
        self.blocked_hosts = set()
        self.failed_endpoints = {}
        self.last_retrieved_at = None

    def disk_bytes(self):
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())

    def save(self, path, value):
        path = Path(path)
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if self.disk_bytes() + len(payload) + 4096 > self.disk_limit:
            raise BudgetExceeded("Acquisition disk allowance reached")
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def exclusive(self):
        lock = self.root / "acquisition.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("Collector already running; inspect a stale lock before removing it") from exc
        try:
            os.write(descriptor, str(os.getpid()).encode())
            yield
        finally:
            os.close(descriptor)
            lock.unlink(missing_ok=True)

    def _read(self, response, allowance):
        parts, consumed = [], 0
        while consumed < allowance:
            chunk = response.read(min(65536, allowance - consumed))
            if not chunk:
                return b"".join(parts), consumed
            parts.append(chunk)
            consumed += len(chunk)
        # Do not read an extra byte past the allowance to detect EOF.
        raise ResponseTooLarge("Response reached its byte cap; stopped without caching")

    def get(self, base, path, params=None):
        if base not in (MB, LB):
            raise ValueError("Only approved metadata providers may be contacted")
        url = base + path + ("?" + urlencode(params) if params else "")
        key = hashlib.sha256(url.encode()).hexdigest()
        cached = self.cache / (key + ".json")
        if cached.exists():
            envelope = json.loads(cached.read_text(encoding="utf-8"))
            self.last_retrieved_at = envelope["retrieved_at"]
            return envelope["data"]
        host = urlsplit(base).hostname
        if host in self.blocked_hosts:
            raise ConnectionError(f"{host}: connection unavailable earlier in this run")
        for attempt in range(3):
            response_cap = self.response_limit if base == MB else max(self.response_limit, 1_000_000)
            allowance = min(response_cap, self.transfer_limit - self.ledger["payload_bytes"])
            if allowance <= 0:
                raise BudgetExceeded("Cumulative transfer allowance reached")
            # Reserve before any IO. A crash may overcount, never undercount.
            self.ledger["payload_bytes"] += allowance
            self.save(self.ledger_path, self.ledger)
            wait = 0 if self.last_request is None else max(0, 1.1 - (self.clock() - self.last_request))
            self.sleep(wait)
            self.last_request = self.clock()
            request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json", "Accept-Encoding": "identity"})
            response_started = False
            try:
                with self.opener(request, timeout=25) as response:
                    response_started = True
                    raw, consumed = self._read(response, allowance)
                    # Redirects to unapproved origins are rejected before parsing.
                    if urlsplit(response.geturl()).hostname != host:
                        raise ValueError("Provider redirected to another origin")
                    if response.headers.get("Content-Encoding", "identity") != "identity":
                        raise ValueError("Unexpected compressed response")
                    pause = response.headers.get("X-RateLimit-Reset-In") if response.headers.get("X-RateLimit-Remaining") == "0" else None
                self.ledger["payload_bytes"] -= allowance - consumed
                self.save(self.ledger_path, self.ledger)
                data = json.loads(raw)
                self.failed_endpoints[host] = 0
                self.last_retrieved_at = utc_now()
                self.save(cached, {"url": url, "retrieved_at": self.last_retrieved_at, "data": data})
                if pause:
                    seconds = float(pause)
                    if seconds > 60:
                        self.blocked_hosts.add(host)
                    else:
                        self.sleep(max(0, seconds))
                return data
            except HTTPError as exc:
                # Error payload bytes count too; unconsumed/failed reads remain conservatively reserved.
                try:
                    with exc:
                        error_body, consumed = self._read(exc, allowance)
                    self.ledger["payload_bytes"] -= allowance - consumed
                    self.save(self.ledger_path, self.ledger)
                except BudgetExceeded:
                    raise
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f"HTTP {exc.code}: {error_body.decode('utf-8', errors='replace')[:500]}") from exc
                retry = exc.headers.get("Retry-After", "")
                try:
                    seconds = float(retry)
                except ValueError:
                    seconds = max(0, parsedate_to_datetime(retry).timestamp() - time.time()) if retry else 2 ** (attempt + 1)
                if seconds > 60:
                    raise RuntimeError("Provider requested a long pause; rerun later") from exc
                self.sleep(max(1.1, seconds))
            except (URLError, TimeoutError, ConnectionError, OSError):
                if not response_started:
                    # DNS/TLS failures before an HTTP response deliver no API
                    # body. Partial-body failures keep their full reservation.
                    self.ledger["payload_bytes"] -= allowance
                    self.save(self.ledger_path, self.ledger)
                if attempt == 2:
                    self.failed_endpoints[host] = self.failed_endpoints.get(host, 0) + 1
                    if self.failed_endpoints[host] >= 3:
                        self.blocked_hosts.add(host)
                    raise
                self.sleep(2 ** (attempt + 1))
        raise RuntimeError("Retry limit reached")


def resolve_artist(client, name, overrides=None):
    if overrides and name in overrides:
        mbid = overrides[name]
        if not valid_mbid(mbid):
            raise ValueError("Invalid verified artist MBID")
        # Explicit verified-ID configuration is authoritative; another network
        # name lookup must not defeat already reviewed identity evidence.
        return {"requested_name": name, "mbid": mbid, "name": name, "match_confidence": "manually_verified", "identity_basis": "operator_verified_file", "status": "resolved"}
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    result = client.get(MB, "artist/", {"query": f'artist:"{escaped}"', "fmt": "json", "limit": 10})
    candidates = [a for a in result.get("artists", []) if normalized(a.get("name", "")) == normalized(name) and valid_mbid(a.get("id"))]
    strong = [a for a in candidates if int(a.get("score", 0)) == 100]
    if len(strong) != 1:
        return {"requested_name": name, "status": "needs_identity_review", "candidates": [{"mbid": a["id"], "name": a["name"], "disambiguation": a.get("disambiguation")} for a in candidates]}
    artist = strong[0]
    # Name-only searches remain provisional; do not silently accept namesakes.
    return {"requested_name": name, "mbid": artist["id"], "name": artist["name"], "match_confidence": "unique_exact_search", "status": "resolved_provisional", "disambiguation": artist.get("disambiguation")}


def parse_recording(item, retrieved_at=None):
    if not valid_mbid(item.get("id")) or not item.get("title"):
        raise ValueError("Malformed recording")
    credits = [c["artist"] for c in item.get("artist-credit", []) if isinstance(c, dict) and isinstance(c.get("artist"), dict)]
    return {"mbid": item["id"], "title": item["title"],
            "artist_names": [c["name"] for c in credits if c.get("name")],
            "artist_mbids": [c["id"] for c in credits if valid_mbid(c.get("id"))],
            "duration_ms": item.get("length"), "first_release_date": item.get("first-release-date"),
            "isrcs": item.get("isrcs", []), "disambiguation": item.get("disambiguation"),
            "releases": [{"mbid": r["id"], "title": r.get("title"), "date": r.get("date"), "status": r.get("status")} for r in item.get("releases", []) if valid_mbid(r.get("id"))],
            "source": "musicbrainz", "license": "CC0-1.0", "retrieved_at": retrieved_at or utc_now(),
            "credit_complete": bool(credits), "credit_basis": "artist_credit_response" if credits else "unavailable",
            "catalog_scope": "credited_recordings_includes_versions_not_verified_studio_only"}


def merge_recording(previous, incoming):
    if not previous or incoming.get("credit_complete"):
        return incoming
    if previous.get("credit_complete"):
        return previous
    merged = dict(incoming)
    merged["artist_mbids"] = list(dict.fromkeys(previous.get("artist_mbids", []) + incoming.get("artist_mbids", [])))
    merged["artist_names"] = list(dict.fromkeys(previous.get("artist_names", []) + incoming.get("artist_names", [])))
    return merged


def collect(client, artist_names, max_recordings=10_000, pages_per_artist=100, overrides=None, listenbrainz=True):
    if not 1 <= max_recordings <= 10_000 or not 1 <= pages_per_artist <= 100:
        raise ValueError("Recording/page limits outside approved bounds")
    output = client.root / "catalog.json"
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    document = {"schema_version": 1, "artists": previous.get("artists", []), "tracks": [], "related_edges": [], "popularity": [], "errors": [], "coverage_complete": True, "metadata_complete": True, "listening_complete": listenbrainz, "requested_artists": list(artist_names), "catalog_scope": "all_credited_recordings_including_live_remix_and_unofficial_versions; not_verified_studio_discographies", "generated_at": utc_now()}
    tracks = {t["mbid"]: t for t in previous.get("tracks", [])}
    edges = {(e["seed_artist_mbid"], e["candidate_artist_mbid"], e["recording_mbid"]): e for e in previous.get("related_edges", [])}
    popularity = {(p["artist_mbid"], p["recording_mbid"]): p for p in previous.get("popularity", [])}
    def checkpoint():
        document["tracks"] = list(tracks.values())
        document["related_edges"] = list(edges.values())
        document["popularity"] = list(popularity.values())
        document["transfer_payload_bytes_upper_bound"] = client.ledger["payload_bytes"]
        statuses = {a["requested_name"]: a for a in document["artists"]}
        document["metadata_complete"] = all(statuses.get(name, {}).get("complete", False) for name in artist_names) and not any(e["provider"] == "musicbrainz" for e in document["errors"])
        document["coverage_complete"] = document["metadata_complete"]
        # coverage_complete alone must never imply failed listening data exists.
        document["all_sources_complete"] = document["metadata_complete"] and document["listening_complete"]
        client.save(output, document)
    for name in artist_names:
        try:
            artist = resolve_artist(client, name, overrides)
            document["artists"] = [a for a in document["artists"] if a["requested_name"] != name]
            document["artists"].append(artist)
            if not artist.get("mbid"):
                document["coverage_complete"] = False
                document["listening_complete"] = False
                checkpoint()
                continue
            count, total, offset, complete = 0, None, 0, False
            for _ in range(pages_per_artist):
                if len(tracks) >= max_recordings:
                    break
                # Minimal browse remains useful when expensive include queries return503.
                params = {"artist": artist["mbid"], "limit": 100, "fmt": "json"}
                if offset:
                    params["offset"] = offset
                page = client.get(MB, "recording", params)
                rows = page.get("recordings")
                total = page.get("recording-count")
                if not isinstance(rows, list) or not isinstance(total, int):
                    raise ValueError("Malformed MusicBrainz recording page")
                page_truncated = False
                for row in rows:
                    track = parse_recording(row, client.last_retrieved_at)
                    if not track["artist_mbids"]:
                        # The browse filter establishes this association, not the
                        # complete credited lineup. Never use it as an exact credit match.
                        track["artist_mbids"] = [artist["mbid"]]
                        track["artist_names"] = [artist["name"]]
                        track["credit_basis"] = "artist_browse_filter"
                        track["credit_complete"] = False
                    if artist["mbid"] not in track["artist_mbids"]:
                        continue
                    if len(tracks) >= max_recordings and track["mbid"] not in tracks:
                        page_truncated = True
                        break
                    tracks[track["mbid"]] = merge_recording(tracks.get(track["mbid"]), track)
                    count += 1
                offset += len(rows)
                artist.update(recording_count=count, recording_total=total, complete=False)
                checkpoint()
                if offset >= total and not page_truncated:
                    complete = True
                    break
                if page_truncated:
                    break
                if not rows:
                    raise ValueError("Pagination ended before reported total")
            artist.update(recording_count=count, recording_total=total, complete=complete)
            document["coverage_complete"] &= complete
            if listenbrainz:
                artist["listening_complete"] = True
                for kind, endpoint, params in (
                    ("popularity", "popularity/top-recordings-for-artist/", None),
                    ("related", "lb-radio/artist/", {"mode": "easy", "max_similar_artists": 20, "max_recordings_per_artist": 5, "pop_begin": 0, "pop_end": 100}),
                ):
                    try:
                        data = client.get(LB, endpoint + artist["mbid"], params)
                        if kind == "popularity":
                            if not isinstance(data, list):
                                raise ValueError("Malformed popularity response")
                            for row in data[:1000]:
                                rid = row.get("recording_mbid")
                                if valid_mbid(rid):
                                    popularity[(artist["mbid"], rid)] = {"recording_mbid": rid, "artist_mbid": artist["mbid"], "total_listen_count": row.get("total_listen_count"), "total_user_count": row.get("total_user_count"), "source": "listenbrainz", "license": "CC0-1.0", "retrieved_at": client.last_retrieved_at or utc_now()}
                        else:
                            if not isinstance(data, dict):
                                raise ValueError("Malformed related-artist response")
                            for aid, recordings in list(data.items())[:100]:
                                if aid == artist["mbid"] or not valid_mbid(aid) or not isinstance(recordings, list):
                                    continue
                                for row in recordings[:5]:
                                    rid = row.get("recording_mbid")
                                    if valid_mbid(rid):
                                        edges[(artist["mbid"], aid, rid)] = {"seed_artist_mbid": artist["mbid"], "candidate_artist_mbid": aid, "recording_mbid": rid, "candidate_artist_name": row.get("similar_artist_name"), "total_listen_count": row.get("total_listen_count"), "source": "listenbrainz", "kind": "provider_artist_based_recommendation", "mode": "easy", "score": None, "license": "CC0-1.0", "retrieved_at": client.last_retrieved_at or utc_now()}
                            missing = list(dict.fromkeys(e["recording_mbid"] for e in edges.values() if e["recording_mbid"] not in tracks))
                            for start in range(0, len(missing), 25):
                                metadata = client.get(LB, "metadata/recording/", {"recording_mbids": ",".join(missing[start:start + 25]), "inc": "artist release"})
                                if not isinstance(metadata, dict):
                                    raise ValueError("Malformed neighbor metadata")
                                for rid, entry in metadata.items():
                                    if not valid_mbid(rid) or not isinstance(entry, dict) or len(tracks) >= max_recordings:
                                        continue
                                    recording = entry.get("recording", {})
                                    credit = entry.get("artist", {})
                                    title = recording.get("name")
                                    if not title:
                                        continue
                                    credits = credit.get("artists", [])
                                    tracks[rid] = {"mbid": rid, "title": title, "artist_names": [c["name"] for c in credits if c.get("name")], "artist_mbids": [c["artist_mbid"] for c in credits if valid_mbid(c.get("artist_mbid"))], "duration_ms": recording.get("length"), "first_release_date": None, "releases": [], "isrcs": [], "source": "listenbrainz_musicbrainz_metadata", "license": "CC0-1.0", "retrieved_at": client.last_retrieved_at or utc_now()}
                    except BudgetExceeded:
                        raise
                    except (ValueError, RuntimeError, OSError) as exc:
                        artist["listening_complete"] = False
                        document["listening_complete"] = False
                        document["errors"].append({"artist": name, "provider": "listenbrainz", "endpoint": kind, "error": str(exc)[:300]})
            checkpoint()
        except BudgetExceeded:
            document["coverage_complete"] = False
            # Preserve the last atomic checkpoint instead of risking disk overflow.
            raise
        except (ValueError, RuntimeError, OSError) as exc:
            document["coverage_complete"] = False
            document["listening_complete"] = False
            document["errors"].append({"artist": name, "provider": "musicbrainz", "error": str(exc)[:300]})
            checkpoint()
    checkpoint()
    return document

