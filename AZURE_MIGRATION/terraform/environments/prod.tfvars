# Production environment values. Apply with:
#   terraform init -backend-config="..." (see versions.tf's comment, key=payreality-prod.tfstate)
#   terraform plan  -var-file=environments/prod.tfvars
#   terraform apply -var-file=environments/prod.tfvars
#
# No secret value belongs in this file, ever -- confirmed by this file
# containing none. This is the file Milestone 3 (Azure Foundation) is
# expected to apply; Milestone 2 authors it, does not run it.

environment = "prod"
owner       = "payreality.ceo@gmail.com"
cost_center = "engineering"

github_repository = "PayReality/PayReality"

# Production gets the durable, always-warm, geo-redundant choices
# staging deliberately skips.
postgres_geo_redundant_backup_enabled = true
storage_replication_type              = "GRS"
container_apps_min_replicas           = 1

# Milestone 5: see staging.tfvars's identical comment -- every environment
# must consciously set this, no default exists.
alert_notification_email = "payreality.ceo@gmail.com"

# Milestone 5 (Azure Production Cutover): redeployed to current HEAD,
# built and pushed via `az acr build` from server/Dockerfile (embedded
# OPA included) and tagged with the exact source commit it was built
# from; see MILESTONE_5_AZURE_PRODUCTION_CUTOVER_SUMMARY.md. Carries
# every fix through Milestone 3 (Enterprise Surface Isolation), which
# commit prod-5e1c3ad (Production Bootstrap Phase 4) predated entirely.
container_image = "acrprprodtq1k.azurecr.io/payreality-api:prod-cb8c9b3"
