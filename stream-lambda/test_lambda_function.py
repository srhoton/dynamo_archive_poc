"""
Unit tests for the EventBridge Lambda function that processes DynamoDB stream events.
"""

import json
import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from lambda_function import (
    _archive_record_to_s3,
    _extract_dynamodb_record,
    _get_env_variable,
    _get_record_id,
    _is_delete_event,
    lambda_handler,
)


@pytest.fixture
def sample_dynamodb_record():
    """Sample DynamoDB stream record for testing."""
    return {
        "eventID": "test-event-id-123",
        "eventName": "REMOVE",
        "eventVersion": "1.1",
        "eventSource": "aws:dynamodb",
        "awsRegion": "us-east-1",
        "dynamodb": {
            "ApproximateCreationDateTime": 1234567890,
            "Keys": {"id": {"S": "user-123"}, "timestamp": {"N": "1234567890"}},
            "OldImage": {
                "id": {"S": "user-123"},
                "name": {"S": "John Doe"},
                "email": {"S": "john@example.com"},
                "timestamp": {"N": "1234567890"},
            },
            "SequenceNumber": "123456789012345678901",
            "SizeBytes": 123,
            "StreamViewType": "OLD_AND_NEW_IMAGES",
        },
    }


@pytest.fixture
def sample_eventbridge_event(sample_dynamodb_record):
    """Sample EventBridge event containing DynamoDB stream data."""
    return {
        "version": "0",
        "id": "event-id-123",
        "detail-type": "DynamoDB Stream Event",
        "source": "custom.dynamodb",
        "account": "123456789012",
        "time": "2023-01-01T12:00:00Z",
        "region": "us-east-1",
        "detail": sample_dynamodb_record
    }


@pytest.fixture
def sample_context():
    """Sample Lambda context."""
    context = MagicMock()
    context.function_name = "test-function"
    context.function_version = "1"
    context.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
    context.memory_limit_in_mb = 128
    context.remaining_time_in_millis = lambda: 30000
    return context


class TestEnvironmentVariables:
    """Test environment variable handling."""

    def test_get_env_variable_success(self):
        """Test successful environment variable retrieval."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            result = _get_env_variable("TEST_VAR")
            assert result == "test_value"

    def test_get_env_variable_missing(self):
        """Test error when environment variable is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                ValueError, match="Required environment variable TEST_VAR is not set"
            ):
                _get_env_variable("TEST_VAR")

    def test_get_env_variable_empty(self):
        """Test error when environment variable is empty."""
        with patch.dict(os.environ, {"TEST_VAR": ""}):
            with pytest.raises(
                ValueError, match="Required environment variable TEST_VAR is not set"
            ):
                _get_env_variable("TEST_VAR")


class TestRecordProcessing:
    """Test DynamoDB record processing functions."""

    def test_is_delete_event_remove(self, sample_dynamodb_record):
        """Test identification of DELETE events."""
        assert _is_delete_event(sample_dynamodb_record) is True

    def test_is_delete_event_insert(self, sample_dynamodb_record):
        """Test identification of non-DELETE events."""
        sample_dynamodb_record["eventName"] = "INSERT"
        assert _is_delete_event(sample_dynamodb_record) is False

    def test_is_delete_event_modify(self, sample_dynamodb_record):
        """Test identification of MODIFY events."""
        sample_dynamodb_record["eventName"] = "MODIFY"
        assert _is_delete_event(sample_dynamodb_record) is False

    def test_get_record_id_with_keys(self, sample_dynamodb_record):
        """Test record ID extraction with DynamoDB keys."""
        record_id = _get_record_id(sample_dynamodb_record)
        assert record_id == "id_user-123_timestamp_1234567890"

    def test_get_record_id_without_keys(self, sample_dynamodb_record):
        """Test record ID extraction without DynamoDB keys."""
        del sample_dynamodb_record["dynamodb"]["Keys"]
        record_id = _get_record_id(sample_dynamodb_record)
        assert record_id == "test-event-id-123"

    def test_get_record_id_empty_record(self):
        """Test record ID extraction from empty record."""
        record = {}
        record_id = _get_record_id(record)
        assert record_id == "unknown"


class TestS3Archiving:
    """Test S3 archiving functionality."""

    @mock_aws
    def test_archive_record_to_s3_success(self, sample_dynamodb_record):
        """Test successful S3 archiving."""
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="test-bucket")

        _archive_record_to_s3(sample_dynamodb_record, "test-table", "test-bucket")

        response = s3_client.get_object(
            Bucket="test-bucket", Key="test-table/id_user-123_timestamp_1234567890.json"
        )

        archived_data = json.loads(response["Body"].read())
        assert archived_data == sample_dynamodb_record
        assert response["ContentType"] == "application/json"

    @mock_aws
    def test_archive_record_to_s3_client_error(self, sample_dynamodb_record):
        """Test S3 archiving with client error."""
        with pytest.raises(ClientError):
            _archive_record_to_s3(sample_dynamodb_record, "test-table", "nonexistent-bucket")


