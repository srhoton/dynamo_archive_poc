# Lambda deployment package
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../stream-lambda"
  output_path = "${path.module}/lambda_deployment.zip"
  excludes = [
    "test_lambda_function.py",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "pyproject.toml",
    ".gitignore"
  ]
}

# Lambda function
resource "aws_lambda_function" "dynamo_archive_processor" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = var.lambda_function_name
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.13"
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory_size
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  dead_letter_config {
    target_arn = aws_sqs_queue.lambda_dlq.arn
  }

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.dynamo_archive_poc.name
      S3_BUCKET_NAME      = aws_s3_bucket.dynamo_archive_poc.bucket
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_cloudwatch_log_group.lambda_logs
  ]

  tags = {
    Name        = var.lambda_function_name
    Environment = var.environment
    Project     = var.project_name
  }
}

# EventBridge rule to trigger Lambda on DynamoDB deletion events
resource "aws_cloudwatch_event_rule" "dynamo_delete_events" {
  name           = "${var.project_name}-dynamo-delete-events"
  description    = "Trigger Lambda for DynamoDB deletion events"
  event_bus_name = aws_cloudwatch_event_bus.dynamo_stream.name

  event_pattern = jsonencode({
    source      = ["custom.dynamodb"]
    detail-type = ["DynamoDB Stream Event"]
    detail = {
      eventName = ["REMOVE"]
    }
  })

  tags = {
    Name        = "${var.project_name}-dynamo-delete-events"
    Environment = var.environment
    Project     = var.project_name
  }
}

# EventBridge target to invoke Lambda
resource "aws_cloudwatch_event_target" "lambda_target" {
  rule           = aws_cloudwatch_event_rule.dynamo_delete_events.name
  target_id      = "lambda-target"
  arn            = aws_lambda_function.dynamo_archive_processor.arn
  event_bus_name = aws_cloudwatch_event_bus.dynamo_stream.name
}

# Lambda permission for EventBridge to invoke the function
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dynamo_archive_processor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.dynamo_delete_events.arn
}