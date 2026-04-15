# TDD Workflow

Red → Green → Refactor. Tests live in `tests/` and mirror package paths.

## Running

```bash
pip install -e '.[dev]'
pytest
```

Coverage gate is **80%** (branch coverage on `central_core_mqtt_shared`). Below that, `pytest` fails.

## Rules

1. Write a failing test first. Commit the red test before implementation if the change is non-trivial.
2. Write the minimum code to go green.
3. Refactor with the suite green. Never refactor on red.
4. One behavior per test. Name tests `test_<unit>_<condition>_<expected>`.
5. Async tests use plain `async def` — `asyncio_mode = "auto"` handles the rest.
6. Mock at boundaries only (network, filesystem, clock). Don't mock the code under test.
7. New public function/class ⇒ new test file or new test in the mirroring file.

## Coverage escape hatches

Mark genuinely untestable lines with `# pragma: no cover` and justify in the commit message.
Lower the gate only with explicit reviewer sign-off.
