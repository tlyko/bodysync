# Agent: Deployer

## Role
Handle deployment workflow: terraform apply, frontend build, Lambda packaging, and post-deploy verification.

## Deployment flow

### 1. Pre-deploy checks
```bash
# Terraform validation
cd terraform && terraform validate && terraform plan -out=plan.tfplan

# Lambda tests pass
cd terraform/lambda-src && pytest -v

# Frontend builds
cd frontend && npm run build

# No secrets in code
grep -rn "AKIA\|sk-ant\|AIza" terraform/ frontend/ --include="*.py" --include="*.ts" --include="*.tf"
```

### 2. Infrastructure deploy
```bash
cd terraform
terraform apply plan.tfplan
# Capture outputs
terraform output -json > ../docs/infra-outputs.json
```

### 3. Lambda deploy
```bash
# Package each function
for func in google-auth health-webhook training-plan-sync ai-advisor-daily ai-advisor-weekly ai-chat recipe-search api-read; do
    cd lambda-src/$func
    pip install -r requirements.txt -t package/
    cp handler.py package/
    cp -r ../shared package/
    cd package && zip -r ../../$func.zip . && cd ..
    rm -rf package
    cd ../..
done

# Upload via Terraform (Lambda source_code_hash triggers update)
terraform apply -auto-approve
```

### 4. Frontend deploy
```bash
cd frontend
npm run build
# Cloudflare Pages deploys automatically from GitHub push
git add -A && git commit -m "deploy: frontend build" && git push
```

### 5. Post-deploy verification
```bash
API_URL="https://api.syncbody.pl"

# Health check
curl -s $API_URL/api/status | jq .

# Auth flow
curl -s -X POST $API_URL/api/auth/google -H "Content-Type: application/json" -d '{"id_token": "test"}' | jq .status

# Webhook accepts data
curl -s -X POST $API_URL/api/health/webhook \
  -H "Authorization: Bearer $WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"data": {"metrics": [{"name": "step_count", "data": [{"qty": 100}]}]}}' | jq .

# Frontend loads
curl -s -o /dev/null -w "%{http_code}" https://syncbody.pl
```

## Rollback
```bash
# Terraform: revert to previous state
terraform apply -target=module.lambda -var="lambda_version=previous"

# Frontend: Cloudflare Pages has automatic rollback in dashboard
# Or: git revert HEAD && git push
```

## Environments
- **dev**: terraform workspace "dev", API at api-dev.syncbody.pl (optional)
- **prod**: terraform workspace "default", API at api.syncbody.pl
- For 2 users, single prod is fine. Add dev later if needed.
