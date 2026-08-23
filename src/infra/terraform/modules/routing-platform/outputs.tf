output "routing_url" { value = "https://${var.routing_private_hostname}" }
output "routing_ecr_repository" { value = aws_ecr_repository.routing.repository_url }
output "routing_ecs_service" { value = aws_ecs_service.routing.name }
output "routing_task_definition_family" { value = aws_ecs_task_definition.routing.family }
output "routing_database_bootstrap_task_definition_arn" { value = aws_ecs_task_definition.database_bootstrap.arn }
output "routing_migration_task_definition_arn" { value = aws_ecs_task_definition.migration.arn }
output "routing_database_endpoint" { value = aws_db_instance.routing.address }
output "routing_database_master_secret_arn" {
  value     = aws_db_instance.routing.master_user_secret[0].secret_arn
  sensitive = true
}
output "routing_application_secret_arns" {
  value = merge(
    {
      django                      = aws_secretsmanager_secret.django.arn
      migration_django            = aws_secretsmanager_secret.migration_django.arn
      migration_jwt               = aws_secretsmanager_secret.migration_jwt.arn
      database_password           = aws_secretsmanager_secret.database_password.arn
      database_migration_password = aws_secretsmanager_secret.database_migration_password.arn
      service_jwt                 = var.shared_jwt_secret_arn
    },
    { for name, secret in aws_secretsmanager_secret.provider : name => secret.arn }
  )
}
output "routing_security_group_id" { value = aws_security_group.task.id }
output "routing_subnet_ids" { value = aws_subnet.routing[*].id }
output "github_deploy_role_arn" { value = local.create_github_role ? aws_iam_role.github_deploy[0].arn : null }
output "github_database_bootstrap_role_arn" {
  value = local.create_github_database_role ? aws_iam_role.github_database_bootstrap[0].arn : null
}
output "rollback_hint" {
  value = "Set desired count to zero or register the previous immutable image digest as a new ${aws_ecs_task_definition.routing.family} revision; keep Provider evidence and factory fail-closed during rollback."
}
