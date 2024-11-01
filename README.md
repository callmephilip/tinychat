# Hello

# Hacking on the app locally

```
LIVE_RELOAD=yes poetry run python app.py
```

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
TEST_MODE=yes PWDEBUG=1 poetry run pytest app.py -s
```

Run playwright codegen

```
poetry run playwright codegen http://localhost:5001
```