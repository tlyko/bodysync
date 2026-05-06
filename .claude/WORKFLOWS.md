# SyncBody — Claude Code Workflows

## Quick reference commands

### Start a new feature
```
/plan [feature name]
```
Reads PROJECT_PLAN.md, creates implementation steps in docs/TODO.md using the planner agent.

### Implement a step
```
/implement [step number from TODO.md]
```
Reads the step, relevant skill, writes code, tests, and marks done. Uses implementer agent.

### Review changes
```
/review
```
Runs reviewer agent checklist on all uncommitted changes. Reports CRITICAL/WARNING/INFO issues.

### Run all tests
```
/test
```
Runs pytest for Lambda + vitest for frontend. Reports failures with context.

### Deploy
```
/deploy [infra|frontend|lambda|all]
```
Runs deployer agent: validate → plan → apply → verify.

## Typical session flow

### Starting a new phase
1. `Plan phase 1 — infrastructure setup`
2. Review the generated TODO.md
3. `Implement step 1 — terraform base modules`
4. `Implement step 2 — DynamoDB table`
5. `Review changes`
6. `Deploy infra`
7. `Test deployed endpoints`

### Adding a feature
1. `Plan: add training-plan-sync Lambda`
2. `Implement step 1`
3. `Test training-plan-sync`
4. `Review`
5. `Deploy lambda`

### Debugging
1. `Check CloudWatch logs for health-webhook Lambda`
2. `Send test webhook payload to /api/health/webhook`
3. `Query DynamoDB for USER#tomek HEALTH# records`

## Tips
- Always read the relevant skill before implementing
- Run tests after every implementation step
- Commit frequently with conventional commit messages
- Use `terraform plan` before `terraform apply` — always
- Check PROJECT_PLAN.md for architectural decisions before making changes
