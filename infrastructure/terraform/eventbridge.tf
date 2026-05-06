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
