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
# Confirmed live 2026-08-19 via a failed azure-backend-deploy.yml run's
# own AADSTS700213 error log ("subject claim - repo:PayReality@.../
# PayReality@...") -- GitHub is now issuing this repo's OIDC tokens in
# the immutable-subject-claim format, so github_repository above no
# longer matches what actually gets presented.
github_repository_immutable = "PayReality@282130118/PayReality@1272545093"

# Production gets the durable, always-warm, geo-redundant choices
# staging deliberately skips.
postgres_geo_redundant_backup_enabled = true
storage_replication_type              = "GRS"
container_apps_min_replicas           = 1

# Milestone 5: see staging.tfvars's identical comment -- every environment
# must consciously set this, no default exists.
alert_notification_email = "payreality.ceo@gmail.com"

# As of the backend CD pipeline (.github/workflows/azure-backend-deploy.yml,
# added 2026-08-19), this value no longer drives what's actually
# running in prod -- every push to main deploys a new image directly
# via `az containerapp update`, bypassing Terraform entirely. Kept in
# sync here manually so `terraform plan` doesn't report false drift on
# every run; if it ever falls behind, that's a plan noting a
# container_image change and nothing else, safe to either apply (which
# only resets this one field, matching whatever the last real CD
# deploy already put there) or refresh this line to match instead.
container_image = "acrprprodtq1k.azurecr.io/payreality-api:prod-0f0d236098d318ad324de51786745606fd2157d4"
