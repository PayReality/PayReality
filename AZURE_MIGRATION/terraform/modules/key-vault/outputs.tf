output "id" {
  # Deliberately depends on the RBAC propagation wait, not just the vault
  # resource itself: every other module (postgres, container-apps) reaches
  # this vault only through this output, and every one of them needs the
  # Terraform-operator role to have actually propagated before it can
  # write or reference a secret here. Tying the wait to this output means
  # that dependency exists once, correctly, everywhere this ID is
  # consumed, instead of relying on every caller to remember it.
  value = azurerm_key_vault.this.id

  depends_on = [time_sleep.wait_for_secrets_officer_rbac]
}

output "name" {
  value = azurerm_key_vault.this.name
}

output "uri" {
  description = "Referenced by the Container App configuration (e.g. AZURE_KEY_VAULT_URI) so the application knows which vault to read from at startup."
  value       = azurerm_key_vault.this.vault_uri
}

output "application_secret_ids" {
  description = "Map of secret name -> Key Vault Secret resource ID, for the four Render-originated placeholder secrets. Consumed by modules/container-apps to build each secret's Key-Vault-backed environment variable reference."
  value       = { for name, secret in azurerm_key_vault_secret.application_secrets : name => secret.id }
}
