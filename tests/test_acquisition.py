import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from data.acquisition import BudgetExceeded, ResponseTooLarge, CurlResponse, JsonClient, MB, collect, merge_recording, resolve_artist

A = "6925db17-f35e-42f3-a4eb-84ee6bf5d4b0"
R = "00000000-0000-4000-8000-000000000001"
S = "00000000-0000-4000-8000-000000000002"


class Response(io.BytesIO):
    headers = {}
    def geturl(self):
        return MB


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def client(self, opener, **kwargs):
        return JsonClient(self.root, opener=opener, sleeper=lambda _: None, **kwargs)

    def test_cached_calls_and_cumulative_budget_survive_restart(self):
        calls = []
        def opener(req, timeout):
            calls.append(req.full_url)
            return Response(b'{"ok":true}')
        client = self.client(opener, response_limit=20, transfer_limit=23)
        self.assertTrue(client.get(MB, "artist/a")["ok"])
        client = self.client(opener, response_limit=20, transfer_limit=23)
        client.get(MB, "artist/a")
        client.get(MB, "artist/b")
        self.assertEqual(len(calls), 2)
        with self.assertRaises(ResponseTooLarge):
            client.get(MB, "artist/c")
        self.assertEqual(client.ledger["payload_bytes"], 23)

    def test_large_response_never_saved_and_reservation_persists(self):
        client = self.client(lambda *a, **k: Response(b"x" * 50), response_limit=20)
        with self.assertRaises(ResponseTooLarge):
            client.get(MB, "recording")
        self.assertEqual(list(client.cache.glob("*")), [])
        self.assertEqual(json.loads(client.ledger_path.read_text())["payload_bytes"], 20)

    def test_error_payload_and_retry_after_are_counted(self):
        waits, calls = [], []
        def opener(req, timeout):
            calls.append(req)
            if len(calls) == 1:
                raise HTTPError(req.full_url, 429, "slow", {"Retry-After": "2"}, io.BytesIO(b"busy"))
            return Response(b"{}")
        client = self.client(opener)
        client.sleep = waits.append
        self.assertEqual(client.get(MB, "artist/a"), {})
        self.assertEqual(client.ledger["payload_bytes"], 6)
        self.assertIn(2.0, waits)

    def test_disk_peak_budget_and_exclusive_lock(self):
        client = self.client(None, disk_limit=5000)
        client.save(self.root / "test.json", {"a": "x" * 500})
        with self.assertRaises(BudgetExceeded):
            client.save(self.root / "other.json", {"a": "x" * 500})
        with client.exclusive():
            with self.assertRaises(RuntimeError):
                with client.exclusive():
                    pass
        self.assertFalse((self.root / "acquisition.lock").exists())

    def test_ambiguous_identity_is_not_auto_accepted(self):
        client = self.client(None)
        client.get = lambda *a, **k: {"artists": [{"id": A, "name": "Name", "score": 100}, {"id": R, "name": "Name", "score": 100}]}
        self.assertEqual(resolve_artist(client, "Name")["status"], "needs_identity_review")

    def test_pagination_deduplication_and_truncation(self):
        client = self.client(None)
        offsets = []
        def get(base, path, params):
            if path == "artist/":
                return {"artists": [{"id": A, "name": "Name", "score": 100}]}
            offsets.append(params.get("offset", 0))
            rows = [{"id": rid, "title": rid, "artist-credit": [{"artist": {"id": A, "name": "Name"}}]} for rid in ([R] if params.get("offset", 0) == 0 else [S])]
            return {"recording-count": 2, "recordings": rows}
        client.get = get
        result = collect(client, ["Name"], listenbrainz=False)
        self.assertEqual(offsets, [0, 1])
        self.assertEqual(len(result["tracks"]), 2)
        self.assertTrue(result["coverage_complete"])
        (self.root / "catalog.json").unlink()
        result = collect(client, ["Name"], max_recordings=1, listenbrainz=False)
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(len(result["tracks"]), 1)

    def test_failed_refresh_preserves_previously_acquired_tracks(self):
        client = self.client(None)
        client.save(self.root / "catalog.json", {"tracks": [{"mbid": R, "title": "Retained"}]})
        def fail(*args, **kwargs):
            raise ConnectionError("offline")
        client.get = fail
        result = collect(client, ["Name"], listenbrainz=False)
        self.assertEqual(result["tracks"][0]["title"], "Retained")
        self.assertFalse(result["coverage_complete"])

    def test_incomplete_credit_cannot_displace_complete_and_merges_associations(self):
        full = {"mbid": R, "credit_complete": True, "artist_names": ["A", "B"], "artist_mbids": [A, S]}
        partial = {"mbid": R, "credit_complete": False, "artist_names": ["A"], "artist_mbids": [A]}
        self.assertEqual(merge_recording(full, partial), full)
        other = dict(partial, artist_names=["B"], artist_mbids=[S])
        merged = merge_recording(partial, other)
        self.assertEqual(set(merged["artist_mbids"]), {A, S})
        self.assertFalse(merged["credit_complete"])

    def test_intermediate_page_checkpoint_is_incomplete(self):
        client = self.client(None)
        snapshots = []
        original_save = client.save
        def save(path, document):
            if Path(path).name == "catalog.json":
                snapshots.append(json.loads(json.dumps(document)))
            original_save(path, document)
        client.save = save
        def get(base, path, params):
            if path == "artist/":
                return {"artists": [{"id": A, "name": "Name", "score": 100}]}
            return {"recording-count": 1, "recordings": [{"id": R, "title": "Song"}]}
        client.get = get
        result = collect(client, ["Name"], listenbrainz=False)
        self.assertFalse(snapshots[0]["metadata_complete"])
        self.assertFalse(snapshots[0]["all_sources_complete"])
        self.assertTrue(result["metadata_complete"])
        self.assertFalse(result["tracks"][0]["credit_complete"])

    def test_provider_allowlist(self):
        client = self.client(None)
        with self.assertRaises(ValueError):
            client.get("https://unapproved.invalid/", "lyrics")

    def test_dead_provider_circuit_breaker_bounds_requests(self):
        calls = []
        def fail(request, timeout):
            calls.append(request.full_url)
            raise URLError("offline")
        client = self.client(fail, response_limit=100)
        for index in range(4):
            with self.assertRaises((URLError, ConnectionError)):
                client.get(MB, f"artist/{index}")
        self.assertEqual(len(calls), 9)
        self.assertEqual(client.ledger["payload_bytes"], 0)

    def test_verified_identity_configuration_needs_no_network(self):
        client = self.client(lambda *a, **k: self.fail("Unexpected identity lookup"))
        result = resolve_artist(client, "Name", {"Name": A})
        self.assertEqual(result["mbid"], A)
        self.assertEqual(result["identity_basis"], "operator_verified_file")

    def test_native_curl_response_blocks_and_failure_handling(self):
        class Process:
            def __init__(self, payload, code=0):
                self.stdout, self.code = io.BytesIO(payload), code
            def poll(self):
                return self.code
            def wait(self, timeout):
                return self.code
            def terminate(self):
                self.code = -1
        cases = [
            (b'HTTP/2 200 OK\r\nContent-Type: application/json\r\n\r\n{}', None),
            (b'HTTP/1.1 100 Continue\r\n\r\nHTTP/2 200 OK\r\n\r\n{}', None),
            (b'HTTP/2 429 Too Many Requests\r\nRetry-After: 2\r\n\r\nbusy', HTTPError),
            (b'HTTP/2 302 Found\r\nLocation: https://other.invalid\r\n\r\n', ValueError),
            (b'', ConnectionError),
        ]
        for payload, error in cases:
            with self.subTest(error=error), patch("data.acquisition.subprocess.Popen", return_value=Process(payload)) as launch:
                if error:
                    with self.assertRaises(error) as caught:
                        CurlResponse(Request(MB), 10)
                    if isinstance(caught.exception, HTTPError):
                        with caught.exception as response:
                            self.assertEqual(response.read(), b"busy")
                else:
                    with CurlResponse(Request(MB), 10) as response:
                        self.assertEqual(response.read(), b"{}")
                self.assertIn("--suppress-connect-headers", launch.call_args.args[0])
        with patch("data.acquisition.subprocess.Popen", return_value=Process(b'HTTP/2 200 OK\r\n\r\n', 35)):
            with CurlResponse(Request(MB), 10) as response:
                with self.assertRaises(ConnectionError):
                    response.read()


if __name__ == "__main__":
    unittest.main()

