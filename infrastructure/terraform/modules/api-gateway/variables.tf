variable "project" {
  type = string
}

variable "cors_allow_origins" {
  type    = list(string)
  default = ["https://bodysync.pl", "https://www.bodysync.pl"]
  # NIGDY localhost w prod (sec audit H1) — z `allow_credentials=true` to
  # vector data exfil dla XHR/fetch z dowolnej maszyny w cudzej sieci. Dev
  # frontend musi używać Vite proxy (`/api → https://api.bodysync.pl`) albo
  # osobnego staging API GW z osobnym CORS allowlist.
  #
  # Oba apex i www — Cloudflare custom domain mapuje oba na ten sam Worker,
  # browsery autocomplete'ują `www.` dla popularnych domen. Cookie z
  # Domain=.bodysync.pl działa cross-subdomain bez różnicy.
}

variable "cors_allow_methods" {
  type = list(string)
  # PUT dodane Sprint 9 dla `/api/profile/targets` (write user-managed
  # kcal/macro targets). Bez PUT browser blokuje preflight zanim request
  # dotrze do Lambdy — owner debugowal "nie udaje sie zapisac" 2026-05-08.
  # DELETE dla `/api/advisor/chat/history` ("Wyczyść rozmowę") — analogicznie.
  default = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
}

variable "cors_allow_headers" {
  type = list(string)
  # `x-csrf-token` (sec audit 2026-05-16 P1-4) — double-submit pattern, frontend
  # wysyła w header dla POST/PUT/DELETE/PATCH. Bez tu CORS preflight blokuje
  # request zanim dotrze do Lambdy.
  default = ["content-type", "authorization", "cookie", "x-csrf-token"]
}

variable "log_retention_days" {
  type    = number
  default = 14
}

# Throttling defaults — security audit 2026-05-09 W3. AWS account quota
# default to 10000 req/s / 5000 burst — nasz throttle jest 200x niżej.
# Adjustować jeśli legitnie potrzebujemy więcej (CW alarm 4XX rate
# jako early warning).
variable "default_throttle_rate" {
  type    = number
  default = 50 # req/s sustained
}

variable "default_throttle_burst" {
  type    = number
  default = 100
}

variable "advisor_chat_throttle_rate" {
  type    = number
  default = 5 # req/s sustained — Anthropic cost guard
}

variable "advisor_chat_throttle_burst" {
  type    = number
  default = 10
}
