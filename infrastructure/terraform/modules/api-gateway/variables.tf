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
  type    = list(string)
  default = ["GET", "POST", "OPTIONS"]
}

variable "cors_allow_headers" {
  type    = list(string)
  default = ["content-type", "authorization", "cookie"]
}

variable "log_retention_days" {
  type    = number
  default = 14
}
