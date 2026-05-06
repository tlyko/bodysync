locals {
  project    = "bodysync"
  aws_region = "eu-west-1"

  tags = {
    Project   = local.project
    ManagedBy = "terraform"
    Repo      = "https://github.com/tlyko/bodysync"
  }

  # Konfiguracja zasobów dochodzi w Step 4 (DDB / S3 / SSM / EventBridge).
  # Per ADR-003 trzymamy ją tu jako mapy/listy locals, nie jako moduły.
}
