output "dynamodb_reg_table_arn" {
  value = aws_dynamodb_table.game_ids_table.arn
}

output "dynamodb_reg_table_name" {
  value = aws_dynamodb_table.game_ids_table.name
}
