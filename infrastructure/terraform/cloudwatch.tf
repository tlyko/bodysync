# CloudWatch cost guard dla Anthropic spend (Sprint 6 Step 7 per ADR-006).
#
# Strategy:
# - advisor_dinner handler emituje structured log line `anthropic_call`
#   z `input_tokens`/`output_tokens` per call (patrz handlers/advisor_dinner/handler.py).
# - Metric filter capturuje obie wartości jako CloudWatch custom metrics
#   w namespace Bodysync/Advisor.
# - Alarm na sumę output tokens / dzień > 1.5M (~ $6 cost przy $4/Mtok output).
#   Defaultowy use case Owner ~5K tokens/dzień; 1.5M = 300x baseline = anomaly.
#
# MVP decision (per TODO.md): brak SNS topic + email subscription. Alarm w
# CloudWatch Console widoczny manualnie. Post-MVP backlog: SNS + email
# subscribe gdy realna integracja.

resource "aws_cloudwatch_log_metric_filter" "anthropic_input_tokens" {
  name           = "${local.project}-anthropic-input-tokens"
  log_group_name = "/aws/lambda/${local.project}-advisor-dinner"
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

  # Lambda log group jest tworzona przez `module.advisor_dinner` — depends_on
  # zapewnia kolejność (filter wymaga istniejącego log group).
  depends_on = [module.advisor_dinner]
}

resource "aws_cloudwatch_log_metric_filter" "anthropic_output_tokens" {
  name           = "${local.project}-anthropic-output-tokens"
  log_group_name = "/aws/lambda/${local.project}-advisor-dinner"
  pattern        = "{ $.msg = \"anthropic_call\" }"

  metric_transformation {
    name          = "AnthropicOutputTokens"
    namespace     = "Bodysync/Advisor"
    value         = "$.output_tokens"
    default_value = "0"
  }

  depends_on = [module.advisor_dinner]
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
  # MVP: brak SNS — alarm widoczny w CloudWatch Console. Post-MVP backlog:
  # SNS topic + email subscribe owner gdy realna integracja.
  alarm_actions = []
  ok_actions    = []

  tags = local.tags
}
