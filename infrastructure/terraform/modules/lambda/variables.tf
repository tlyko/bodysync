variable "function_name" {
  type        = string
  description = "Bare function name (e.g. \"google-auth\"). Module prefixes with project name."
}

variable "project" {
  type        = string
  description = "Project tag/prefix (typically \"bodysync\")."
}

variable "source_zip" {
  type        = string
  description = "Absolute path to the deployment package zip (apps/api/dist/{fn}.zip)."
}

variable "handler" {
  type        = string
  default     = "handler.handler"
  description = "Module-qualified entrypoint (e.g. \"handler.handler\" inside the zip)."
}

variable "memory_size" {
  type    = number
  default = 512
}

variable "timeout" {
  type    = number
  default = 10
}

variable "environment" {
  type        = map(string)
  default     = {}
  description = "Lambda env vars. TABLE_NAME etc."
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "extra_iam_statements" {
  type        = any
  default     = []
  description = "Extra IAM policy statements attached to the Lambda role (DDB / SSM / S3 access). Mixed-type list — Resource may be string or list of strings."
}
