# Hello


# Running tests locally

Run tests

If running tests for the first time, install drivers for playwright

```
poetry run playwright install
```

```
TEST_MODE=yes poetry run pytest app.py --base-url http://localhost:5002
```

Run tests with debugger

```
PWDEBUG=1 poetry run pytest -s
```

Run playwright codegen

```
poetry run playwright codegen http://localhost:5001
```