"""
DynamoDB Stream Lambda Function for archiving deleted records to S3.

This Lambda function processes DynamoDB stream events and archives
deleted records to an S3 bucket for long-term storage.
"""

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler for processing DynamoDB stream events.

    Args:
        event: DynamoDB stream event containing records
        context: Lambda context object

    Returns:
        Dictionary containing processing results

    Raises:
        Exception: Re-raises exceptions to trigger DLQ processing
    """
    try:
        table_name = _get_env_variable("DYNAMODB_TABLE_NAME")
        s3_bucket = _get_env_variable("S3_BUCKET_NAME")

        records = event.get("Records", [])
        processed_count = 0
        failed_records = []

        logger.info(f"Processing {len(records)} DynamoDB stream records")

        for record in records:
            try:
                if _is_delete_event(record):
                    _archive_record_to_s3(record, table_name, s3_bucket)
                    processed_count += 1
                    logger.info(f"Archived deleted record: {_get_record_id(record)}")
                else:
                    logger.debug(f"Skipping non-delete event: {record.get('eventName', 'UNKNOWN')}")

            except Exception as e:
                logger.error(f"Failed to process record {_get_record_id(record)}: {str(e)}")
                failed_records.append({"recordId": _get_record_id(record), "error": str(e)})

        result = {
            "processedCount": processed_count,
            "totalRecords": len(records),
            "failedRecords": failed_records,
        }

        logger.info(f"Processing complete: {result}")

        if failed_records:
            raise Exception(f"Failed to process {len(failed_records)} records")

        return result

    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}")
        raise


def _get_env_variable(var_name: str) -> str:
    """Get required environment variable."""
    value = os.getenv(var_name)
    if not value:
        raise ValueError(f"Required environment variable {var_name} is not set")
    return value


def _is_delete_event(record: dict[str, Any]) -> bool:
    """Check if the DynamoDB stream record is a DELETE event."""
    return record.get("eventName") == "REMOVE"


def _get_record_id(record: dict[str, Any]) -> str:
    """Extract a unique identifier from the DynamoDB record."""
    dynamodb_data = record.get("dynamodb", {})
    keys = dynamodb_data.get("Keys", {})

    if not keys:
        return str(record.get("eventID", "unknown"))

    key_parts = []
    for key, value_dict in keys.items():
        for _value_type, value in value_dict.items():
            key_parts.append(f"{key}_{value}")

    return "_".join(key_parts) if key_parts else str(record.get("eventID", "unknown"))


def _archive_record_to_s3(record: dict[str, Any], table_name: str, s3_bucket: str) -> None:
    """
    Archive a DynamoDB stream record to S3.

    Args:
        record: DynamoDB stream record
        table_name: Name of the DynamoDB table
        s3_bucket: Name of the S3 bucket

    Raises:
        ClientError: If S3 operation fails
    """
    record_id = _get_record_id(record)
    s3_key = f"{table_name}/{record_id}.json"

    try:
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=s3_key,
            Body=json.dumps(record, indent=2, default=str),
            ContentType="application/json",
        )
        logger.info(f"Successfully archived record to s3://{s3_bucket}/{s3_key}")

    except ClientError as e:
        logger.error(f"Failed to upload to S3: {str(e)}")
        raise
