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

# DynamoDB stream event source mapping
resource "aws_lambda_event_source_mapping" "dynamo_stream_trigger" {
  event_source_arn                   = aws_dynamodb_table.dynamo_archive_poc.stream_arn
  function_name                      = aws_lambda_function.dynamo_archive_processor.arn
  starting_position                  = "LATEST"
  batch_size                         = var.lambda_batch_size
  maximum_batching_window_in_seconds = var.lambda_batching_window_seconds

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["REMOVE"]
      })
    }
  }
}