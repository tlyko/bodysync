variable "aws_region" {
  description = "AWS region for state backend resources."
  type        = string
  default     = "eu-west-1"
}

variable "github_owner" {
  description = "GitHub user/org that owns the repo allowed to assume the CI role."
  type        = string
  default     = "tlyko"
}

variable "github_repo" {
  description = "GitHub repository name allowed to assume the CI role."
  type        = string
  default     = "bodysync"
}

variable "project" {
  description = "Project tag value applied to all bootstrap resources."
  type        = string
  default     = "syncbody"
}
