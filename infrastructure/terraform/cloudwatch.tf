# CloudWatch cost guard dla Anthropic spend (Sprint 6 Step 7 per ADR-006,
# rename advisor-dinner → advisor-chat per ADR-007 Sprint 6.1 PR1).
#
# Strategy:
# - advisor_chat handler emituje structured log line `anthropic_call`
#   z `input_tokens`/`output_tokens` per call (patrz handlers/advisor_chat/handler.py).
# - Metric filter capturuje obie wartości jako CloudWatch custom metrics
#   w namespace Bodysync/Advisor.
# - Alarm na sumę output tokens / dzień > 1.5M (~ $6 cost przy $4/Mtok output).
#   Defaultowy use case Owner ~5K tokens/dzień; 1.5M = 300x baseline = anomaly.
# - SNS topic → `telegram_notifier` Lambda → Telegram bota owner'a. Email
#   subscription porzucony bo Gmail auto-unsubuje SNS notyfikacje (alarm
#   dzwonił do void). Telegram daje confirmację dostarczenia + zero opt-out
#   na delivery side.
#
# Post-deploy manual: owner wpisuje `bot_token` (od @BotFather) i `chat_id`
# (private chat z botem) do SSM SecureString/String. Bez tego notifier
# loguje warning i no-op'uje (PLACEHOLDER guard w handlerze).

resource "aws_cloudwatch_log_metric_filter" "anthropic_input_tokens" {
  name           = "${local.project}-anthropic-input-tokens"
  log_group_name = "/aws/lambda/${local.project}-advisor-chat"
  # JSON pattern — handler emituje JsonFormatter z msg=anthropic_call.
  # `$.msg = "anthropic_call"` filtruje tylko te eventy (cache_hit logi
  # mają inny msg, są ignorowane).
  pattern = "{ $.msg = \"anthropic_call\" }"

  metric_transformation {
    name          = "AnthropicInputTokens"
    namespace     = "Bodysync/Advisor"
    value         = "$.input_tokens"
    default_value = "0"
  }

  # Lambda log group jest tworzona przez `module.advisor_chat` — depends_on
  # zapewnia kolejność (filter wymaga istniejącego log group).
  depends_on = [module.advisor_chat]
}

resource "aws_cloudwatch_log_metric_filter" "anthropic_output_tokens" {
  name           = "${local.project}-anthropic-output-tokens"
  log_group_name = "/aws/lambda/${local.project}-advisor-chat"
  pattern        = "{ $.msg = \"anthropic_call\" }"

  metric_transformation {
    name          = "AnthropicOutputTokens"
    namespace     = "Bodysync/Advisor"
    value         = "$.output_tokens"
    default_value = "0"
  }

  depends_on = [module.advisor_chat]
}

# Cost guard alarm — Anthropic Haiku 4.5 output ~$4/Mtok. Próg 1.5M tokens/day
# = ~$6 (znacznie powyżej oczekiwanego baseline ~5k tokens/dzień). Tunable
# post-deploy po pierwszym tygodniu real usage.
resource "aws_cloudwatch_metric_alarm" "anthropic_daily_cost_high" {
  alarm_name          = "${local.project}-anthropic-daily-cost-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "AnthropicOutputTokens"
  namespace           = "Bodysync/Advisor"
  period              = 86400 # 1 day
  statistic           = "Sum"
  threshold           = 1500000
  alarm_description   = "Anthropic Haiku output tokens > 1.5M/day (~$6 cost). Daily baseline ~5k. Alarm = anomaly indicator (auth bypass, runaway loop, accidental ?force=true on every call)."
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.cost_guard.arn]
  ok_actions          = [aws_sns_topic.cost_guard.arn]

  tags = local.tags
}

# SNS topic dla cost guard alarms — output token threshold breach + recovery.
# Subscriber: telegram_notifier Lambda (poniżej).
resource "aws_sns_topic" "cost_guard" {
  name = "${local.project}-cost-guard"
  tags = local.tags
}

# Telegram notifier Lambda — SNS subscriber. Forwarduje CloudWatch alarm
# payload (ALARM/OK transition) na Telegram bota. Stdlib only (`urllib`),
# 256MB / 5s. Per-handler IAM: read SSM bot_token (SecureString) + chat_id
# (String). SSM placeholdery tworzone w `ssm.tf` przez `locals.ssm_*`.
module "telegram_notifier" {
  source = "./modules/lambda"

  project       = local.project
  function_name = "telegram-notifier"
  source_zip    = "${path.module}/../../apps/api/dist/telegram_notifier.zip"
  handler       = "handlers.telegram_notifier.handler.handler"
  memory_size   = 256
  timeout       = 5

  environment = {
    ENV = "prod"
  }

  extra_iam_statements = [
    {
      Sid    = "ReadTelegramSecrets"
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/telegram/bot_token",
        "arn:aws:ssm:${local.aws_region}:${local.account_id}:parameter/bodysync/telegram/chat_id",
      ]
    },
  ]
}

# SNS subscription: cost-guard topic → telegram_notifier Lambda.
resource "aws_sns_topic_subscription" "cost_guard_telegram" {
  topic_arn = aws_sns_topic.cost_guard.arn
  protocol  = "lambda"
  endpoint  = module.telegram_notifier.function_arn
}

# SNS principal musi mieć permission do invoke Lambdy — bez tego SNS dostaje
# AccessDenied i alarm tonie (delivery policy retries → eventually drop).
resource "aws_lambda_permission" "telegram_notifier_sns" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.telegram_notifier.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.cost_guard.arn
}
