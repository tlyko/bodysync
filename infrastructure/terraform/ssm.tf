# Placeholdery dla sekretów. Wartości wpisuje user ręcznie w AWS Console
# po deployu — `lifecycle.ignore_changes = [value]` pilnuje, by Terraform
# nie unieważnił sekretu na kolejnych apply'ach.

# JEDNORAZOWY import — do usunięcia po pierwszym udanym apply (mirror
# sprzątania z PR #191).
#
# Sekret MCP został wpisany ręcznie ZANIM apply zdążył założyć zasób, więc
# `PutParameter` zwrócił `ParameterAlreadyExists` i wywalił cały apply.
# Wszystkie pozostałe zasoby MCP (Lambda, role, integracja, 7 tras) powstały
# poprawnie — brakuje wyłącznie tego jednego wpisu w stanie.
#
# Import adoptuje istniejący parametr zamiast go odtwarzać. Wartość jest
# bezpieczna: `ignore_changes = [value]` nie pozwoli nadpisać jej
# placeholderem z konfiguracji.
import {
  to = aws_ssm_parameter.securestring["/bodysync/mcp/token_signing_secret"]
  id = "/bodysync/mcp/token_signing_secret"
}
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
