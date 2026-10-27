// Monthly cost budget at resource group scope: 50/80/100 percent of actual and 100 percent of forecast.
targetScope = 'resourceGroup'

@description('Budget name.')
param name string = 'nsdemo-monthly'

@description('Monthly budget amount in the billing currency.')
@minValue(1)
param amount int

@description('First day of the budget period, yyyy-MM-01 (must be the first of a month).')
param startDate string

@description('Email addresses notified when a threshold is crossed.')
param contactEmails array

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: name
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    notifications: {
      actual50: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: contactEmails
      }
      actual80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: contactEmails
      }
      actual100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: contactEmails
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: contactEmails
      }
    }
  }
}

@description('Resource id of the budget.')
output id string = budget.id
