variable "project" {
  type = string
}

variable "cors_allow_origins" {
  type    = list(string)
  default = ["https://bodysync.pl", "http://localhost:5173"]
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
