"""
EventBridge Lambda Function for archiving deleted DynamoDB records to S3.

This Lambda function processes EventBridge events containing DynamoDB stream data
and archives deleted records to an S3 bucket for long-term storage.
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
    AWS Lambda handler for processing EventBridge events containing DynamoDB stream data.

    Args:
        event: EventBridge event containing DynamoDB stream data
        context: Lambda context object

    Returns:
        Dictionary containing processing results

    Raises:
        Exception: Re-raises exceptions to trigger DLQ processing
    """
    try:
        table_name = _get_env_variable("DYNAMODB_TABLE_NAME")
        s3_bucket = _get_env_variable("S3_BUCKET_NAME")

        # Extract DynamoDB stream record from EventBridge event
        dynamodb_record = _extract_dynamodb_record(event)

        if not dynamodb_record:
            logger.warning("No valid DynamoDB record found in EventBridge event")
            return {
                "processedCount": 0,
                "totalRecords": 0,
                "failedRecords": []
            }

        processed_count = 0
        failed_records = []

        logger.info("Processing EventBridge event with DynamoDB stream data")

        try:
            if _is_delete_event(dynamodb_record):
                _archive_record_to_s3(dynamodb_record, table_name, s3_bucket)
                processed_count += 1
                logger.info(f"Archived deleted record: {_get_record_id(dynamodb_record)}")
            else:
                event_name = dynamodb_record.get('eventName', 'UNKNOWN')
                logger.debug(f"Skipping non-delete event: {event_name}")

        except Exception as e:
            logger.error(f"Failed to process record {_get_record_id(dynamodb_record)}: {str(e)}")
            failed_records.append({"recordId": _get_record_id(dynamodb_record), "error": str(e)})

        result = {
            "processedCount": processed_count,
            "totalRecords": 1,
            "failedRecords": failed_records,
        }

        logger.info(f"Processing complete: {result}")

        if failed_records:
            raise Exception(f"Failed to process {len(failed_records)} records")

        return result

    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}")
        raise


def _extract_dynamodb_record(event: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extract DynamoDB stream record from EventBridge event.

    Args:
        event: EventBridge event containing DynamoDB stream data

    Returns:
        DynamoDB stream record or None if not found
    """
    try:
        # EventBridge event structure has the DynamoDB stream record in the detail field
        detail = event.get("detail", {})

        # Validate that this is a DynamoDB stream event
        if event.get("source") != "custom.dynamodb":
            logger.warning(f"Event source is not custom.dynamodb: {event.get('source')}")
            return None

        if event.get("detail-type") != "DynamoDB Stream Event":
            detail_type = event.get('detail-type')
            logger.warning(f"Event detail-type is not DynamoDB Stream Event: {detail_type}")
            return None

        # The detail should contain the original DynamoDB stream record
        if not detail:
            logger.warning("EventBridge event detail is empty")
            return None

        return detail

    except Exception as e:
        logger.error(f"Failed to extract DynamoDB record from EventBridge event: {str(e)}")
        return None


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
