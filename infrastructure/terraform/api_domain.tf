# Custom domain `api.bodysync.pl` dla API Gateway HTTP. Frontend na
# bodysync.pl (Cloudflare Workers) potrzebuje same-parent cookie domain
# .bodysync.pl — JWT session cookie ustawiony przez api.bodysync.pl
# zostanie wysłany przez przeglądarkę na bodysync.pl (i odwrotnie).
#
# DNS w Cloudflare (user-managed):
#   1. ACM cert validation: po pierwszym apply, Terraform tworzy ACM cert
#      w stanie "Pending validation". User wpisuje CNAME validation record
#      w CF DNS (dane z `aws acm describe-certificate --certificate-arn ...`).
#   2. Po validation propagation (~5-15 min) — re-run apply, terraform
#      tworzy aws_apigatewayv2_domain_name + api_mapping.
#   3. User wpisuje główny CNAME `api` → target_domain_name w CF DNS
#      (dane z `aws apigatewayv2 get-domain-name --domain-name api.bodysync.pl`).
#   4. Endpoint live na https://api.bodysync.pl

resource "aws_acm_certificate" "api" {
  domain_name       = local.api_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn = aws_acm_certificate.api.arn

  # validation_record_fqdns: nie podajemy bo DNS jest w Cloudflare
  # (poza Terraform). Resource po prostu czeka aż ACM samo wykryje DNS
  # validation record (default timeout 45 min — wystarczy dla typowej
  # Cloudflare propagation).

  timeouts {
    create = "30m"
  }
}

resource "aws_apigatewayv2_domain_name" "api" {
  domain_name = local.api_domain

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.api.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "api" {
  api_id      = module.api_gateway.api_id
  domain_name = aws_apigatewayv2_domain_name.api.id
  stage       = "$default"
}
