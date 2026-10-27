# MCP server: bodysync health data in Claude conversations

Exposes bodysync data as a custom connector in Claude. **Read-only.**
Design decisions and their rationale: [ADR-010](../../../../docs/adr/ADR-010-mcp-server.md).

## Connecting

1. In Claude: **Customize → Connectors → `+` → Add custom connector**
2. **Name:** anything, e.g. `bodysync`
3. **Remote MCP server URL:** `https://api.bodysync.pl/mcp`
4. **Advanced settings:** leave both OAuth fields **empty**. Claude registers
   itself through DCR
5. Click **Add**, then connect the connector
6. On the consent screen, check that the account email is correct and click
   **Zezwalam** (Allow)

If you don't have an active session on `bodysync.pl`, `/authorize` first
redirects you to Google login and then back here. Only accounts on the
2-email allowlist get access, the same allowlist the app uses.

## Tools

| Tool | Returns | Default range |
|---|---|---|
| `get_body_composition` | weight, BMI, body fat %, lean mass, circumferences | 90 days |
| `get_daily_health_metrics` | kcal in/active/basal + balance, macros, steps, sleep stages, heart rate | today |
| `get_health_trends` | one metric over time + summary (first/last/change/min/max/avg) | 30 days |
| `get_workouts` | exercises, sets, weights, RIR, grouped into sessions | 30 days |

Above **60 days**, `get_health_trends` switches to weekly averages, because
half a year of daily values would flood the model's context. Hard window
limit: 730 days.

### What's not here

- **Strava activities**: the separate Strava connector covers them better
- **HRV and Body Battery**: Garmin doesn't send them to Apple Health, so this
  data doesn't exist in the database. Adding it would need a Garmin Connect
  integration
- **Anything that writes**: the server has no mutating endpoints, and the
  Lambda's IAM role has no `PutItem` on `USER#*`

The server instructions (`protocol.INSTRUCTIONS`) tell the model this
explicitly, so it doesn't go looking for this data or treat a missing result
as zero.

## Architecture

One Lambda (`bodysync-mcp`, 1024 MB) serves seven routes:

```
POST /mcp                                     JSON-RPC 2.0, requires Bearer
GET  /.well-known/oauth-protected-resource    RFC 9728
GET  /.well-known/oauth-authorization-server  RFC 8414
POST /mcp/register                            RFC 7591 DCR
GET  /mcp/authorize                           consent screen
POST /mcp/authorize                           code issuance
POST /mcp/token                               code exchange / refresh
```

Measured in production: **881 ms cold start, 2 ms warm**, 13.97 MB bundle.

The protocol is hand-written, without FastMCP. Rationale and measurements are
in ADR-010. Spec conformance is checked by `tests/handlers/mcp/test_conformance.py`,
which validates responses against the official SDK models. **The `mcp`
package is a dev-only dependency.** Two guard tests make sure it never ends up
in the Lambda bundle together with its `pydantic`.

## Security

- PKCE **S256** required, `plain` rejected
- `redirect_uri` must exactly match a registered one, and its host must be on
  the allowlist (`claude.ai`, `claude.com` over https; loopback for Claude
  Code). DCR is open by definition, so the allowlist is what guarantees the
  code never reaches a third party
- Authorization code is single-use (atomic delete), 60 s TTL, bound to
  `client_id` + `redirect_uri` + `code_challenge`
- Refresh tokens are rotated on every use and stored as SHA-256
- Access tokens are signed with a **different** secret than the session
  cookie. If they shared a key, a read-only token would pass as an app
  session and grant full write access

## Secret

`/bodysync/mcp/token_signing_secret` (SecureString, at least 32 bytes).
Terraform creates a placeholder; the owner sets the value **after** a
successful apply:

```sh
aws ssm put-parameter --name /bodysync/mcp/token_signing_secret \
  --value "$(openssl rand -base64 48)" --type SecureString --overwrite --region eu-west-1
```

Order matters: setting the value **before** apply fails with
`ParameterAlreadyExists` and breaks the whole apply (see ADR-010, pitfalls
section).

Rotating the secret invalidates every issued token, so the connector has to
be reconnected.

## Troubleshooting

```sh
# Is discovery alive
curl -s https://api.bodysync.pl/.well-known/oauth-protected-resource | jq

# Is the 401 handshake correct
curl -si -X POST https://api.bodysync.pl/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -i www-authenticate

# Does form parsing work (base64 regression from PR #224)
curl -s -X POST https://api.bodysync.pl/mcp/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=refresh_token&refresh_token=testowy'
# expected: invalid_grant. `grant_type: None` = the body doesn't reach the parser
```

Logs: `/aws/lambda/bodysync-mcp`. Events to search for: `mcp_client_registered`,
`mcp_authorize_granted`, `mcp_token_issued`, `mcp_tool_ok`, `mcp_oauth_error`.
