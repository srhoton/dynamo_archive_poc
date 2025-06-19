# DynamoDB Archive POC

A proof of concept demonstrating automatic archiving of deleted DynamoDB records to S3 using AWS EventBridge, Lambda, and DynamoDB Streams.

## Overview

This project provides a serverless solution for preserving deleted DynamoDB records by automatically archiving them to S3. The architecture uses AWS EventBridge to create a decoupled, event-driven system where DynamoDB stream events are filtered and only deletion events trigger Lambda processing. This approach significantly reduces Lambda invocations and costs while providing a scalable, maintainable archival solution.

## Architecture

![DynamoDB Archive POC Architecture](DynamoDB%20Archive%20POC%20Architecture.png)

The architecture implements an event-driven data archival system using AWS EventBridge to decouple DynamoDB streams from Lambda processing:

**Data Flow:**
1. **DynamoDB Table** with streams captures all table changes (INSERT/MODIFY/REMOVE)
2. **EventBridge Pipes** reads from DynamoDB stream and forwards events to EventBridge
3. **EventBridge Bus** receives all stream events and routes them to filtering rules
4. **EventBridge Rule** filters for REMOVE events only and triggers Lambda
5. **Lambda Function** processes deletion events and archives data to S3
6. **Error Handling** via SQS Dead Letter Queue for failed executions
7. **Monitoring** through CloudWatch Logs for all Lambda activity

### Components

1. **DynamoDB Table**
   - Configured with streams enabled (`NEW_AND_OLD_IMAGES` view type)
   - Uses composite keys (PK and SK) for flexible data modeling
   - Pay-per-request billing mode for cost optimization
   - Stream captures all table changes in real-time

2. **EventBridge Pipes**
   - Connects DynamoDB stream to EventBridge custom bus
   - Batch size: 10 records, batching window: 5 seconds
   - Starting position: LATEST, parallelization factor: 1
   - Automatic retry: 3 attempts, max record age: 1 hour

3. **EventBridge Custom Bus**
   - Receives all DynamoDB stream events from pipes
   - Routes events to filtering rules based on event patterns
   - Source configured as `custom.dynamodb`

4. **EventBridge Rule**
   - Filters specifically for REMOVE (deletion) events
   - Pattern matches: `eventName = ["REMOVE"]`
   - Only triggers Lambda for deletion events, reducing invocations

5. **Lambda Function**
   - Python 3.13 runtime with 256MB memory, 300s timeout
   - Processes only filtered DELETE events from EventBridge
   - Archives deleted records as JSON files in S3
   - Includes comprehensive error handling and logging

6. **S3 Bucket**
   - Stores archived records in JSON format
   - Organized by table name and record ID
   - Configured with public access blocking for security
   - Bucket: `srhoton-dynamo-archive-poc`

7. **SQS Dead Letter Queue**
   - Captures failed Lambda processing attempts
   - 14-day message retention for troubleshooting
   - Configured as Lambda dead letter config

8. **CloudWatch Logs**
   - Lambda execution logs with 14-day retention
   - Structured logging for easy debugging and monitoring

9. **IAM Roles**
   - **Lambda Execution Role**: S3 write, SQS access, CloudWatch logs
   - **EventBridge Pipes Role**: DynamoDB stream read, EventBridge write
   - Follows principle of least privilege

## Features

- **Event-Driven Architecture**: Uses EventBridge for decoupled, scalable event processing
- **Selective Processing**: Only DELETE events trigger Lambda, significantly reducing invocations
- **Automatic Archiving**: Deleted records are automatically captured and stored in S3
- **Batch Processing**: EventBridge Pipes batches stream events for efficient Lambda execution
- **Error Resilience**: Multi-level error handling with retries and DLQ for failed records
- **Scalable**: Serverless architecture scales automatically with load
- **Cost-Effective**: Pay-per-use pricing with intelligent filtering to minimize costs
- **Monitoring**: Comprehensive CloudWatch logging and metrics
- **Security**: IAM least privilege with private S3 bucket and encrypted data
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
- **EventBridge Pipes**: Charged per event processed from DynamoDB stream
- **EventBridge**: Charged per event published to custom bus and rule evaluations
- **Lambda**: Charged per invocation and GB-seconds (significantly reduced due to filtering)
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
