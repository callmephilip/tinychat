# Hello


# Running tests locally

Run tests

```
TEST_MODE=yes poetry run pytest app.py --base-url http://localhost:5001
```

Run tests with debugger

```
PWDEBUG=1 poetry run pytest -s
```

Run playwright codegen

```
poetry run playwright codegen http://localhost:5001
```