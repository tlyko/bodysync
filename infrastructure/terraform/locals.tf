locals {
  project    = "bodysync"
  aws_region = "eu-west-1"

  tags = {
    Project   = local.project
    ManagedBy = "terraform"
    Repo      = "https://github.com/tlyko/bodysync"
  }

  account_id = data.aws_caller_identity.current.account_id

  # Owner email — SNS subscriber dla CloudWatch alarms (cost guard).
  # AWS SNS wymaga manual confirmation linkiem w mailu po pierwszym
  # subscribe (PendingConfirmation state until confirmed).
  owner_email = "tlyko94@gmail.com"

  # Custom domain dla API GW — frontend na bodysync.pl używa same-parent
  # cookie domain (.bodysync.pl) by sesyjny JWT cookie był dostępny
  # cross-subdomain.
  domain_root = "${local.project}.pl"
  api_domain  = "api.${local.domain_root}"

  # Single-table DDB (CLAUDE.md schemat). PK=USER#{id}, SK={TYPE}#{date}.
  # GSI-1 (inverted index SK→PK) służy do query po typie across users
  # (np. "wszystkie ACTIVITY z dzisiaj"). PITR włączony.
  ddb_table_name = "${local.project}-data"

  # S3 bucket dla raw payloads (Strava streams JSON, Health Auto Export raw,
  # FAISS index dla recipes). Bucket name globally unique → suffix account_id.
  data_bucket_name = "${local.project}-data-${local.account_id}"

  # SSM SecureString (per-user webhook secrets oddzielone żeby zgubienie
  # secret na jednym telefonie nie unieważniało drugiego). Wartości
  # placeholderowe — wpisujemy ręcznie konsolą AWS po deployu (lifecycle
  # ignore_changes pilnuje by Terraform nie unieważnił).
  ssm_securestrings = [
    "/bodysync/anthropic/api_key",
    "/bodysync/openai/api_key", # Sprint 6.2 RAG — embedding queries (text-embedding-3-small)
    "/bodysync/strava/client_secret",
    "/bodysync/strava/verify_token",
    "/bodysync/google/oauth_client_secret",
    "/bodysync/google/service_account_json",
    "/bodysync/health-auto-export/webhook_secret_tomek",
    "/bodysync/health-auto-export/webhook_secret_weronika",
    "/bodysync/jwt/signing_secret",
  ]

  ssm_strings = [
    "/bodysync/strava/client_id",
    # Sprint 4 — JSON map `{"<athlete_id>": "<bodysync_user_id>"}`, empty `{}`
    # przy starcie. Aktualizowany przez OAuth callback (PutParameter Overwrite=true).
    # Webhook handler reads to map `event.owner_id` na bodysync user_id.
    "/bodysync/strava/athlete-to-user",
    # Sprint 4 — populated przez `scripts/strava_subscribe.py` CLI po deploy.
    # Webhook identity check: event.subscription_id musi matchować ten id
    # (lub SYNTHETIC_SUBSCRIPTION_ID=999999 dla replay testów).
    "/bodysync/strava/subscription_id",
    "/bodysync/google/oauth_client_id",
    "/bodysync/auth/allowed_emails",
  ]

  # EventBridge cron rules. Targety dochodzą w Sprint 2+ kiedy Lambdy
  # będą gotowe; teraz same reguły bez handlerów (rule disabled żeby
  # nie generować invocation costów na pusto).
  eventbridge_rules = {
    training-sync = {
      schedule    = "cron(0 */6 * * ? *)"
      description = "Google Sheets training plan sync (every 6h)"
    }
    advisor-daily = {
      schedule    = "cron(0 19 * * ? *)" # 21:00 CET = 19:00 UTC
      description = "Daily kcal + meal advisor (21:00 CET)"
    }
    advisor-weekly = {
      schedule    = "cron(0 18 ? * SUN *)" # 20:00 CET Sun = 18:00 UTC
      description = "Weekly summary advisor (Sun 20:00 CET)"
    }
  }
}
