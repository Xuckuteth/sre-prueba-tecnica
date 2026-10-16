variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "Región de AWS para el entorno"
}

variable "environment" {
  type        = string
  default     = "local"
  description = "Entorno de despliegue"
}

variable "bucket_name" {
  type        = string
  default     = "sre-local-bucket-ei908k"
  description = "Nombre del bucket S3 de persistencia"
}