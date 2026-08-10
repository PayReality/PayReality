# One Container Apps Environment, VNet-integrated into the delegated
# container-apps subnet, wired to the Log Analytics workspace
# (modules/monitoring) so every container's stdout/stderr -- including
# entrypoint.sh's own OPA-then-migration-then-uvicorn startup sequence,
# confirmed directly in AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md -- lands
# somewhere queryable from day one, not bolted on in Milestone 8.

resource "azurerm_container_app_environment" "this" {
  name                       = var.container_apps_environment_name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  infrastructure_subnet_id   = var.container_apps_subnet_id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  tags = merge(var.tags, { Purpose = "Hosts the PayReality API Container App for ${var.environment}" })
}

resource "azurerm_container_app" "api" {
  name                         = var.container_app_name
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single" # one active revision at a time -- no traffic-splitting abstraction this project has no current use for; see README

  identity {
    type         = "UserAssigned"
    identity_ids = [var.container_app_identity_id]
  }

  # Key-Vault-backed secrets: the platform resolves these using the
  # Container App's own managed identity, transparently, before the
  # container starts. The application reads them as ordinary environment
  # variables -- app/config.py needs zero code change, and no secret
  # value ever passes through a Terraform variable, a pipeline log, or
  # this module's own state in plaintext beyond what Terraform's Azure
  # provider already has to read back to manage the resource.
  secret {
    name                = "database-url"
    key_vault_secret_id = var.database_url_secret_id
    identity            = var.container_app_identity_id
  }

  dynamic "secret" {
    for_each = var.application_secret_ids
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = var.container_app_identity_id
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "payreality-api"
      image  = var.container_image
      cpu    = var.cpu
      memory = var.memory

      # Plain, non-secret configuration -- classified exactly per Sprint
      # 1's Environment Standard (AZURE_MIGRATION/../PRODUCT_ROADMAP/SPRINT_1/03_ENVIRONMENT_STANDARD.md).
      env {
        name  = "ENVIRONMENT"
        value = "production" # both staging and prod set this literally, deliberately -- see that document's own reasoning: staging exists to rehearse production's exact boot-time validation, not to run in a permissively different mode
      }
      env {
        name  = "CORS_ORIGIN"
        value = var.cors_origin
      }
      env {
        name  = "INTENT_SIGNATURE_WINDOW_SECONDS"
        value = tostring(var.intent_signature_window_seconds)
      }
      env {
        name  = "ORGANIZATION_NAME"
        value = var.organization_name
      }
      env {
        name  = "OWNER_EMAIL"
        value = var.owner_email
      }

      # Secret-backed configuration.
      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "EVIDENCE_SIGNING_KEY_B64"
        secret_name = "evidence-signing-key-b64"
      }
      env {
        name        = "EVIDENCE_SIGNING_KEY_ID"
        secret_name = "evidence-signing-key-id"
      }
      env {
        name        = "ADMIN_API_KEY"
        secret_name = "admin-api-key"
      }
      env {
        name        = "ANTHROPIC_API_KEY"
        secret_name = "anthropic-api-key"
      }

      # Same endpoints the application already serves today (confirmed
      # directly in MILESTONE_1_DISCOVERY.md) -- zero application change
      # required for either probe.
      liveness_probe {
        transport = "HTTP"
        port      = var.container_port
        path      = "/health"

        initial_delay           = 10
        interval_seconds        = 30
        timeout                 = 5
        failure_count_threshold = 3
      }

      readiness_probe {
        transport = "HTTP"
        port      = var.container_port
        path      = "/health/ready"

        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 3
      }
    }

    http_scale_rule {
      name                = "http-concurrency"
      concurrent_requests = var.http_scale_concurrent_requests
    }
  }

  ingress {
    external_enabled           = true
    target_port                = var.container_port
    allow_insecure_connections = false # HTTPS only -- Container Apps' managed TLS certificate on the default *.azurecontainerapps.io domain; a custom domain binding is Milestone 9's concern, not this one

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  tags = merge(var.tags, { Purpose = "The PayReality API -- Azure replacement for Render's payreality-api service" })
}
