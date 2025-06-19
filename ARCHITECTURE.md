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
- The stream flows through EventBridge Pipes to a custom EventBridge bus
- EventBridge rules filter for deletion events and trigger our Lambda function
- The Lambda archives the deleted record to S3
- If anything fails, the built-in retry mechanism and DLQ ensure we don't lose data

This isn't a "best effort" solution - it's a guaranteed capture mechanism with the added flexibility of event-driven architecture.

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
Deleted records → EventBridge → Lambda → s3://archives/usr-contact-svc/2024/01/15/CONTACT#123.json
```
### Service Order Service
```
Deleted records → EventBridge → Lambda → s3://archives/sor-service-order-svc/2024/01/15/ORDER#456.json
```

### Unit Service
```
Deleted records → EventBridge → Lambda → s3://archives/unt-svc/2024/01/15/UNIT#789.json
```

Each service gets its own:
- DynamoDB table (with streams enabled)
- EventBridge bus and rules (configurable event bus name)
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

## EventBridge Architecture Benefits

The implementation uses EventBridge as an intermediary between DynamoDB Streams and Lambda processing, providing several key advantages:

### Event-Driven Flexibility
- **Multiple Consumers**: The same DynamoDB stream events can trigger multiple different processing pipelines
- **Configurable Event Buses**: Each service can have its own isolated event bus or share a common one
- **Event Filtering**: EventBridge rules filter events before triggering Lambda, reducing unnecessary invocations
- **Loose Coupling**: Lambda functions are triggered by events, not directly coupled to DynamoDB streams

### Scalability and Extensibility
- **Fan-out Patterns**: One deletion event can trigger archiving, analytics, and notifications simultaneously
- **Future-Proof**: Easy to add new event consumers without modifying existing infrastructure
- **Cross-Service Events**: Events can be routed to different services based on business rules

### Architecture Flow
```
DynamoDB Table (with streams) 
    ↓
DynamoDB Stream
    ↓ 
EventBridge Pipe (captures all events: INSERT, MODIFY, REMOVE)
    ↓
Custom EventBridge Bus
    ↓
EventBridge Rule (filters for REMOVE events only)
    ↓
Lambda Function (processes deletion events)
    ↓
S3 Archive Storage
```

## Implementation Checklist

When implementing this pattern for a new service:

1. **Enable DynamoDB Streams** on your table with `NEW_AND_OLD_IMAGES`
2. **Configure EventBridge Bus** (use configurable `event_bus_name` variable or default to project name)
3. **Deploy EventBridge Pipe** to capture stream events and route to your event bus
4. **Set up EventBridge Rules** to filter for deletion events
5. **Deploy the Lambda** (reuse the code, just change environment variables)
6. **Configure S3 path** to organize by service/date
7. **Set lifecycle policies** based on your retention requirements
8. **Enable TTL if appropriate** for automatic expiration of temporary data
9. **Test deletion and retrieval** before going to production (both manual and TTL deletions)
10. **Monitor the DLQ** to ensure everything is working

## Future Possibilities

The EventBridge-based architecture significantly expands possibilities beyond just archiving deleted records:

### Immediate Enhancements
- **Analytics Pipelines**: All DynamoDB events (not just deletions) flow through EventBridge and can feed analytics systems
- **Real-time Notifications**: Alert systems when critical records are deleted
- **Compliance Reporting**: Generate deletion and modification reports automatically
- **Cross-Service Integration**: Events can trigger workflows in other services

### Advanced Patterns
- **Soft Deletes**: Implement application-level soft deletes with automatic hard delete after X days
- **Data Lake Integration**: All events (CREATE, UPDATE, DELETE) can be streamed to data lakes for comprehensive analytics
- **Event Sourcing**: Build event sourcing systems using the complete stream of DynamoDB changes
- **Multi-Region Replication**: Route events to trigger replication or backup processes in other regions

### EventBridge Native Features
- **Schema Registry**: Define and evolve event schemas over time
- **Event Replay**: Replay historical events for testing or recovery scenarios
- **Custom Applications**: Any application can subscribe to events by adding EventBridge rules
- **Third-Party Integrations**: Direct integration with SaaS applications that support EventBridge

The beauty of this architecture is that adding new capabilities requires only new EventBridge rules and targets - the core DynamoDB → EventBridge infrastructure remains unchanged.
