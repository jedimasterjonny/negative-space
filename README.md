# Negative Space



## Getting started

```sh
uv sync      # create the venv and uv.lock — commit the lockfile
just hooks   # install the pre-commit, commit-msg and pre-push hooks
just check   # lint + format check + typecheck + test
```

Run `just` to list every command.

## Configuration

Settings live in `src/negative_space/settings.py` and are loaded by
pydantic-settings from `.env` (gitignored; see `.env.example`).

Every key in `.env` needs a matching field on `Settings` — unknown keys are
rejected, so a typo fails loudly instead of being silently ignored.

## Updating from the template

```sh
just update-template
```
