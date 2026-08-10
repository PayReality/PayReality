output "diagnostic_setting_ids" {
  value = { for key, setting in azurerm_monitor_diagnostic_setting.this : key => setting.id }
}
