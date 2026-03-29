# Contributing

Contributions are welcome.

## Priorities

The highest-value contributions are:

- correctness fixes in provenance enforcement
- transport hardening
- test coverage for edge cases and failure paths
- documentation improvements
- deployment and packaging cleanup

## Development

Install Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run tests:

```bash
pytest -q
```

Build the console:

```bash
cd console
npm install
npm run build
```

## Pull Requests

- keep changes scoped and coherent
- add or update tests for bug fixes and invariants
- avoid weakening fail-closed behavior around served-reference provenance
- document any contract changes affecting Claude or Codex integrations
