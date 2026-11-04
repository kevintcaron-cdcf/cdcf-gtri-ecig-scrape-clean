# Scrape Runner Usage

`run_scrape.sh` is the production entrypoint for running the configured
retailer scrapers. It activates the virtual environment and delegates to
`run_scrape.py`.

Do **not** invoke the Bash wrapper with Python:

```bash
# Correct
./run_scrape.sh
bash run_scrape.sh

# Also correct
python run_scrape.py

# Incorrect
python run_scrape.sh
```

## Basic command

From the repository root:

```bash
./run_scrape.sh
```

The default is to run up to **4 sites concurrently**. Each scraper remains a
separate subprocess, and each retailer's own request-delay settings are
preserved.

All options can be passed through the shell wrapper or directly to Python:

```bash
./run_scrape.sh [OPTIONS]
python run_scrape.py [OPTIONS]
```

## Command-line options

### `--workers N`

Maximum number of scraper processes to run concurrently.

```bash
./run_scrape.sh --workers 8
```

`N` must be at least `1`. The default is `4`, unless `SCRAPE_WORKERS` is set.

### `--state-dir PATH`

Directory containing the checkpoint and per-site logs.

```bash
./run_scrape.sh --state-dir /var/tmp/cdcf-scrape
```

Relative paths are resolved from the repository root. The default directory
is:

```text
.scrape-run/
```

### `--only SITE[,SITE,...]`

Run only the specified configured sites. Site names are the scraper filename
without its `.py` extension. The `scraping/` prefix and `.py` suffix are also
accepted.

```bash
./run_scrape.sh --only prilla,nicokick
./run_scrape.sh --only scraping/vapewh.py
```

Unknown site names cause the runner to exit with an error.

### `--from SITE`

Start with the specified site in the configured production order and include
all later sites. This is useful when working through the production list in
order.

```bash
./run_scrape.sh --from prilla
./run_scrape.sh --from scraping/nicokick.py
```

This option does not force already-successful sites to run again; use
`--no-resume` if that is desired.

### `--reset`

Delete the existing checkpoint before starting. Logs are retained and new
output is appended to the existing per-site log files.

```bash
./run_scrape.sh --reset
```

Use `--reset` carefully because it removes the runner's record of which sites
completed successfully. It does not delete database records or scraper data.

### `--no-resume`

Ignore successful statuses in the checkpoint and run all selected sites again.

```bash
./run_scrape.sh --no-resume
./run_scrape.sh --only vapewh --no-resume
```

Failed and interrupted sites are retried automatically even without this
option.

### `--list`

List all configured production sites and exit without running a scraper.

```bash
./run_scrape.sh --list
```

## Environment variables

### Runner variables

| Variable | Default | Description |
| --- | ---: | --- |
| `SCRAPE_WORKERS` | `4` | Default value for `--workers`. |
| `SCRAPE_STATE_DIR` | `.scrape-run` | Default value for `--state-dir`. |
| `SCRAPE_WRITE_DB` | Scraper-specific, normally enabled | Existing scraper setting controlling whether supported scrapers write to Azure SQL. |

Command-line options take precedence over the corresponding runner
environment variables.

Example:

```bash
SCRAPE_WORKERS=6 SCRAPE_STATE_DIR=/var/tmp/cdcf-scrape ./run_scrape.sh
```

### Scraper-specific variables

Individual scrapers also support their existing environment variables, such
as request delays, page/product limits, sample mode, and headless-browser
settings. These are passed through to each subprocess. Examples include:

```bash
SCRAPE_WRITE_DB=0 ./run_scrape.sh --only vapewh
VAPE_WH_REQUEST_DELAY=2 ./run_scrape.sh --only vapewh
NICOKICK_MAX_PRODUCTS=10 ./run_scrape.sh --only nicokick
HEADLESS=0 ./run_scrape.sh --only vapewh
```

Refer to the individual scraper source files for the exact variable names.
The runner does not overwrite general environment variables except for the
existing per-site overrides required by the production configuration:

- `HEADLESS=0` for `myvaporstore`
- `HEADLESS=0` for `vape_com`

## Checkpoints and resume behavior

The runner stores state in:

```text
.scrape-run/checkpoint.json
```

Each site has a status such as:

- `running`
- `succeeded`
- `failed`
- `interrupted`

A site is skipped on later runs only when its status is `succeeded`. Sites
marked `failed`, `interrupted`, or `running` are eligible to run again. This
means an interrupted run can be restarted with the same command and the
unfinished sites will be retried.

The checkpoint is written atomically so an interrupted write should not leave
a partially written JSON file.

## Logs

Each configured site writes combined standard output and error to:

```text
.scrape-run/logs/<site-name>.log
```

For example:

```text
.scrape-run/logs/vapewh.log
.scrape-run/logs/nicokick.log
```

The logs are appended to when a site is retried. Runtime timestamps and the
subprocess exit code are recorded in the log.

The `.scrape-run/` directory is ignored by Git and should remain local to the
machine running the scrapers.

## Interrupting a run

Press `Ctrl-C` once. The runner sends `SIGTERM` to active scraper process
groups, waits for them to exit, records them as interrupted, and exits with
status `130`.

Run the same command again to retry unfinished sites:

```bash
./run_scrape.sh
```

## Exit codes

| Exit code | Meaning |
| ---: | --- |
| `0` | All selected sites completed successfully, or all were already complete. |
| `1` | At least one selected site failed, or command-line validation failed. |
| `130` | The run was interrupted. |

## Common workflows

### First production run

```bash
./run_scrape.sh --workers 4
```

### Retry only failures

```bash
./run_scrape.sh --workers 4
```

Successful sites will be skipped automatically.

### Re-run one site after fixing its scraper

```bash
./run_scrape.sh --only vapewh --no-resume --workers 1
```

### Dry-run/sample validation

Use the scraper's own sample and database environment variables:

```bash
SCRAPE_WRITE_DB=0 VAPE_WH_SAMPLE=1 ./run_scrape.sh --only vapewh --no-resume
```

Not every scraper implements the same sample variable. Check the scraper file
before using a site-specific `*_SAMPLE` setting.

### Start at a later production site

```bash
./run_scrape.sh --from prilla --workers 6
```

### Run from a clean checkpoint

```bash
./run_scrape.sh --reset --workers 4
```
