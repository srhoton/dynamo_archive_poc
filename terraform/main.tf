terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "srhoton-tfstate"
    key    = "dynamo-archive-poc/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_dynamodb_table" "dynamo_archive_poc" {
  name             = "dynamo-archive-poc"
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
    Name        = "dynamo-archive-poc"
    Environment = "development"
    Project     = "dynamo-archive-poc"
  }
}

resource "aws_s3_bucket" "dynamo_archive_poc" {
  bucket = "srhoton-dynamo-archive-poc"

  tags = {
    Name        = "srhoton-dynamo-archive-poc"
    Environment = "development"
    Project     = "dynamo-archive-poc"
  }
}

resource "aws_s3_bucket_public_access_block" "dynamo_archive_poc" {
  bucket = aws_s3_bucket.dynamo_archive_poc.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}