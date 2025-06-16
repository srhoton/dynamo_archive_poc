# SQS Dead Letter Queue for Lambda failures
resource "aws_sqs_queue" "lambda_dlq" {
  name                      = "${var.project_name}-lambda-dlq"
  message_retention_seconds = var.dlq_retention_days * 24 * 60 * 60

  tags = {
    Name        = "${var.project_name}-lambda-dlq"
    Environment = var.environment
    Project     = var.project_name
  }
}