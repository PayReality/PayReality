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
owner       = "payreality.ceo@gmail.com"
cost_center = "engineering"

github_repository = "PayReality/PayReality"

# Milestone 3: the real application image, built and pushed via
# `az acr build` from server/Dockerfile (embedded OPA included) and
# tagged with the exact source commit it was built from -- see
# MILESTONE_3_DEPLOYMENT_REPORT.md for the full build record (registry,
# tag, digest, auth method).
container_image = "acrprstagingadzg.azurecr.io/payreality-api:staging-371906d"

# Milestone 5: closes the "zero alert rules" gap from MILESTONE_4_RISK_REGISTER.md.
# Same address used throughout this program's tagging (owner, above).
alert_notification_email = "payreality.ceo@gmail.com"

# Staging is disposable and re-seedable (Sprint 1's own Infrastructure
# Blueprint) -- cheaper, non-geo-redundant choices throughout.
postgres_geo_redundant_backup_enabled = false
storage_replication_type              = "LRS"
container_apps_min_replicas           = 0 # scale-to-zero is acceptable here; staging is not customer-facing
