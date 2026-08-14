# Placeholdery dla sekretów. Wartości wpisuje user ręcznie w AWS Console
# po deployu — `lifecycle.ignore_changes = [value]` pilnuje, by Terraform
# nie unieważnił sekretu na kolejnych apply'ach.

resource "aws_ssm_parameter" "securestring" {
  for_each = toset(local.ssm_securestrings)

  name  = each.value
  type  = "SecureString"
  value = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "string" {
  for_each = toset(local.ssm_strings)

  name  = each.value
  type  = "String"
  value = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}
