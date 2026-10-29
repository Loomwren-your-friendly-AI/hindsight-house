# Testing

All counts below were measured by running the suites on a copy of the package in a scratch folder, and are copied from the output of those runs. They are not taken from any report. Python was 3.14.8 (the interpreter of the QA virtual environment); pytest and coverage come from that environment.

## Plugin suite

Run on a copy of the plugin folder with its `tests/` folder:

    cd PACKAGE/plugin/hindsight-house/tests
    export HERMES_HOME=WORKDIR/home HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1
    export HINDSIGHT_HOUSE_TEST_HERMES_AGENT_DIR=HERMES_CHECKOUT HINDSIGHT_HOUSE_TEST_HERMES_HOME=HERMES_HOME_FOR_THE_SITE_PROBE
    QA_VENV/bin/pytest -q -p no:cacheprovider \
      --cov=house_settings --cov=recall_policy --cov=notice_cut --cov=prev_statement \
      --cov=drift_guard --cov=degraded --cov-branch --cov-report=term-missing \
      --rootdir=. --confcutdir=. .

The first folder holds `hermes_bootstrap.py`; the second is a Hermes home that `hermes_site()` uses once, read only, to find `hindsight_client`. A missing variable stops the run with a message that names it. For coverage set `HH_COV_DIR` and `HINDSIGHT_HOUSE_TEST_COVERAGE_SITE` (the site-packages folder that holds `coverage`).

Result: `437 passed in 11.79s`, exit code 0.

Why from `tests/`: the plugin folder contains an `__init__.py`, so pytest started in that folder treats it as a package and fails to collect. Starting in `tests/` with `--rootdir=. --confcutdir=.` collects normally. `HERMES_HOME` must point at a scratch folder: the test driver refuses a home that is not under the folder that the test helper creates (under `TMPDIR`), and no test may read or write a real profile.

Branch coverage for the six pure and guard modules, from the same run:

| Module | Statements | Missed | Branches | Partial branches | Coverage |
|---|---|---|---|---|---|
| `house_settings.py` | 107 | 0 | 40 | 0 | 100% |
| `recall_policy.py` | 70 | 0 | 28 | 0 | 100% |
| `notice_cut.py` | 23 | 0 | 14 | 0 | 100% |
| `prev_statement.py` | 26 | 0 | 6 | 0 | 100% |
| `drift_guard.py` | 119 | 0 | 26 | 0 | 100% |
| `degraded.py` | 43 | 0 | 4 | 0 | 100% |
| total of the six | 388 | 0 | 118 | 0 | 100% |

`__init__.py` (the provider class, the proxy, `register`, `post_setup`) runs inside child processes that start the real loader. Its coverage was collected from those child processes into a separate data folder and combined: 145 statements, 0 missed, 24 branches, 0 partial, 100%. The same combined report shows lower numbers for the six modules above (65 to 84 percent), because the child scenarios exercise only part of each of them. The 100 percent figures of the table come from the module tests, not from the child scenarios. Coverage of 100 percent says every line and branch ran; it does not say every behaviour was asserted. A mutation run found survivors that the reviewers classed as equivalent or as wording only (see below).

### What the test files cover

| File | Subject |
|---|---|
| `test_house_settings.py` | parsing of every house key, bad values, defaults, nested-quantifier refusal; plus the cases that came from reviewer findings (recall_cron default, negative values, window and empty-cut edge cases) |
| `test_recall_policy.py` | `rewrite_kwargs` over a grid of inclusion, match mode, exclusion and origin; cap; short-query composition; credential cues; plus the reviewer case of a missing redact callable |
| `test_notice_cut.py` | notice-cut rules, fail-open cases, property tests with hypothesis (never raises, output is a prefix, `min_keep` holds) |
| `test_prev_statement.py` | read-only lookup, whitespace rows, schema and lock failures, relative path; plus the reviewer cases (blank rows, relative home, integer session id) |
| `test_drift_guard.py` | hash rule (docstring-only edit stays OK), signatures, client parameters, flag file, FATAL cases |
| `test_degraded.py` | degraded provider: no injection, filtered tool recall, fail-closed flag |
| `test_provider.py` | the provider class in child processes under the real loader: origin on both paths, proxy count, thread names, many-thread interleave, thread-local cleanup, `post_setup`, registration |

Helpers: `conftest.py`, `helpers.py` (loader scenarios, stock variants; the two environment variables) and `hh_driver.py` (the child process that loads the plugin and records what the fake client received).

## Tool suite

    cd PACKAGE
    QA_VENV/bin/pytest -q -p no:cacheprovider -o pythonpath=tools tools/tests \
      --cov=hindsight_house_guard_watch --cov=apply_house_config --cov-branch --cov-report=term-missing

The result is `173 passed in 1.62s`, exit code 0.

| Module | Statements | Missed | Branches | Partial | Coverage | Missing lines |
|---|---|---|---|---|---|---|
| `apply_house_config.py` | 177 | 1 | 60 | 1 | 99% | 278 |
| `hindsight_house_guard_watch.py` | 186 | 3 | 82 | 1 | 99% | 47-48, 273 |

The two coverage rows come from the run of the tools tests alone (173 passed, exit code 0).

`guard_check.py` is exercised through the plugin suite (`test_provider.py`); its coverage was not measured separately: not measured.

## Other checks (reviewer-reported, not re-run for this page)

The reviewer agent reported these on earlier builds. They were not re-run for this page, so they carry no figure here beyond the source's own words: mypy in strict mode on the four pure modules (no issues), pyright (0 errors), an ast-grep rule for bare `except:` (0 hits), a secret scan of the build folder (no leak), and a mutation run with mutmut on the pure modules (hundreds of mutants; the survivors were wording-only or equivalent, and the real gaps were closed with tests). Re-run them before a release.

## Notes on the measurement

- The plugin suite starts child interpreters. In the copy used for these counts three lines of `helpers.py` were changed: the location of the dependency site folder is fixed to the Hermes dependency environment, the child start command no longer imports the Hermes bootstrap module, and the child interpreter is the interpreter of that environment. Test logic and test files were not changed. Your layout will differ; adjust `hermes_site()` and the child start command in the helper to your environment. The helper reads two absolute paths from the environment variables named in the comment at the top of `helpers.py`.
- Every run used a scratch `HERMES_HOME`, `HERMES_DISABLE_LAZY_INSTALLS=1`, and no network. The suites read no key, no `.env` file and no real session database.
- Suite time is about 12 seconds for the plugin suite and about 2 seconds for the tool suite on the measuring host.
