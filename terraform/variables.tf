variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_credentials_file" {
  type    = list(string)
  default = ["$HOME/.aws/credentials"]
}

variable "aws_profile" {
  type    = string
  default = "default"
}

variable "tags" {
  type = map(string)
  default = {
    Name    = "QuizPleaseReg"
    Project = "QuizPlease"
  }
}

variable "team_name" {
  type = string
}

variable "cpt_email" {
  type = string
}

variable "cpt_name" {
  type = string
}

variable "cpt_phone" {
  type = string
}

variable "team_size" {
  type    = number
  default = 9
}

variable "bot_token" {
  type = string
}

variable "group_id" {
  type = string
}

variable "resource_name" {
  description = "The prefix for all resource names"
  type        = string
  default     = "QuizPleaseReg"
}