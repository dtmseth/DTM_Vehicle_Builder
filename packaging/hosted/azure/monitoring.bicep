targetScope = 'resourceGroup'
param location string = 'centralus'
param appName string = 'ca-dtm-builder-pilot-cus'
param workspaceName string = 'law-dtm-builder-pilot-cus'
param alertEmail string = 'seth@dtmfleet.com'
@description('Enable after tables are populated and query schemas are checked.')
param enableLogAlerts bool = false
@description('Optional until Cost Management is available on the new trial subscription.')
param enableBudget bool = false
param budgetStartDate string
param budgetEndDate string
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = { name: workspaceName }
resource group 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-dtm-builder-pilot'
  location: 'global'
  properties: {
    groupShortName: 'dtm-pilot'
    enabled: true
    emailReceivers: [{ name: 'pilot-owner', emailAddress: alertEmail, useCommonAlertSchema: true }]
  }
}
var queries = [
  '''
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "__APP_NAME__"
| extend event = parse_json(Log_s)
| where event.event == "http_request"
| summarize requests=count(), errors=countif(toint(event.status) >= 500)
| where errors >= 5 and 100.0 * errors / requests >= 5.0
'''
  '''
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "__APP_NAME__"
| extend event = parse_json(Log_s)
| summarize failures=countif(TimeGenerated > ago(15m) and event.event == "startup_failed"), bytes=sumif(_BilledSize, _IsBillable == "true")
| where failures > 0 or bytes > 100000000
'''
]
resource rules 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for (query, i) in queries: if (enableLogAlerts) {
  name: i == 0 ? 'pilot-request-errors' : 'pilot-startup-or-log-volume'
  location: location
  properties: {
    displayName: i == 0 ? 'Pilot request errors' : 'Pilot startup or log volume'
    enabled: true
    severity: 2
    evaluationFrequency: i == 0 ? 'PT5M' : 'PT15M'
    windowSize: i == 0 ? 'PT5M' : 'P1D'
    scopes: [logs.id]
    criteria: {
      allOf: [{ query: replace(query, '__APP_NAME__', appName), timeAggregation: 'Count', operator: 'GreaterThan', threshold: 0 }]
    }
    actions: { actionGroups: [group.id] }
    autoMitigate: true
    skipQueryValidation: false
  }
}]
resource budget 'Microsoft.Consumption/budgets@2024-08-01' = if (enableBudget) {
  name: 'budget-dtm-builder-pilot'
  properties: {
    category: 'Cost'
    amount: 15
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate, endDate: budgetEndDate }
    notifications: {
      half: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 50, thresholdType: 'Actual', contactEmails: [alertEmail] }
      eighty: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, thresholdType: 'Actual', contactEmails: [alertEmail] }
      full: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Actual', contactEmails: [alertEmail] }
      forecast: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Forecasted', contactEmails: [alertEmail] }
    }
  }
}
