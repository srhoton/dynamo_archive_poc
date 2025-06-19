variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "development"
}

variable "project_name" {
  description = "Project name for tagging"
  type        = string
  default     = "dynamo-archive-poc"
}

variable "lambda_function_name" {
  description = "Name of the Lambda function"
  type        = string
  default     = "dynamo-archive-stream-processor"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "lambda_memory_size" {
  description = "Lambda function memory size in MB"
  type        = number
  default     = 256
}

variable "lambda_batch_size" {
  description = "Number of records to process in a single Lambda invocation"
  type        = number
  default     = 10
}

variable "lambda_batching_window_seconds" {
  description = "Maximum time to wait for records before invoking Lambda"
  type        = number
  default     = 5
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 14
}

variable "dlq_retention_days" {
  description = "Dead Letter Queue message retention in days"
  type        = number
  default     = 14
}

variable "event_bus_name" {
  description = "Name of the EventBridge event bus"
  type        = string
  default     = null

  validation {
    condition     = var.event_bus_name == null || can(regex("^[a-zA-Z0-9._-]+$", var.event_bus_name))
    error_message = "Event bus name must contain only alphanumeric characters, periods, hyphens, and underscores."
  }
}