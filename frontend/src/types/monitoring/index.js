export const MonitoringSourceType = {
  GENERIC_WEBHOOK: 'generic_webhook',
  PROMETHEUS_ALERTMANAGER: 'prometheus_alertmanager',
  GRAFANA: 'grafana',
  ZABBIX: 'zabbix',
  PRTG: 'prtg',
  NAGIOS: 'nagios',
  AZURE_MONITOR: 'azure_monitor',
  AWS_CLOUDWATCH: 'aws_cloudwatch',
  VMWARE_VCENTER: 'vmware_vcenter',
  WINDOWS_EVENT: 'windows_event',
  LINUX_AGENT: 'linux_agent',
  MANUAL: 'manual',
  OTHER: 'other',
};

export const MonitoringSourceStatus = {
  ACTIVE: 'active',
  DISABLED: 'disabled',
  DEGRADED: 'degraded',
  ERROR: 'error',
  RETIRED: 'retired',
};

export const MonitoringSourceHealth = {
  HEALTHY: 'healthy',
  DEGRADED: 'degraded',
  UNHEALTHY: 'unhealthy',
  UNKNOWN: 'unknown',
};

export const AlertSeverity = {
  INFO: 'info',
  WARNING: 'warning',
  MINOR: 'minor',
  MAJOR: 'major',
  CRITICAL: 'critical',
};

export const AlertStatus = {
  NEW: 'new',
  OPEN: 'open',
  ACKNOWLEDGED: 'acknowledged',
  SUPPRESSED: 'suppressed',
  RECOVERED: 'recovered',
  RESOLVED: 'resolved',
  CLOSED: 'closed',
  FLAPPING: 'flapping',
};

export const EventState = {
  FIRING: 'firing',
  RECOVERED: 'recovered',
  INFORMATIONAL: 'informational',
  UNKNOWN: 'unknown',
};

export const AutomationPolicySourceFilter = {
  ALL: 'all',
  SELECTIVE: 'selective',
};

export const AutomationPolicyMinSeverity = {
  INFO: 'info',
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
  CRITICAL: 'critical',
};

export const AutomationPolicyEligibleState = {
  NEW: 'new',
  OPEN: 'open',
  ACKNOWLEDGED: 'acknowledged',
  RECOVERED: 'recovered',
  SUPPRESSED: 'suppressed',
};

export const AlertHistoryEventType = {
  CREATED: 'created',
  EVENT_CORRELATED: 'event_correlated',
  DUPLICATE_RECEIVED: 'duplicate_received',
  SEVERITY_CHANGED: 'severity_changed',
  ACKNOWLEDGED: 'acknowledged',
  ASSIGNED: 'assigned',
  SUPPRESSED: 'suppressed',
  UNSUPPRESSED: 'unsuppressed',
  TICKET_CREATED: 'ticket_created',
  TICKET_UPDATED: 'ticket_updated',
  RECOVERED: 'recovered',
  REOPENED: 'reopened',
  FLAPPING_DETECTED: 'flapping_detected',
  FLAPPING_CLEARED: 'flapping_cleared',
  RESOLVED: 'resolved',
  CLOSED: 'closed',
  AUTOMATION_FAILED: 'automation_failed',
};