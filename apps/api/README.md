# `@bodysync/api`

Python 3.12 Lambda backend dla bodysync.pl (per [ADR-002 lambda packaging](../../docs/adr/ADR-002-lambda-packaging.md)).

## Layout

```
apps/api/
├── pyproject.toml          # dev deps (pytest, moto, ruff, mypy)
├── shared/                 # importowane przez wszystkie handlery
│   ├── ssm.py             # get_param z module-level cache
│   ├── dynamo.py          # get_item / put_item / query_by_pk
│   ├── auth.py            # verify_jwt, mint_jwt
│   └── logging.py         # structured logger
├── handlers/
│   └── google_auth/
│       ├── handler.py      # def handler(event, context)
│       ├── schemas.py      # Pydantic input/output
│       ├── service.py      # logika osobno od event/context
│       └── requirements.txt # prod deps tylko dla tej Lambdy
├── tests/
│   ├── conftest.py         # fixtures: dynamodb_table (moto), ssm_params
│   └── handlers/google_auth/test_handler.py
├── scripts/
│   └── build.py            # produkuje dist/{fn}.zip per handler
└── dist/                   # gitignored — Terraform input
```

## Local setup

Wymaga [uv](https://docs.astral.sh/uv/) (`brew install uv`).

```bash
cd apps/api
uv python install 3.12      # one-time
uv venv --python 3.12        # creates .venv/
uv pip install -e ".[dev]"   # all dev deps + pip (potrzebne dla scripts/build.py)
```

Aktywacja venv: `source .venv/bin/activate` albo `uv run <command>` bez aktywacji.

Alternatywnie classic pip (jeśli masz Python 3.12 w PATH):
```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

## Komendy

```bash
pytest -v                               # tests
pytest tests/handlers/google_auth -v    # single handler
ruff check . && ruff format --check .   # lint
mypy shared handlers                     # type check

python scripts/build.py                  # build all handlers → dist/
python scripts/build.py google_auth      # build single handler
```

Build script:
- robi `pip install -r handlers/{fn}/requirements.txt --target dist/_build/{fn}/ --platform manylinux2014_aarch64 --only-binary=:all:` (wheels dla Lambda ARM64)
- kopiuje `handlers/{fn}/*.py` + `shared/` do `dist/_build/{fn}/`
- `zip dist/{fn}.zip` deterministycznie (sortowane pliki, fixed mtime)

Output `apps/api/dist/{fn}.zip` jest konsumowany przez `infrastructure/terraform/main.tf` (`module "lambda_X" { source_zip = "${path.module}/../../apps/api/dist/X.zip" }`).
