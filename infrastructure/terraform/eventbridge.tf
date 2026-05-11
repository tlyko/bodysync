# Cron rules bez targetów — Lambdy dochodzą w Sprint 2-6, wtedy
# `aws_cloudwatch_event_target` linkuje rule → handler. Reguły
# DISABLED na razie — bez targetu i tak nic nie wywołują, ale
# explicit disabled chroni przed CloudWatch metric noise gdy ktoś
# w przyszłości doda buggy target przed rdy testem.
resource "aws_cloudwatch_event_rule" "scheduled" {
  for_each = local.eventbridge_rules

  name                = "${local.project}-${each.key}"
  description         = each.value.description
  schedule_expression = each.value.schedule
  state               = "DISABLED"
}

# Sprint 11 PR3 — Adaptive TDEE recalc cron (per ADR-008).
# Co 14 dni Lambda iteruje po hardcoded user list (event input), dla
# każdego user_id wykonuje recalc jeśli baseline_initialized + ≥10
# wag/kcal_in w 14d window. Skip scenarios są no-op (per-user log +
# aggregate `tdee_recalc_cron_complete` line dla CloudWatch).
#
# Standalone (nie w `local.eventbridge_rules` for_each) bo:
# - aktywna feature wymaga ENABLED, shared rules są DISABLED
# - target + permission per-Lambda — `for_each` by się rozsypał na
#   różnych targetach
# - nowy reader szuka "tdee_recalc" → znajduje cały bundle w jednym miejscu
resource "aws_cloudwatch_event_rule" "tdee_recalc_biweekly" {
  name                = "${local.project}-tdee-recalc-biweekly"
  description         = "Adaptive TDEE recalc co 14d (Sprint 11 ADR-008)"
  schedule_expression = "rate(14 days)"
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "tdee_recalc" {
  rule      = aws_cloudwatch_event_rule.tdee_recalc_biweekly.name
  target_id = "TdeeRecalcLambda"
  arn       = module.tdee_recalc.function_arn
  # Hardcoded user list mirror handlers/tdee_recalc/handler.py:CRON_USER_LIST.
  # Multi-user dynamic by wymagał osobnej `users` entity — YAGNI dla 2 userów.
  input = jsonencode({ users = ["tomek", "weronika"] })
}

resource "aws_lambda_permission" "tdee_recalc_eventbridge" {
  statement_id  = "AllowEventBridgeInvokeTdeeRecalc"
  action        = "lambda:InvokeFunction"
  function_name = module.tdee_recalc.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.tdee_recalc_biweekly.arn
}
