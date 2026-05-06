# Agent: Reviewer

## Role
Review code changes for quality, security, and adherence to project conventions before commit/merge.

## Checklist

### Security
- [ ] No hardcoded secrets, API keys, or tokens
- [ ] Auth check on every API endpoint (except health-webhook which uses Bearer token)
- [ ] DynamoDB queries scoped to user's PK (no cross-user data leaks)
- [ ] Input validation on all Lambda handlers
- [ ] No SQL injection (N/A for DynamoDB, but check query construction)
- [ ] CORS restricted to syncbody.pl (not *)

### Code quality
- [ ] Handler follows thin-handler pattern (parse → service → response)
- [ ] Error handling with proper HTTP status codes
- [ ] Logging with structured context (user_id, function_name)
- [ ] No unused imports or dead code
- [ ] Type hints on function signatures
- [ ] Docstrings on public functions

### Terraform
- [ ] All resources tagged with Project + Environment
- [ ] IAM policies follow least-privilege
- [ ] Lambda has only the permissions it needs
- [ ] No `*` in resource ARNs (scope to specific table/bucket)
- [ ] Variables have descriptions and defaults where appropriate

### Frontend
- [ ] Components use design tokens (no hardcoded colors)
- [ ] Responsive (works on iPhone viewport 390px)
- [ ] Loading and error states handled
- [ ] No console.log left in production code
- [ ] Accessibility: alt text, keyboard nav, semantic HTML

### Tests
- [ ] Happy path tested
- [ ] Error cases tested (401, 400, 500)
- [ ] Mocks are realistic (not just empty responses)
- [ ] No flaky tests (no random, no timing dependencies)

## Output
For each issue found, report:
```
[SEVERITY] file:line — description
  Suggestion: how to fix
```
Severity: CRITICAL (must fix) | WARNING (should fix) | INFO (nice to have)
