output "cloudfront_distribution_id" { value = aws_cloudfront_distribution.web.id }
output "web_url" { value = "https://${aws_cloudfront_distribution.web.domain_name}" }
output "web_bucket" { value = aws_s3_bucket.web.id }
output "service_alb_dns" { value = aws_lb.service.dns_name }
output "service_ecr_repository" { value = aws_ecr_repository.service.repository_url }
output "ecs_cluster" { value = aws_ecs_cluster.this.name }
output "ecs_service" { value = aws_ecs_service.service.name }
output "task_definition_family" { value = aws_ecs_task_definition.service.family }
output "service_subnet_ids" { value = aws_subnet.app[*].id }
output "service_security_group_id" { value = aws_security_group.service.id }
output "vpc_id" { value = aws_vpc.this.id }
output "vpc_cidr" { value = aws_vpc.this.cidr_block }
output "app_subnet_ids" { value = aws_subnet.app[*].id }
output "data_subnet_ids" { value = aws_subnet.data[*].id }
output "platform_kms_key_arn" { value = aws_kms_key.platform.arn }
output "routing_auth_secret_arn" { value = aws_secretsmanager_secret.routing_token.arn }
output "public_route_table_id" { value = aws_route_table.public.id }
output "database_endpoint" { value = aws_db_instance.service.address }
output "database_master_secret_arn" {
  value     = aws_db_instance.service.master_user_secret[0].secret_arn
  sensitive = true
}
output "application_secret_arns" {
  value = {
    django                   = aws_secretsmanager_secret.django.arn
    kakao_local              = aws_secretsmanager_secret.kakao_local.arn
    routing_auth             = aws_secretsmanager_secret.routing_token.arn
    data_rights_artifact_key = aws_secretsmanager_secret.data_rights_artifact_key.arn
  }
}
output "data_rights_filesystem_id" { value = aws_efs_file_system.data_rights.id }
output "data_rights_schedule_names" {
  value = {
    process = aws_cloudwatch_event_rule.process_data_rights_jobs.name
    purge   = aws_cloudwatch_event_rule.purge_service_data.name
  }
}
output "data_rights_dead_letter_queue_url" { value = aws_sqs_queue.data_rights_dead_letter.url }
output "github_deploy_role_arn" { value = local.create_github_role ? aws_iam_role.github_deploy[0].arn : null }
output "rollback_hint" {
  value = "Register the previous immutable image digest as a new ${aws_ecs_task_definition.service.family} revision, then update ${aws_ecs_service.service.name}; restore web assets from S3 version history."
}
output "postgis_migration_requirement" {
  value = "Service DB geography columns require CREATE EXTENSION IF NOT EXISTS postgis in an approved one-off migration before schema migration. Terraform does not mutate the application schema."
}
