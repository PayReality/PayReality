# Production environment values. Apply with:
#   terraform init -backend-config="..." (see versions.tf's comment, key=payreality-prod.tfstate)
#   terraform plan  -var-file=environments/prod.tfvars
#   terraform apply -var-file=environments/prod.tfvars
#
# No secret value belongs in this file, ever -- confirmed by this file
# containing none. This is the file Milestone 3 (Azure Foundation) is
# expected to apply; Milestone 2 authors it, does not run it.

environment = "prod"
owner       = "REPLACE_WITH_ACCOUNTABLE_OWNER"
cost_center = "engineering"

github_repository = "PayReality/PayReality"

# Production gets the durable, always-warm, geo-redundant choices
# staging deliberately skips.
postgres_geo_redundant_backup_enabled = true
storage_replication_type              = "GRS"
container_apps_min_replicas           = 1
