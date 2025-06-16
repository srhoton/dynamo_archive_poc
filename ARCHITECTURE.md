# DynamoDB Delete Archiving

## The Problem We're Solving

This architecture provides a pattern for automatically archiving deleted records from DynamoDB tables across any domain or service.

## Why This Pattern Works

### 1. Zero Impact on Your Application

Your application doesn't need to know anything about archiving. It just deletes records normally:

```python
# Your app code stays clean and simple
dynamodb.delete_item(
    TableName='users-table',
    Key={'PK': {'S': 'USER#123'}, 'SK': {'S': 'PROFILE'}}
)
```

The archiving happens transparently through DynamoDB Streams. No extra API calls, no performance impact, no code changes.

### 2. Guaranteed Capture

DynamoDB Streams guarantees at-least-once delivery of every change. When a record is deleted:
- DynamoDB captures the deletion event (including the full record that was deleted)
- The stream triggers our Lambda function
- The Lambda archives the deleted record to S3
- If anything fails, the built-in retry mechanism and DLQ ensure we don't lose data

This isn't a "best effort" solution - it's a guaranteed capture mechanism.

### 3. Complete Record Preservation

DynamoDB Streams with `NEW_AND_OLD_IMAGES` allows us to get the entire deleted record, not just the keys:

```json
{
  "eventName": "REMOVE",
  "dynamodb": {
    "Keys": {
      "PK": {"S": "USER#123"},
      "SK": {"S": "PROFILE"}
    },
    "OldImage": {
      "PK": {"S": "USER#123"},
      "SK": {"S": "PROFILE"},
      "email": {"S": "user@example.com"},
      "name": {"S": "John Doe"},
      "createdAt": {"S": "2023-01-15T10:30:00Z"},
      "preferences": {"M": {...}},
      "lastLogin": {"S": "2024-01-10T15:45:00Z"}
    }
  }
}
```

Everything that was in the record is preserved in the archive.

## DynamoDB TTL

TTL automatically deletes expired records based on a timestamp attribute, and these deletions flow through DynamoDB Streams just like manual deletions. This creates a powerful combination for data lifecycle management.

### How TTL Complements Archiving

When you enable TTL on your DynamoDB table:
1. You specify a timestamp attribute (e.g., `expiresAt`)
2. DynamoDB automatically deletes records when the current time passes that timestamp
3. The deletion triggers a stream event with `eventName: "REMOVE"`
4. Your Lambda archives the expired record to S3

The beauty is that TTL deletions include a special marker in the stream record:

```json
{
  "eventName": "REMOVE",
  "userIdentity": {
    "type": "Service",
    "principalId": "dynamodb.amazonaws.com"
  },
  "dynamodb": {
    "Keys": {...},
    "OldImage": {
      "PK": {"S": "SESSION#abc123"},
      "SK": {"S": "2024-01-15T10:30:00Z"},
      "userId": {"S": "USER#123"},
      "expiresAt": {"N": "1705315800"},  // The TTL attribute
      "sessionData": {"M": {...}}
    }
  }
}
```

### TTL Best Practices for Archiving

1. **Always include context in TTL'd records**: Since they'll be auto-deleted, make sure the archived record contains enough information to understand why it existed.

2. **Use meaningful TTL values**: Don't just delete after 30 days because it sounds good. Align TTL with business requirements.

3. **Consider archive retrieval in TTL planning**: If you might need the data 6 months later, make sure your S3 lifecycle policies keep it accessible.

## Record Retention Strategies

### Immediate Archiving to S3

The default pattern archives to S3 immediately, giving you:
- **11 9's of durability** - Your archived data is safer than your production data
- **Infinite retention** - Keep records as long as you need
- **Cost-effective storage** - S3 pricing beats keeping data in DynamoDB

### Lifecycle Management

For most use cases, you'll want tiered storage. For example:

```
Day 1-90: S3 Standard (immediate access)
Day 91-365: S3 Standard-IA (infrequent access, lower cost)
Day 366+: S3 Glacier Flexible Retrieval (rare access, minimal cost)
After 7 years: Delete (or move to Glacier Deep Archive)
```

This is all configured through S3 lifecycle policies - no Lambda changes needed.

## Cross-Domain Implementation

This pattern works identically across all your services because deleted records are deleted records, regardless of what they represent:

### Contact Service
```
Deleted records → Lambda → s3://archives/usr-contact-svc/2024/01/15/CONTACT#123.json
```
### Service Order Service
```
Deleted records → Lambda → s3://archives/sor-service-order-svc/2024/01/15/ORDER#456.json
```

### Unit Service
```
Deleted records → Lambda → s3://archives/unt-svc/2024/01/15/UNIT#789.json
```

Each service gets its own:
- DynamoDB table (with streams enabled)
- Lambda function (can be the same code, different environment variables)
- S3 path prefix for organization

But the core pattern never changes.

## Retrieval and Recovery

When you need to access archived data:

### Ad-Hoc Retrieval
```bash
# Find and download a specific deleted record
aws s3 cp s3://archives/user-service/2024/01/15/USER#123_PROFILE.json -
```

### Bulk Analysis
```bash
# Download all deleted user records from January
aws s3 sync s3://archives/user-service/2024/01/ ./january-deletions/
```

### Restoration (if needed)
The archived JSON contains the complete DynamoDB record format, making restoration straightforward:
```python
# Extract the OldImage and put it back
archived = json.load(open('archived_record.json'))
old_image = archived['dynamodb']['OldImage']

# Convert back to DynamoDB format and restore
dynamodb.put_item(TableName='users-table', Item=old_image)
```

## Implementation Checklist

When implementing this pattern for a new service:

1. **Enable DynamoDB Streams** on your table with `NEW_AND_OLD_IMAGES`
2. **Deploy the Lambda** (reuse the code, just change environment variables)
3. **Configure S3 path** to organize by service/date
4. **Set lifecycle policies** based on your retention requirements
5. **Enable TTL if appropriate** for automatic expiration of temporary data
6. **Test deletion and retrieval** before going to production (both manual and TTL deletions)
7. **Monitor the DLQ** to ensure everything is working

## Future Possibilities

While our focus is on archiving deleted records, this same event stream infrastructure opens doors for the future:

- **Analytics**: Those deletion events could feed into analytics pipelines
- **Compliance Reporting**: Generate deletion reports automatically
- **Soft Deletes**: Implement application-level soft deletes with automatic hard delete after X days
- **Data Lake Integration**: Archived records can be queried with Athena when needed
