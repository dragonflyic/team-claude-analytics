# Public ECR repository for the collector image
# Note: Public ECR must be created in us-east-1 (which is our default region)

resource "aws_ecrpublic_repository" "collector" {
  repository_name = "claude-log-collector"

  catalog_data {
    about_text        = "Claude Code log collector - streams chat logs to PostgreSQL"
    architectures     = ["x86-64", "ARM 64"]
    operating_systems = ["Linux"]
    description       = "Collects Claude Code chat logs from developer machines and streams them to a shared PostgreSQL database"
    usage_text        = <<-EOF
      ## Usage

      ```bash
      docker pull public.ecr.aws/<alias>/claude-log-collector:latest

      docker run -d \
        -e DB_HOST=your-rds-endpoint \
        -e DB_PASSWORD=your-password \
        -v ~/.claude/projects:/claude-projects:ro \
        public.ecr.aws/<alias>/claude-log-collector:latest
      ```
    EOF
  }

  tags = {
    Name        = "claude-log-collector"
    Environment = var.environment
  }
}
