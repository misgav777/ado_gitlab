output "ado_migration_instance_id" {
  description = "The ID of the ADO migration instance"
  value       = aws_instance.ado_migration_instance.id
}