variable "targets" {
  description = "Map of short resource key (e.g. \"postgres\", \"key-vault\") -> full Azure resource ID to attach a diagnostic setting to. One entry per resource this project wants to monitor."
  type        = map(string)
}

variable "log_analytics_workspace_id" {
  type = string
}
