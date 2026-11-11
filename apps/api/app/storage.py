import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from .config import Settings, get_settings

ALLOWED_UPLOADS = {
    "image/jpeg": ("image", ".jpg", (b"\xff\xd8\xff",)),
    "image/png": ("image", ".png", (b"\x89PNG\r\n\x1a\n",)),
    "image/webp": ("image", ".webp", (b"RIFF",)),
    "video/mp4": ("video", ".mp4", (b"ftyp",)),
    "video/quicktime": ("video", ".mov", (b"ftyp", b"moov", b"wide", b"mdat")),
    "video/webm": ("video", ".webm", (b"\x1a\x45\xdf\xa3",)),
}


def signature_matches(content_type: str, head: bytes) -> bool:
    signatures = ALLOWED_UPLOADS[content_type][2]
    if content_type.startswith("video/") and content_type != "video/webm":
        return any(sig in head[:16] for sig in signatures)
    if content_type == "image/webp":
        return head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    return any(head.startswith(sig) for sig in signatures)


class LocalStorage:
    presigned = False

    def __init__(self, root: Path):
        self.root = root

    def path(self, key: str) -> Path:
        destination = (self.root / key).resolve()
        if not destination.is_relative_to(self.root.resolve()):
            raise ValueError("Invalid storage key")
        return destination

    def put_file(self, source: Path, key: str, content_type: str) -> str:
        destination = self.path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return key

    def head(self, key: str) -> int | None:
        target = self.path(key)
        return target.stat().st_size if target.exists() else None

    def read_prefix(self, key: str, size: int = 32) -> bytes:
        with self.path(key).open("rb") as handle:
            return handle.read(size)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    @contextmanager
    def local_copy(self, key: str) -> Iterator[Path]:
        yield self.path(key)

    def presign_put(self, key: str, content_type: str) -> str | None:
        return None

    def presign_get(self, key: str, content_type: str | None = None) -> str | None:
        return None

    def ensure_bucket(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


class S3Storage:
    presigned = True

    def __init__(self, settings: Settings):
        import boto3
        from botocore.config import Config

        config = Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3})
        common = {
            "aws_access_key_id": settings.s3_access_key,
            "aws_secret_access_key": settings.s3_secret_key,
            "region_name": settings.s3_region,
            "config": config,
        }
        self.bucket = settings.s3_bucket
        self.ttl = settings.signed_url_ttl_seconds
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint, **common)
        self.public_client = boto3.client("s3", endpoint_url=settings.s3_public_endpoint or settings.s3_endpoint, **common)

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_file(self, source: Path, key: str, content_type: str) -> str:
        self.client.upload_file(str(source), self.bucket, key, ExtraArgs={"ContentType": content_type})
        return key

    def head(self, key: str) -> int | None:
        from botocore.exceptions import ClientError

        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except ClientError:
            return None

    def read_prefix(self, key: str, size: int = 32) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes=0-{size - 1}")
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    @contextmanager
    def local_copy(self, key: str) -> Iterator[Path]:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / Path(key).name
            self.client.download_file(self.bucket, key, str(target))
            yield target

    def presign_put(self, key: str, content_type: str) -> str | None:
        return self.public_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=self.ttl,
        )

    def presign_get(self, key: str, content_type: str | None = None) -> str | None:
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ResponseContentType"] = content_type
        return self.public_client.generate_presigned_url("get_object", Params=params, ExpiresIn=self.ttl)


Storage = LocalStorage | S3Storage


def build_storage(settings: Settings) -> Storage:
    if settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key:
        return S3Storage(settings)
    return LocalStorage(settings.artifact_dir)


@lru_cache
def _default_storage() -> Storage:
    return build_storage(get_settings())


def get_storage() -> Storage:
    return _default_storage()
