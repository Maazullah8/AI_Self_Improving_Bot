# Agent Instructions

## Testing

Run the full test suite before finishing any task:

```bash
PYTHONPATH=/workspace/src python3 -m pytest tests/ -q
```

Long-running end-to-end tests are marked `slow` and run as part of the suite.
To run only fast tests:

```bash
PYTHONPATH=/workspace/src python3 -m pytest tests/ -q -m "not slow"
```

## Lint / typecheck

No linter or type checker is configured for this Python repo. The de-facto
quality gate is the pytest suite plus:

```bash
PYTHONPATH=/workspace/src python3 -m compileall -q src
```

## Conventions

- Timestamps are integer epoch SECONDS in UTC (`core.time_utils`).
- Domain models are frozen dataclasses in `core/models.py`.
- Data providers normalize into `Candle`/`Tick`; never couple strategy/replay
  code to a concrete provider.
- Storage is protocol-based; backtests/tests use `MemoryStore`, production uses
  `PostgresStore`. Never require a database in unit tests.
- Strategies are versioned append-only; candidates are created via
  `CandidateGenerator` and must pass `PromotionGate` before promotion.
- Fail-closed: any unknown/unhealthy state must result in no trade.
