"""Request-local storage downloads with bounded transport calls for media reads.

Ordinary upload/index storage behavior is unchanged. Downloads live only as long
as the reconstruction worker; cancellation never truncates a shared cache file.
"""

import os
import tempfile

from open_webui.retrieval.reconstruction import ReconstructionControl
from open_webui.storage import provider as storage


DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def reconstruction_source_path(
    provider, source_path: str, control: ReconstructionControl
) -> str:
    control.timeout(30)
    if isinstance(provider, storage.LocalStorageProvider):
        path = provider.get_file(source_path)
        control.timeout(30)
        return path

    directory = control.resources.enter_context(
        tempfile.TemporaryDirectory(prefix="rag-media-")
    )
    destination = os.path.join(directory, "source")
    with open(destination, "wb") as target:
        if isinstance(provider, storage.S3StorageProvider):
            _download_s3(provider, source_path, target, control)
        elif isinstance(provider, storage.GCSStorageProvider):
            _download_gcs(provider, source_path, target, control)
        elif isinstance(provider, storage.AzureStorageProvider):
            _download_azure(provider, source_path, target, control)
        else:
            # An unknown implementation has no verified bounded download API.
            raise RuntimeError("Storage provider does not support bounded media reads")
    control.timeout(30)
    return destination


def _download_s3(provider, source_path, target, control):
    # A separate client keeps request timeouts and disabled retries local to this
    # reconstruction; the application's shared storage client is never mutated.
    timeout = control.timeout(30)
    client = storage.boto3.client(
        "s3",
        region_name=storage.S3_REGION_NAME,
        endpoint_url=storage.S3_ENDPOINT_URL,
        aws_access_key_id=storage.S3_ACCESS_KEY_ID,
        aws_secret_access_key=storage.S3_SECRET_ACCESS_KEY,
        config=provider.s3_client.meta.config.merge(
            storage.Config(
                connect_timeout=min(5, timeout),
                read_timeout=timeout,
                retries={"total_max_attempts": 1},
            )
        ),
    )
    try:
        control.timeout(30)
        response = client.get_object(
            Bucket=provider.bucket_name, Key=provider._extract_s3_key(source_path)
        )
        body = response["Body"]
        try:
            while True:
                body.set_socket_timeout(control.timeout(30))
                chunk = body.read(DOWNLOAD_CHUNK_BYTES)
                control.timeout(30)
                if not chunk:
                    return
                target.write(chunk)
        finally:
            body.close()
    finally:
        client.close()


def _download_gcs(provider, source_path, target, control):
    key = source_path.removeprefix("gs://").split("/", 1)[1]
    blob = provider.bucket.blob(key)
    blob.reload(timeout=control.timeout(30), retry=None)
    for offset in range(0, int(blob.size or 0), DOWNLOAD_CHUNK_BYTES):
        chunk = blob.download_as_bytes(
            start=offset,
            end=min(offset + DOWNLOAD_CHUNK_BYTES, blob.size) - 1,
            if_generation_match=blob.generation,
            timeout=control.timeout(30),
            retry=None,
        )
        control.timeout(30)
        target.write(chunk)


def _download_azure(provider, source_path, target, control):
    from azure.core import MatchConditions

    client = provider.container_client.get_blob_client(source_path.rsplit("/", 1)[-1])

    def options():
        remaining = control.timeout(30)
        return {
            "connection_timeout": min(5, remaining),
            "read_timeout": remaining,
            "retry_total": 0,
        }

    properties = client.get_blob_properties(**options())
    for offset in range(0, properties.size, DOWNLOAD_CHUNK_BYTES):
        chunk = client.download_blob(
            offset=offset,
            length=min(DOWNLOAD_CHUNK_BYTES, properties.size - offset),
            etag=properties.etag,
            match_condition=MatchConditions.IfNotModified,
            max_concurrency=1,
            **options(),
        ).readall()
        control.timeout(30)
        target.write(chunk)
