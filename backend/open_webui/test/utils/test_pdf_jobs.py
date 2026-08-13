"""
The job store keeps PDF bytes in a Redis pool shared with the socket layer,
which is built with decode_responses=True. These tests stand in a client that
behaves the same way, so the round trip is covered without a live Redis.
"""

import pytest

from open_webui.utils import pdf_jobs

PDF = b"%PDF-1.7\n\x00\x01\x02\xff\xfe binary \xc3\x28 body\n%%EOF"


class DecodingRedis:
    """
    Mimics redis-py with decode_responses=True: values come back as str, and a
    value that is not valid UTF-8 raises on read exactly as the real client
    does. This is the behaviour that made completed exports unreadable.
    """

    def __init__(self):
        self.store = {}

    def set(self, key, value, ex=None):
        self.store[key] = value.encode() if isinstance(value, str) else value

    def get(self, key):
        raw = self.store.get(key)
        if raw is None:
            return None
        return raw.decode("utf-8")  # raises UnicodeDecodeError on binary


class TestPayloadRoundTrip:
    def test_binary_pdf_survives_a_decoding_client(self):
        client = DecodingRedis()
        client.set("k", pdf_jobs._encode_payload(PDF))
        assert pdf_jobs._decode_payload(client.get("k")) == PDF

    def test_raw_bytes_would_not_survive(self):
        """Guards the premise: without the wrapper the read is what fails."""
        client = DecodingRedis()
        client.set("k", PDF)
        with pytest.raises(UnicodeDecodeError):
            client.get("k")

    def test_encoded_payload_is_ascii(self):
        encoded = pdf_jobs._encode_payload(PDF)
        assert isinstance(encoded, str)
        encoded.encode("ascii")

    def test_decode_accepts_bytes_and_str(self):
        encoded = pdf_jobs._encode_payload(PDF)
        assert pdf_jobs._decode_payload(encoded) == PDF
        assert pdf_jobs._decode_payload(encoded.encode("ascii")) == PDF

    def test_legacy_unwrapped_value_is_returned_as_is(self):
        """A payload stored before the wrapper existed must not be mangled."""
        assert pdf_jobs._decode_payload(b"not base64 at all!!") == b"not base64 at all!!"

    @pytest.mark.parametrize("size", [0, 1, 1024, 500_000])
    def test_round_trip_at_several_sizes(self, size):
        blob = bytes(range(256)) * (size // 256) + b"\x00" * (size % 256)
        assert pdf_jobs._decode_payload(pdf_jobs._encode_payload(blob)) == blob


class TestMemoryStoreStillWorks:
    """The no-Redis path keeps raw bytes and must be untouched by the wrapper."""

    def test_submit_and_read_back_through_memory(self, monkeypatch):
        monkeypatch.setattr(pdf_jobs, "_get_redis", lambda: None)
        job_id = "job-mem"
        pdf_jobs._write(job_id, {"status": pdf_jobs.STATUS_COMPLETED}, data=PDF)

        assert pdf_jobs.result(job_id) == PDF
        assert pdf_jobs.status(job_id)["status"] == pdf_jobs.STATUS_COMPLETED


class TestRedisStoreRoundTrip:
    def test_completed_job_is_downloadable(self, monkeypatch):
        client = DecodingRedis()

        class HashRedis(DecodingRedis):
            def __init__(self):
                super().__init__()
                self.hashes = {}

            def hset(self, key, mapping=None):
                self.hashes.setdefault(key, {}).update(mapping or {})

            def expire(self, key, ttl):
                return True

            def hgetall(self, key):
                return dict(self.hashes.get(key, {}))

        client = HashRedis()
        monkeypatch.setattr(pdf_jobs, "_get_redis", lambda: client)

        job_id = "job-redis"
        pdf_jobs._write(
            job_id,
            {"status": pdf_jobs.STATUS_COMPLETED, "user_id": "u1", "size": len(PDF)},
            data=PDF,
        )

        assert pdf_jobs.status(job_id)["status"] == pdf_jobs.STATUS_COMPLETED
        assert pdf_jobs.result(job_id) == PDF


class TestReadDoesNotDropTheClientOnBadPayload:
    def test_unreadable_payload_leaves_the_client_in_place(self, monkeypatch):
        """
        A bad value must not be treated as a dead connection. _drop_redis()
        blinds the process for _REDIS_RETRY_SEC, which is what turned a single
        unreadable result into a minute of "PDF export job not found".
        """
        dropped = []

        class Weird(DecodingRedis):
            def get(self, key):
                return "!!!not-base64!!!"

        monkeypatch.setattr(pdf_jobs, "_get_redis", lambda: Weird())
        monkeypatch.setattr(pdf_jobs, "_drop_redis", lambda: dropped.append(True))

        pdf_jobs._read_data("whatever")
        assert dropped == []
