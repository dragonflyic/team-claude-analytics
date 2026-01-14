# team-claude-analytics

This application collects each individual developer's Claude Code chat logs and
centralizes them for the end goal of creating insights into how the team can more
effectively use agentic coding to ship more. 

# Tech Stack
- Infrastructure managed via terraform
- All backend logic written in Python, managed by poetry

# Key Locations
- `collector/` contains a service that runs on each developer's machines that sends that
  machine's Claude chat logs to a centralized RDS instance
- `terrfaorm/` contains the Terraform code that provisions that centralized RDS instance