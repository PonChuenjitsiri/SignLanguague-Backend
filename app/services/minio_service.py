"""
MinIO service — handles file uploads to MinIO object storage.
"""

import os
from io import BytesIO
from minio import Minio
from minio.error import S3Error
from dotenv import load_dotenv

load_dotenv()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "smartglove-images")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"


class MinioService:
    """MinIO client wrapper for file uploads."""

    _client: Minio = None

    @classmethod
    def get_client(cls) -> Minio:
        if cls._client is None:
            cls._client = Minio(
                MINIO_ENDPOINT,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=MINIO_SECURE,
            )
        return cls._client

    @classmethod
    def ensure_bucket(cls):
        """Create the bucket if it doesn't exist."""
        client = cls.get_client()
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
            # Set bucket policy to public read
            import json
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{MINIO_BUCKET}/*"],
                    }
                ],
            }
            client.set_bucket_policy(MINIO_BUCKET, json.dumps(policy))
            print(f"✅ MinIO bucket '{MINIO_BUCKET}' created (public read)")
        else:
            print(f"✅ MinIO bucket '{MINIO_BUCKET}' exists")

    @classmethod
    def upload_file(cls, file_data: bytes, object_name: str, content_type: str = "image/png") -> str:
        """
        Upload a file to MinIO and return the public URL.

        Args:
            file_data: Raw file bytes
            object_name: Path in bucket (e.g. "signs/hello.png")
            content_type: MIME type

        Returns:
            Public URL string
        """
        client = cls.get_client()
        data = BytesIO(file_data)

        client.put_object(
            MINIO_BUCKET,
            object_name,
            data,
            length=len(file_data),
            content_type=content_type,
        )

        # Build public URL
        if MINIO_PUBLIC_URL:
            # If public URL is provided (e.g. http://100.110.16.105:9000), use it
            url = f"{MINIO_PUBLIC_URL.rstrip('/')}/{MINIO_BUCKET}/{object_name}"
        else:
            # Fallback to endpoint
            protocol = "https" if MINIO_SECURE else "http"
            url = f"{protocol}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_name}"
            
        return url

    @classmethod
    def delete_file(cls, object_name: str):
        """Delete a file from MinIO."""
        client = cls.get_client()
        try:
            client.remove_object(MINIO_BUCKET, object_name)
        except S3Error:
            pass
