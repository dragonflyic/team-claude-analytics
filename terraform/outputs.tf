output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "rds_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.main.endpoint
}

output "rds_hostname" {
  description = "RDS instance hostname"
  value       = aws_db_instance.main.address
}

output "rds_port" {
  description = "RDS instance port"
  value       = aws_db_instance.main.port
}

output "rds_database_name" {
  description = "Database name"
  value       = aws_db_instance.main.db_name
}

output "rds_username" {
  description = "Database master username"
  value       = aws_db_instance.main.username
  sensitive   = true
}

output "connection_string" {
  description = "PostgreSQL connection string (without password)"
  value       = "postgresql://${aws_db_instance.main.username}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/${aws_db_instance.main.db_name}"
  sensitive   = true
}

output "ecr_repository_url" {
  description = "Public ECR repository URL"
  value       = aws_ecrpublic_repository.collector.repository_uri
}

output "ecr_registry_id" {
  description = "Public ECR registry ID"
  value       = aws_ecrpublic_repository.collector.registry_id
}

# Dashboard outputs
output "dashboard_url" {
  description = "Dashboard URL (ALB DNS name)"
  value       = "http://${aws_lb.dashboard.dns_name}"
}

output "dashboard_ecr_repository_url" {
  description = "Dashboard ECR repository URL"
  value       = aws_ecr_repository.dashboard.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.dashboard.name
}
