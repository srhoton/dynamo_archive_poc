# DynamoDB Archive POC

A proof of concept demonstrating automatic archiving of deleted DynamoDB records to S3 using AWS Lambda and DynamoDB Streams.

## Overview

This project provides a serverless solution for preserving deleted DynamoDB records by automatically archiving them to S3. When records are deleted from a DynamoDB table, a Lambda function triggered by DynamoDB Streams captures the deletion event and stores the deleted record's data in S3 for long-term retention and audit purposes.

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│                 │ DELETE   │                  │ Archive │                 │
│  DynamoDB Table │────────▶ │  Lambda Function │────────▶│   S3 Bucket     │
│  (with Streams) │ Events   │                  │  JSON   │                 │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                     │
                                     │ Failed
                                     │ Records
                                     ▼
                            ┌──────────────────┐
                            │   SQS DLQ        │
                            │                  │
                            └──────────────────┘
```

### Components

1. **DynamoDB Table**
   - Configured with streams enabled (`NEW_AND_OLD_IMAGES` view type)
   - Uses composite keys (PK and SK) for flexible data modeling
   - Pay-per-request billing mode for cost optimization

2. **Lambda Function**
   - Python 3.13 runtime
   - Processes DynamoDB stream events in batches
   - Filters for DELETE events only
   - Archives deleted records as JSON files in S3
   - Includes comprehensive error handling and logging

3. **S3 Bucket**
   - Stores archived records in JSON format
   - Organized by table name and record ID
   - Configured with public access blocking for security

4. **SQS Dead Letter Queue**
   - Captures failed processing attempts
   - 14-day retention for troubleshooting

5. **CloudWatch Logs**
   - Lambda execution logs with 14-day retention
   - Structured logging for easy debugging

## Features

- **Automatic Archiving**: Deleted records are automatically captured and stored
- **Selective Processing**: Only DELETE events are processed, reducing Lambda invocations
- **Error Resilience**: Failed records are sent to DLQ for later analysis
- **Scalable**: Serverless architecture scales automatically with load
- **Cost-Effective**: Pay-per-use pricing model with optimized batch processing
- **Testable**: Comprehensive unit tests with 100% code coverage

## Prerequisites

- AWS Account with appropriate permissions
- Terraform >= 1.0
- Python 3.13 (for local development/testing)
- AWS CLI configured with credentials

## Deployment

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd dynamo_archive_poc
   ```

2. Update the S3 backend configuration in `terraform/main.tf` if needed:
   ```hcl
   backend "s3" {
     bucket = "your-terraform-state-bucket"
     key    = "dynamo-archive-poc/terraform.tfstate"
     region = "us-east-1"
   }
   ```

3. Update the S3 bucket name in `terraform/main.tf` (must be globally unique):
   ```hcl
   resource "aws_s3_bucket" "dynamo_archive_poc" {
     bucket = "your-unique-bucket-name"
   }
   ```

4. Deploy the infrastructure:
   ```bash
   cd terraform
   terraform init
   terraform plan
   terraform apply
   ```

## Configuration

Key configuration variables in `terraform/variables.tf`:

| Variable | Default | Description |
|----------|---------|-------------|
| `lambda_timeout` | 300 | Lambda function timeout in seconds |
| `lambda_memory_size` | 256 | Lambda function memory in MB |
| `lambda_batch_size` | 10 | Records per Lambda invocation |
| `lambda_batching_window_seconds` | 5 | Max wait time for batch collection |
| `log_retention_days` | 14 | CloudWatch log retention period |
| `dlq_retention_days` | 14 | DLQ message retention period |

## Testing

### Unit Tests

Run the Lambda function unit tests:

```bash
cd stream-lambda
pip install -r requirements.txt
pytest test_lambda_function.py -v
```

### Integration Testing

1. Insert test data into the DynamoDB table:
   ```bash
   aws dynamodb put-item \
     --table-name dynamo-archive-poc \
     --item '{"PK": {"S": "USER#123"}, "SK": {"S": "PROFILE"}, "name": {"S": "Test User"}}'
   ```

2. Delete the item:
   ```bash
   aws dynamodb delete-item \
     --table-name dynamo-archive-poc \
     --key '{"PK": {"S": "USER#123"}, "SK": {"S": "PROFILE"}}'
   ```

3. Check the S3 bucket for the archived record:
   ```bash
   aws s3 ls s3://your-bucket-name/dynamo-archive-poc/
   ```

4. View the archived record:
   ```bash
   aws s3 cp s3://your-bucket-name/dynamo-archive-poc/PK_USER#123_SK_PROFILE.json -
   ```

## Archive File Format

Archived records are stored as JSON files with the following structure:

```json
{
  "eventID": "abc123...",
  "eventName": "REMOVE",
  "eventVersion": "1.1",
  "eventSource": "aws:dynamodb",
  "awsRegion": "us-east-1",
  "dynamodb": {
    "ApproximateCreationDateTime": 1234567890,
    "Keys": {
      "PK": {"S": "USER#123"},
      "SK": {"S": "PROFILE"}
    },
    "OldImage": {
      "PK": {"S": "USER#123"},
      "SK": {"S": "PROFILE"},
      "name": {"S": "Test User"},
      "email": {"S": "user@example.com"}
    },
    "SequenceNumber": "123456789012345678901",
    "SizeBytes": 123,
    "StreamViewType": "NEW_AND_OLD_IMAGES"
  }
}
```

## File Naming Convention

Archives are stored with the following path structure:
```
s3://bucket-name/table-name/key1_value1_key2_value2.json
```

Example:
```
s3://srhoton-dynamo-archive-poc/dynamo-archive-poc/PK_USER#123_SK_PROFILE.json
```

## Monitoring

### CloudWatch Metrics

Monitor Lambda performance via CloudWatch:
- Invocation count
- Error count
- Duration
- Concurrent executions

### DLQ Monitoring

Check for failed records:
```bash
aws sqs get-queue-attributes \
  --queue-url <dlq-url> \
  --attribute-names ApproximateNumberOfMessages
```

### Lambda Logs

View Lambda execution logs:
```bash
aws logs tail /aws/lambda/dynamo-archive-stream-processor --follow
```

## Cost Considerations

- **DynamoDB Streams**: Charged per read request unit
- **Lambda**: Charged per invocation and GB-seconds
- **S3**: Storage costs for archived data
- **CloudWatch Logs**: Log ingestion and storage

## Security

- Lambda function has minimal required permissions
- S3 bucket blocks all public access
- IAM roles follow the principle of least privilege
- Environment variables used for configuration

## Limitations

- Maximum Lambda timeout is 15 minutes
- DynamoDB stream records are available for 24 hours
- Maximum batch size is 1000 records

## Future Enhancements

- [ ] Add S3 lifecycle policies for archive tiering
- [ ] Implement SNS notifications for failures
- [ ] Add CloudWatch alarms for monitoring
- [ ] Support for multiple DynamoDB tables
- [ ] Add data encryption at rest
- [ ] Implement archive restoration functionality

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This is a proof of concept for demonstration purposes.
