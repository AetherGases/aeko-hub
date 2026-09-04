import boto3
import requests

from inventory_analysis.inventory_analysis import IRepository
from shared import Module, logged


s3_client = boto3.client("s3")


class Repository(IRepository):
    @logged(Module.DATABASE, "inventory.get_excel_bytes")
    def get_excel_bytes(self, s3: str) -> bytes:
        try:
            bucket, key = _normalize_s3_reference(s3)
            response = s3_client.get_object(
                Bucket=bucket,
                Key=key,
            )
            return response["Body"].read()
        except Exception as e:
            raise RuntimeError(f"Error fetching inventory file from S3: {e}")

    @logged(Module.INTEGRATION, "inventory.get_external_inventory_context")
    def get_external_inventory_context(self, id_external_inventory_4context: int) -> dict:
        try:
            response = requests.get(
                f"https://api.example.com/inventory/{id_external_inventory_4context}",
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise RuntimeError(f"Error fetching inventory context: {e}")


def _normalize_s3_reference(s3: str) -> tuple[str, str]:
    if s3.startswith("s3://"):
        without_scheme = s3.removeprefix("s3://")
        bucket, _, key = without_scheme.partition("/")
        if not bucket or not key:
            raise ValueError("Invalid S3 URI. Expected format: s3://bucket/key")
        return bucket, key

    if "/" not in s3:
        raise ValueError("Invalid S3 reference. Expected bucket/key or s3://bucket/key")

    bucket, key = s3.split("/", 1)
    if not bucket or not key:
        raise ValueError("Invalid S3 reference. Expected bucket/key or s3://bucket/key")
    return bucket, key
