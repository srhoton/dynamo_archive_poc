"""
Unit tests for the DynamoDB Stream Lambda function.
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
def sample_event(sample_dynamodb_record):
    """Sample Lambda event with DynamoDB records."""
    return {"Records": [sample_dynamodb_record]}


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


class TestLambdaHandler:
    """Test the main Lambda handler function."""

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    @mock_aws
    def test_lambda_handler_success(self, sample_event, sample_context):
        """Test successful Lambda execution."""
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="test-bucket")

        result = lambda_handler(sample_event, sample_context)

        assert result["processedCount"] == 1
        assert result["totalRecords"] == 1
        assert result["failedRecords"] == []

        response = s3_client.get_object(
            Bucket="test-bucket", Key="test-table/id_user-123_timestamp_1234567890.json"
        )
        archived_data = json.loads(response["Body"].read())
        assert archived_data == sample_event["Records"][0]

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    def test_lambda_handler_skip_non_delete(self, sample_event, sample_context):
        """Test Lambda handler skips non-DELETE events."""
        sample_event["Records"][0]["eventName"] = "INSERT"

        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="test-bucket")

            result = lambda_handler(sample_event, sample_context)

            assert result["processedCount"] == 0
            assert result["totalRecords"] == 1
            assert result["failedRecords"] == []

    @patch.dict(os.environ, {})
    def test_lambda_handler_missing_env_vars(self, sample_event, sample_context):
        """Test Lambda handler with missing environment variables."""
        with pytest.raises(ValueError, match="Required environment variable"):
            lambda_handler(sample_event, sample_context)

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    @mock_aws
    def test_lambda_handler_s3_error(self, sample_event, sample_context):
        """Test Lambda handler with S3 error."""
        with pytest.raises(Exception, match="Failed to process 1 records"):
            lambda_handler(sample_event, sample_context)

    @patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"})
    @mock_aws
    def test_lambda_handler_multiple_records(self, sample_dynamodb_record, sample_context):
        """Test Lambda handler with multiple records."""
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="test-bucket")

        record2 = sample_dynamodb_record.copy()
        record2["eventID"] = "test-event-id-456"
        record2["dynamodb"]["Keys"]["id"]["S"] = "user-456"

        record3 = sample_dynamodb_record.copy()
        record3["eventName"] = "INSERT"
        record3["eventID"] = "test-event-id-789"

        event = {"Records": [sample_dynamodb_record, record2, record3]}

        result = lambda_handler(event, sample_context)

        assert result["processedCount"] == 2
        assert result["totalRecords"] == 3
        assert result["failedRecords"] == []

    def test_lambda_handler_empty_records(self, sample_context):
        """Test Lambda handler with empty records."""
        event = {"Records": []}

        with patch.dict(
            os.environ, {"DYNAMODB_TABLE_NAME": "test-table", "S3_BUCKET_NAME": "test-bucket"}
        ):
            result = lambda_handler(event, sample_context)

            assert result["processedCount"] == 0
            assert result["totalRecords"] == 0
            assert result["failedRecords"] == []
