# Staging environment values. Apply with:
#   terraform init -backend-config="..." (see versions.tf's comment, key=payreality-staging.tfstate)
#   terraform plan  -var-file=environments/staging.tfvars
#   terraform apply -var-file=environments/staging.tfvars
#
# No secret value belongs in this file, ever -- confirmed by this file
# containing none. owner is a placeholder; replace with a real
# accountable identifier before the first real apply, per
# docs/TAGGING_STRATEGY.md.

environment = "staging"
owner       = "REPLACE_WITH_ACCOUNTABLE_OWNER"
cost_center = "engineering"

github_repository = "PayReality/PayReality"

# Staging is disposable and re-seedable (Sprint 1's own Infrastructure
# Blueprint) -- cheaper, non-geo-redundant choices throughout.
postgres_geo_redundant_backup_enabled = false
storage_replication_type              = "LRS"
container_apps_min_replicas           = 0 # scale-to-zero is acceptable here; staging is not customer-facing
