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

# Redeployed for Milestone 11 (Security Boundary Completion). This
# also carries Milestone 10's decision-security fixes live for the
# first time -- no deployment credentials were available in that
# session, so this is the first deploy since Phase 2B (prod-5041fbc).
# No new migration this round (no schema change). Built and pushed via
# `az acr build`, tagged with the exact source commit as always.
container_image = "acrprprodtq1k.azurecr.io/payreality-api:prod-11f4d3e"
