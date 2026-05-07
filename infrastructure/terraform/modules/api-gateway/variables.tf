variable "project" {
  type = string
}

variable "cors_allow_origins" {
  type    = list(string)
  default = ["https://bodysync.pl"]
  # NIGDY localhost w prod (sec audit H1) — z `allow_credentials=true` to
  # vector data exfil dla XHR/fetch z dowolnej maszyny w cudzej sieci. Dev
  # frontend musi używać Vite proxy (`/api → https://api.bodysync.pl`) albo
  # osobnego staging API GW z osobnym CORS allowlist.
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
