<h1 align="center">tinychat</h1>
<p align="center">Chat so small it fits in 1 python file</p>

> 🚧 This project is in active development. Things might be broken and will likely change.

![Screenshot](./desktop.png)

# Hacking on the app locally

Make sure you have Poetry [installed](https://python-poetry.org/docs/#installation)

```
LIVE_RELOAD=yes poetry run python app.py
```

# Running tests locally

If running tests for the first time, install drivers for playwright

```
poetry run playwright install
```

Run tests

```
TEST_MODE=yes poetry run pytest app.py --base-url http://localhost:5002
```

Run tests with debugger

```
TEST_MODE=yes PWDEBUG=1 poetry run pytest app.py --base-url http://localhost:5002 -s
```

# Deploy

Check [deploy](https://github.com/callmephilip/tinychat/tree/deploy) branch for an example deployment approach. Additional deps:

# Run load tests

`poetry run locust -f locustfile.py --headless`

# Figure out machine resources

- get number of CPUs `getconf _NPROCESSORS_ONLN`
- get total memory `grep MemTotal /proc/meminfo` or use `free`: shows total, used 
- people talking about hosting laravel sites on $6 droplets: https://www.reddit.com/r/laravel/comments/watkc0/how_many_laravel_projects_can_a_digital_ocean_6/

# Build and run docker locally

docker build -t tinychat .
docker run -d  --name  tinychat -p 5001:5001 -v $PWD/data:/code/data tinychat
