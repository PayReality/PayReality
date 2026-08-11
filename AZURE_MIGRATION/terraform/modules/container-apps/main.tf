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

  # Milestone 3 finding: `infrastructure_resource_group_name` is Optional
  # but NOT Computed in provider ~3.117 -- leaving it unset means Azure
  # auto-generates one on create (e.g. "ME_<name>_<resource-group>_
  # <location>"), but every later `terraform plan` then reads that real
  # value back, compares it to this resource's unset config, and treats
  # the difference as "-> null", which is ForceNew: left alone, this
  # would destroy and recreate an already-successfully-running
  # environment on every apply for no operational reason. Explicitly
  # setting the value instead requires also configuring `workload_profile`
  # blocks (a provider-enforced pairing this Consumption-only environment
  # has no other reason to adopt), so
  # `ignore_changes` is the correct fix here: it lets Azure's
  # auto-generated value stand, permanently, without Terraform proposing
  # to tear it down to "fix" a value it was never asked to manage. See
  # MILESTONE_3_DEPLOYMENT_REPORT.md.
  lifecycle {
    ignore_changes = [infrastructure_resource_group_name]
  }
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

  registry {
    server   = var.container_registry_login_server
    identity = var.container_app_identity_id
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
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = var.app_insights_connection_string
      }

      # Authority Intelligence Program, Phase 1: endpoints and names
      # only, never credentials -- Managed Identity authenticates to all
      # three, so none of this belongs in Key Vault (app/config.py's own
      # comment makes the same point). Empty strings (the default when
      # modules/ai-foundry / modules/ai-search haven't been applied to
      # this environment) mean Authority Builder runs exactly as it did
      # before this program existed.
      #
      # AZURE_CLIENT_ID: confirmed live-necessary, not a preemptive
      # addition -- the first staging deploy of this program's code
      # (the first application code ever calling DefaultAzureCredential()
      # itself; Key Vault secret resolution above is done by the
      # platform, not app code) failed at boot with "Unable to load the
      # proper Managed Identity" / invalid_scope. This Container App has
      # only a user-assigned identity (identity_ids, above); unlike a
      # system-assigned identity, DefaultAzureCredential can't resolve
      # which identity to use without an explicit client ID. Setting
      # AZURE_CLIENT_ID is azure-identity's own documented, standard,
      # code-free fix for exactly this -- ManagedIdentityCredential reads
      # it automatically, no application code change required.
      env {
        name  = "AZURE_CLIENT_ID"
        value = var.container_app_identity_client_id
      }
      env {
        name  = "AZURE_AI_FOUNDRY_ENDPOINT"
        value = var.azure_ai_foundry_endpoint
      }
      env {
        name  = "AZURE_AI_FOUNDRY_DEPLOYMENT_NAME"
        value = var.azure_ai_foundry_deployment_name
      }
      env {
        name  = "AZURE_AI_SEARCH_ENDPOINT"
        value = var.azure_ai_search_endpoint
      }
      env {
        name  = "AZURE_AI_SEARCH_INDEX_NAME"
        value = var.azure_ai_search_index_name
      }
      env {
        name  = "AZURE_STORAGE_ACCOUNT_URL"
        value = var.azure_storage_account_url
      }
      env {
        name  = "AZURE_STORAGE_CONTAINER_NAME"
        value = var.azure_storage_container_name
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

  # Same class of finding as azurerm_container_app_environment.this above:
  # `workload_profile_name` is Optional but NOT Computed in provider
  # ~3.117. Azure auto-assigns "Consumption" on create; this config never
  # asked for a specific profile, so every later plan proposes nulling it
  # back out. `ignore_changes` again, for the same reason.
  lifecycle {
    ignore_changes = [workload_profile_name]
  }
}
