# Project Overview

Web API for order processing, written in Python 3.11 with FastAPI.

## Guidelines

- Run `pytest -q` before every commit because CI blocks unverified merges.
- Keep endpoint handlers in `src/api/routes/` and business logic in `src/api/services/` to avoid circular imports.
- Use `ruff check src tests` to lint; fix findings instead of suppressing them.
- Pin dependencies in `requirements.txt` with exact versions to ensure reproducible builds.
- Target Python 3.11; do not use language features newer than 3.11.

## Example

Preferred error handling:

```python
raise OrderError(f"order {order_id} not found")
```
