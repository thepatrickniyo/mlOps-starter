variable "project_id" {
  description = "The ID of the Google Cloud project"
  type        = string
}

variable "region" {
  default     = "us-central1"
  type        = string
}

variable "cluster_name" {
  default     = "mlops-prod-cluster"
  type        = string
}