# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-lambda-logs"
    Environment = var.environment
    Project     = var.project_name
  }
}