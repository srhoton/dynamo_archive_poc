terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket = "srhoton-tfstate"
    key    = "dynamo-archive-poc/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.region
}

# DynamoDB table with streams enabled
resource "aws_dynamodb_table" "dynamo_archive_poc" {
  name             = var.project_name
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "PK"
  range_key        = "SK"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  tags = {
    Name        = var.project_name
    Environment = var.environment
    Project     = var.project_name
  }
}

# S3 bucket for archived data
resource "aws_s3_bucket" "dynamo_archive_poc" {
  bucket = "srhoton-${var.project_name}"

  tags = {
    Name        = "srhoton-${var.project_name}"
    Environment = var.environment
    Project     = var.project_name
  }
}

# S3 bucket public access block
resource "aws_s3_bucket_public_access_block" "dynamo_archive_poc" {
  bucket = aws_s3_bucket.dynamo_archive_poc.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Local value for event bus name
locals {
  event_bus_name = coalesce(var.event_bus_name, var.project_name)
}

# EventBridge custom event bus
resource "aws_cloudwatch_event_bus" "dynamo_stream" {
  name = local.event_bus_name

  tags = {
    Name        = local.event_bus_name
    Environment = var.environment
    Project     = var.project_name
  }
}

# EventBridge pipe from DynamoDB stream to EventBridge
resource "aws_pipes_pipe" "dynamo_stream_to_eventbridge" {
  name     = "${var.project_name}-dynamo-stream-pipe"
  role_arn = aws_iam_role.eventbridge_pipe_role.arn

  source = aws_dynamodb_table.dynamo_archive_poc.stream_arn
  target = aws_cloudwatch_event_bus.dynamo_stream.arn

  source_parameters {
    dynamodb_stream_parameters {
      starting_position                  = "LATEST"
      batch_size                         = 10
      maximum_batching_window_in_seconds = 5
      parallelization_factor             = 1
      maximum_record_age_in_seconds      = 3600
      maximum_retry_attempts             = 3
      on_partial_batch_item_failure      = "AUTOMATIC_BISECT"
    }

    filter_criteria {
      filter {
        pattern = jsonencode({
          eventName = ["INSERT", "MODIFY", "REMOVE"]
        })
      }
    }
  }

  target_parameters {
    eventbridge_event_bus_parameters {
      detail_type = "DynamoDB Stream Event"
      source      = "custom.dynamodb"
    }
  }

  tags = {
    Name        = "${var.project_name}-dynamo-stream-pipe"
    Environment = var.environment
    Project     = var.project_name
  }
}