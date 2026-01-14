variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "claude-analytics"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "claude_logs"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "claude_admin"
}

variable "db_password" {
  description = "Database master password"
  type        = string
  sensitive   = true
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to connect to RDS"
  type        = list(string)
  default     = ["0.0.0.0/0"]  # Restrict in production
}

variable "multi_az" {
  description = "Enable Multi-AZ deployment"
  type        = bool
  default     = false
}

# Dashboard / ECS variables
# Note: github_token is stored in AWS Parameter Store, not Terraform
# Create it manually at: /${project_name}/github-token

variable "github_repos" {
  description = "Comma-separated list of GitHub repos to sync (owner/repo format)"
  type        = string
  default     = ""
}

variable "sync_interval_minutes" {
  description = "How often to sync GitHub data (minutes)"
  type        = number
  default     = 15
}

variable "dashboard_cpu" {
  description = "Fargate CPU units for dashboard (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 256
}

variable "dashboard_memory" {
  description = "Fargate memory (MB) for dashboard"
  type        = number
  default     = 512
}

variable "dashboard_desired_count" {
  description = "Number of dashboard instances to run"
  type        = number
  default     = 1
}
