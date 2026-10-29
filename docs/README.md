# hindsight-house

A recall policy layer for the stock Hindsight memory provider of Hermes Agent. It is a separate plugin that subclasses the stock provider at load time. It does not fork, copy or edit the stock plugin.

Status: first release, for review. The code is the reviewed build whose test counts are in TESTING.md. Precision figures come from one deployment (PRECISION.md).

## Why

The stock provider (plugin name `hindsight`) recalls memories and injects them into the model context before each turn. An operator who runs several agents against one memory bank needs controls that the stock provider does not offer:

- keep records tagged as noise or superseded out of every recall;
- cap the number of injected results;
- stop injection in scheduled (cron) sessions;
- keep a long background-process notice from becoming the recall query;
- give a very short user message ("yes", "do it") the previous assistant statement as context.

The usual way to get these controls is to patch the stock file. A stock update then wipes the patch, and nothing says so. This plugin keeps the policy in its own folder, reaches stock code only through the public plugin loader, and checks on every load that the stock code still has the shape the policy relies on. When the check fails, the plugin stops injecting and says so in the log and in a flag file. It never runs the policy against code it has not verified.

## What each feature does

One line each. Every feature is off, or equal to stock behaviour, when its key is unset, with two exceptions marked below.

- Exclusion tags (`recall_exclude_tags`): results that carry a listed tag are removed by the server filter. Applies to the automatic path and to the `hindsight_recall` tool path.
- Result cap (`recall_max_results`): the automatic path injects at most N results. The tool path returns every server result.
- Cron switch (`recall_cron`): when false (the default of this plugin), a cron session gets no automatic injection. Stock has `retain_cron` for writes and no matching key for recall.
- Query cuts (`recall_query_cuts`): a rule list that cuts the recall query at a literal marker, for example the text before `Output:` in a background-process notice.
- Short-query context (`recall_short_query_chars`, `recall_short_query_context_chars`): a user message shorter than the threshold gets the tail of the previous assistant statement in the query. Read-only lookup in the Hermes session database, redacted, skipped when the text looks like a credential.
- Tool preamble: the stock key `recall_prompt_preamble` is also placed before the output of the `hindsight_recall` tool.
- Built-in memory mirror switch (`mirror_builtin_memory`): when false (default of this plugin), writes to the built-in memory are not copied into the bank.
- Floor (`recall_min_scores`): not a house feature. It is a stock key; the plugin leaves it alone.
- Drift guard: on every load, hashes the code of the stock methods the plugin overrides and compares with a table of reviewed revisions. See DRIFT-GUARD.md.
- Degraded provider: when the guard finds drift, the plugin serves a reduced provider: no injection, tool recall still filtered by the exclusion tags.
- Setup wizard fix: `post_setup` keeps `memory.provider` at `hindsight-house` after the stock setup wizard finished.

## Requirements

- Hermes Agent with the user memory plugin loader (a folder under `HERMES_HOME/plugins/` with a `plugin.yaml` of kind `exclusive`).
- The stock `hindsight` plugin installed in `HERMES_HOME/plugins/hindsight/`. The reviewed revision is 1.2.3. Any other revision loads in degraded mode until it is reviewed and added to `known_stock.json`.
- `hindsight_client` 0.10.2 or newer in the Hermes dependency environment. `Hindsight.arecall` must accept `tag_groups` and `min_scores`. The guard checks this.
- `hindsight` must stay in `plugins.enabled`, because the dependency set of the environment is computed from that list and `memory.provider`.
- Python 3.14 was the interpreter of every test run. No other version was tested.
- For short-query context: `recall_sync` true in the stock config, and read access to the Hermes session database in `HERMES_HOME`.

## Install in five steps

1. Back up `HERMES_HOME/plugins/hindsight/`, `HERMES_HOME/hindsight/config.json` and `HERMES_HOME/config.yaml` to a dated folder that does not exist yet.
2. Copy the plugin folder (without `tests/`) to `HERMES_HOME/plugins/hindsight-house/`.
3. Add the house keys to `HERMES_HOME/hindsight/config.json` (see CONFIGURATION.md). The tool `tools/apply_house_config.py` prints a key diff in a dry run and writes after a backup with `--apply`.
4. Set `memory.provider` to `hindsight-house` in `HERMES_HOME/config.yaml`. While the stock folder is still an unreviewed revision the plugin loads degraded, which is the safe state.
5. Run `tools/guard_check.py` with `HERMES_HOME` set, the Hermes dependency interpreter, and the installed stock and house folders as arguments (DRIFT-GUARD.md). Expect `OK`. Start a session and look for the log token `HINDSIGHT_HOUSE_GUARD` (it appears only on a problem).

Rollback: restore the stock folder first, then the config, then set `memory.provider` back to `hindsight`, then move the house folder away. The order matters: no process may ever see an unguarded stock revision. See UPGRADING.md.

## Configuration keys

| Key | Type | Default | Applies to |
|---|---|---|---|
| `recall_exclude_tags` | list, JSON list text or comma text | empty | auto and tool |
| `recall_max_results` | integer, 0 or more | 0 (no cap) | auto only |
| `recall_cron` | boolean | false | auto only |
| `mirror_builtin_memory` | boolean | false | memory writes |
| `recall_query_cuts` | list of rule objects, or JSON text | empty | auto only |
| `recall_short_query_chars` | integer, 0 or more | 0 (off) | auto only |
| `recall_short_query_context_chars` | integer, 0 or more | 400 | auto only |

A bad value never raises. It logs one warning that names the key (not the value) and uses the default. Details and an example: CONFIGURATION.md.

## How it was built

Automated agents built and reviewed it in rounds. A builder agent wrote the code and the tests. A reviewer agent read each round, ran its own probes, fixed defects in a separate copy and recorded each fix with a test. The pure modules (settings, policy, notice cut, previous statement) passed two review rounds before the provider class was written. The provider, the guard and the degraded provider passed the next review. The tools passed the one after. A parity run that compared this plugin with the patched plugin it replaces, on a read-only bank, passed the last review after the reviewer corrected the check script.

Choices that came from the reviews:

- A thread-local origin and a client proxy, not a copy of the stock recall method, and not a hook in stock code (ARCHITECTURE.md).
- The guard hashes code, with docstrings removed, not the version string.
- The tool path gets the exclusion filter too. An early design set the filter only on the automatic path and lost it on the tool path.
- Every defect found in review was fixed with a test that fails on the old code.

Test counts and coverage were measured by running the suites; see TESTING.md. Precision measurements, including those where precision fell, are in PRECISION.md. Proposed upstream requests are in UPSTREAM-ISSUES.md.
