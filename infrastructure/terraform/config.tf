terraform {
  required_version = "~> 1.9"

  backend "s3" {
    bucket  = "syncbody-tfstate-214598715232"
    key     = "bodysync/terraform.tfstate"
    region  = "eu-west-1"
    encrypt = true

    # Replaces deprecated `dynamodb_table` (TF 1.10+). Locking via S3 .tflock
    # alongside the state file — same bucket, zero extra infra. The legacy
    # `syncbody-tflock` DDB table can be deleted by hand after a few clean
    # GHA runs.
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.43.0"
    }
  }
}

provider "aws" {
  region = local.aws_region

  default_tags {
    tags = local.tags
  }
}
