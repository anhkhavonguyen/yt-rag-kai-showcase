# Spec Delta

## ADDED Requirements

### Requirement: Blueprint carries Datadog settings without secrets
The blueprint SHALL list `DD_API_KEY` and `DD_SITE` with no values, so the owner enters them in the hosting dashboard and blueprint syncs never overwrite them. It MUST NOT contain a Datadog API key. A service deployed without `DD_API_KEY` SHALL run with tracing off.

#### Scenario: Blueprint contents
- **WHEN** the blueprint is inspected
- **THEN** `DD_API_KEY` and `DD_SITE` have no values, and no Datadog key appears anywhere in the repository

#### Scenario: Deploying without Datadog
- **GIVEN** the owner leaves `DD_API_KEY` empty
- **WHEN** the service is deployed and a question is asked
- **THEN** the service answers as before and sends nothing to Datadog

### Requirement: Datadog setup is documented
The deployment guide SHALL describe how to create a Datadog account on the free plan without a payment method, choose a Datadog site, create an API key, set `DD_API_KEY` and `DD_SITE` on a new or an existing service, find the traces, and turn text capture or tracing off.

#### Scenario: Owner turns on tracing for the live service
- **WHEN** the owner follows the guide on an already-deployed service
- **THEN** they end with traces from the live service visible in Datadog Agent Observability, without adding a payment method anywhere

#### Scenario: Owner reads the data notice
- **WHEN** the owner reads the Datadog section of the guide
- **THEN** it states the free plan's limits (40K LLM spans a month, 15-day retention), that visitor questions and answers are stored at Datadog unless text capture is off, and that sign-up must stop if Datadog asks for a card
