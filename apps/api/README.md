# `@bodysync/api`

Python 3.12 Lambda backend for bodysync.pl (per [ADR-002 lambda packaging](../../docs/adr/ADR-002-lambda-packaging.md)).

## Layout

```
apps/api/
├── pyproject.toml          # dev deps (pytest, moto, ruff, mypy)
├── shared/                 # imported by every handler
│   ├── ssm.py             # get_param with a module-level cache
│   ├── dynamo.py          # get_item / put_item / query_by_pk
│   ├── auth.py            # verify_jwt, mint_jwt
│   └── logging.py         # structured logger
├── handlers/
│   └── google_auth/
│       ├── handler.py      # def handler(event, context)
│       ├── schemas.py      # Pydantic input/output
│       ├── service.py      # logic kept separate from event/context
│       └── requirements.txt # prod deps for this Lambda only
├── tests/
│   ├── conftest.py         # fixtures: dynamodb_table (moto), ssm_params
│   └── handlers/google_auth/test_handler.py
├── scripts/
│   └── build.py            # produces dist/{fn}.zip per handler
└── dist/                   # gitignored, Terraform input
```

## Local setup

Requires [uv](https://docs.astral.sh/uv/) (`brew install uv`).

```bash
cd apps/api
uv python install 3.12      # one-time
uv venv --python 3.12        # creates .venv/
uv pip install -e ".[dev]"   # all dev deps + pip (needed by scripts/build.py)
```

Activate the venv with `source .venv/bin/activate`, or use `uv run <command>` without activating.

Alternatively, with plain pip (if Python 3.12 is on your PATH):
```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

## Commands

```bash
pytest -v                               # tests
pytest tests/handlers/google_auth -v    # single handler
ruff check . && ruff format --check .   # lint
mypy shared handlers                     # type check

python scripts/build.py                  # build all handlers → dist/
python scripts/build.py google_auth      # build single handler
```

The build script:
- runs `pip install -r handlers/{fn}/requirements.txt --target dist/_build/{fn}/ --platform manylinux2014_aarch64 --only-binary=:all:` (wheels for Lambda ARM64)
- copies `handlers/{fn}/*.py` + `shared/` into `dist/_build/{fn}/`
- zips `dist/{fn}.zip` deterministically (sorted files, fixed mtime)

The output `apps/api/dist/{fn}.zip` is consumed by `infrastructure/terraform/main.tf` (`module "lambda_X" { source_zip = "${path.module}/../../apps/api/dist/X.zip" }`).
