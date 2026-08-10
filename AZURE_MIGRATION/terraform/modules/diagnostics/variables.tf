variable "targets" {
  description = "Map of short resource key (e.g. \"postgres\", \"key-vault\") -> full Azure resource ID to attach a diagnostic setting to. One entry per resource this project wants to monitor."
  type        = map(string)
}

variable "log_analytics_workspace_id" {
  type = string
}

variable "metric_categories" {
  description = "Per-target override of metric categories, keyed by the same key used in `targets`. Defaults to [\"AllMetrics\"] for any target not listed here. Milestone 3 finding: unlike every other resource type in this project, Blob Storage's diagnostic-settings API does not accept \"AllMetrics\" as a stable value -- it silently translates it server-side into the concrete categories it actually exposes (\"Capacity\", \"Transaction\"), so a config left at \"AllMetrics\" and a real state that reads back as those two categories never converge, producing a never-clean `terraform plan` on every run. Declaring the concrete list explicitly for that one target is the fix; every other target keeps using the generic default, unaffected."
  type        = map(list(string))
  default     = {}
}
