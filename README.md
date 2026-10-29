# hindsight-house

A memory provider plugin for Hermes Agent. It subclasses the stock Hindsight provider and adds a recall policy: exclusion tags, a result cap, a notice cut for background-process notices, and short-query context. A drift guard compares the stock source with a reviewed hash table and fails closed when the stock plugin has changed.

Documentation: see docs/README.md.

## Layout

- plugin/hindsight-house/ is the plugin (nine files). Its tests are in plugin/hindsight-house/tests/.
- tools/ holds three scripts: guard_check.py (run the drift check), apply_house_config.py (write the house keys into a home's hindsight/config.json) and hindsight_house_guard_watch.py (report homes whose guard flag is missing or not OK). Their tests are in tools/tests/.
- fixtures/ holds unmodified copies of the stock plugin that the tests use, with the upstream licence text. See fixtures/NOTICE.md.

## Running the tests

The tests need pytest, hypothesis and PyYAML. The plugin tests start child processes under the real Hermes plugin loader, so they need two absolute paths from the environment:

    export HINDSIGHT_HOUSE_TEST_HERMES_AGENT_DIR=<folder of a Hermes checkout that holds hermes_bootstrap.py>
    export HINDSIGHT_HOUSE_TEST_HERMES_HOME=<a Hermes home, read only, used once to find hindsight_client>
    export HERMES_HOME=<an empty scratch folder> HERMES_DISABLE_LAZY_INSTALLS=1
    cd plugin/hindsight-house/tests
    pytest -q -p no:cacheprovider --rootdir=. --confcutdir=. .

For branch coverage of the six modules, also set HH_COV_DIR to a scratch folder and HINDSIGHT_HOUSE_TEST_COVERAGE_SITE to the site-packages folder that holds the coverage package. A missing variable stops the run with a message that names it.

The tool tests run from the package root:

    pytest -q -p no:cacheprovider -o pythonpath=tools tools/tests

## Licence

MIT. Copyright (c) 2026 the hindsight-house contributors.

The stock fixtures under fixtures/ keep their own upstream licence (MIT, fixtures/LICENSE-hindsight-upstream); see fixtures/NOTICE.md.
