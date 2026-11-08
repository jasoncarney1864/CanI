// Subscription-scoped module: a Consumption budget filtered to one resource group.
// Budgets can only be created at subscription (or management group) scope, so main.bicep
// calls this with `scope: subscription()`. The filter keeps the number honest when other
// workloads share the subscription (the Mercor dev VM lives next door).
//
// A budget never stops spend; it only emails. The emails must go to a mailbox that is read —
// the previous deployment's went to ops@canido.co and the $500 month passed without anyone
// seeing them.

targetScope = 'subscription'

param budgetName string
param amountUsd int
@description('First day of a month, yyyy-MM-01. Azure rejects a start date in the past month once created.')
param startDate string
param resourceGroupName string
param contactEmails array
param actionGroupId string

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: amountUsd
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
      // Ten years out; Azure requires an end date and this is "indefinite" in practice.
      endDate: dateTimeAdd(startDate, 'P10Y', 'yyyy-MM-dd')
    }
    filter: {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: [resourceGroupName]
      }
    }
    notifications: {
      actual50: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: contactEmails
        contactGroups: [actionGroupId]
      }
      actual80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: contactEmails
        contactGroups: [actionGroupId]
      }
      actual100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: contactEmails
        contactGroups: [actionGroupId]
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: contactEmails
        contactGroups: [actionGroupId]
      }
    }
  }
}
