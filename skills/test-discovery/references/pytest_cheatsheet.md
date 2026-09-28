# pytest selection cheatsheet

- One file: `tests/test_models.py`
- One test: `tests/test_models.py::test_parse_header`
- One method in a class: `tests/test_models.py::TestHeaders::test_parse`
- By substring: `-k "parse and not slow"`
- Stop at the first failure: `-x`
- Show locals on failure: `-l`
- Async tests (anyio is disabled by the harness's pytest.ini): tests marked `@pytest.mark.anyio` may be
  skipped. Use `pytest.mark.asyncio` tests or call the code from a script with `asyncio.run`.
- Parametrized ids: `tests/test_x.py::test_y[case-1]`. Quote them in the shell.
- Collection errors (`ERROR collecting`) usually mean an import-time failure in **your** edit. Check syntax
  and names first.