class TestEventBridgeExtraction:
    """Test EventBridge event extraction functionality."""

    def test_extract_dynamodb_record_success(self, sample_eventbridge_event, sample_dynamodb_record):
        """Test successful extraction of DynamoDB record from EventBridge event."""
        result = _extract_dynamodb_record(sample_eventbridge_event)
        assert result == sample_dynamodb_record

    def test_extract_dynamodb_record_wrong_source(self, sample_eventbridge_event):
        """Test extraction fails with wrong source."""
        sample_eventbridge_event["source"] = "wrong.source"
        result = _extract_dynamodb_record(sample_eventbridge_event)
        assert result is None

    def test_extract_dynamodb_record_wrong_detail_type(self, sample_eventbridge_event):
        """Test extraction fails with wrong detail-type."""
        sample_eventbridge_event["detail-type"] = "Wrong Event Type"
        result = _extract_dynamodb_record(sample_eventbridge_event)
        assert result is None

    def test_extract_dynamodb_record_empty_detail(self, sample_eventbridge_event):
        """Test extraction fails with empty detail."""
        sample_eventbridge_event["detail"] = {}
        result = _extract_dynamodb_record(sample_eventbridge_event)
        assert result is None

    def test_extract_dynamodb_record_missing_detail(self, sample_eventbridge_event):
        """Test extraction fails with missing detail."""
        del sample_eventbridge_event["detail"]
        result = _extract_dynamodb_record(sample_eventbridge_event)
        assert result is None

    def test_extract_dynamodb_record_malformed_event(self):
        """Test extraction handles malformed events gracefully."""
        malformed_event = {"not": "valid"}
        result = _extract_dynamodb_record(malformed_event)
        assert result is None


class TestLambdaHandler:
    """Test the main Lambda handler function."""

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    @mock_aws
    def test_lambda_handler_success(self, sample_eventbridge_event, sample_context):
        """Test successful Lambda execution with EventBridge event."""
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="test-bucket")

        result = lambda_handler(sample_eventbridge_event, sample_context)

        assert result["processedCount"] == 1
        assert result["totalRecords"] == 1
        assert result["failedRecords"] == []

        response = s3_client.get_object(
            Bucket="test-bucket", Key="test-table/id_user-123_timestamp_1234567890.json"
        )
        archived_data = json.loads(response["Body"].read())
        assert archived_data == sample_eventbridge_event["detail"]

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    def test_lambda_handler_skip_non_delete(self, sample_eventbridge_event, sample_context):
        """Test Lambda handler skips non-DELETE events."""
        sample_eventbridge_event["detail"]["eventName"] = "INSERT"

        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")

            result = lambda_handler(sample_eventbridge_event, sample_context)

            assert result["processedCount"] == 0
            assert result["totalRecords"] == 1
            assert result["failedRecords"] == []

    @patch.dict(os.environ, {})
    def test_lambda_handler_missing_env_vars(self, sample_eventbridge_event, sample_context):
        """Test Lambda handler with missing environment variables."""
        with pytest.raises(ValueError, match="Required environment variable"):
            lambda_handler(sample_eventbridge_event, sample_context)

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    @mock_aws
    def test_lambda_handler_s3_error(self, sample_eventbridge_event, sample_context):
        """Test Lambda handler with S3 error."""
        with pytest.raises(Exception, match="Failed to process 1 records"):
            lambda_handler(sample_eventbridge_event, sample_context)

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    def test_lambda_handler_invalid_eventbridge_event(self, sample_context):
        """Test Lambda handler with invalid EventBridge event."""
        invalid_event = {
            "source": "wrong.source",
            "detail-type": "Wrong Type",
            "detail": {}
        }

        result = lambda_handler(invalid_event, sample_context)

        assert result["processedCount"] == 0
        assert result["totalRecords"] == 0
        assert result["failedRecords"] == []

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    def test_lambda_handler_missing_detail(self, sample_context):
        """Test Lambda handler with EventBridge event missing detail."""
        event_without_detail = {
            "source": "custom.dynamodb",
            "detail-type": "DynamoDB Stream Event"
        }

        result = lambda_handler(event_without_detail, sample_context)

        assert result["processedCount"] == 0
        assert result["totalRecords"] == 0
        assert result["failedRecords"] == []
