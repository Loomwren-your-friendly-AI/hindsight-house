# Drift guard

## What it protects against

The house provider changes behaviour by overriding stock methods and by wrapping the client that stock's recall method uses. If a new stock revision changes one of those methods, the override can silently do the wrong thing: for example send no exclusion filter, or inject on a path that should be closed. The guard turns that silent failure into a loud, safe one.

## When it runs

Once per process, inside `register()`, before the provider class is built. It reads the stock source as text. It never runs stock code and never uses the network.

## What it checks

1. Stock import: `import_provider_module("hindsight")` works, the module has a source file, and it defines `HindsightMemoryProvider`. Failure is FATAL.
2. Client: the package `hindsight_client` imports, and `Hindsight.arecall` accepts the parameters `tag_groups` and `min_scores`. A missing client is FATAL. A client that lacks a parameter is DRIFT (`client:tag_groups`, `client:min_scores`).
3. Code hash of each guarded symbol, compared with the table in `known_stock.json`.
4. Signature of each guarded method (the unparsed argument list), compared with the table.

Guarded symbols (the methods the house overrides or relies on): `_recall`, `_do_recall`, `prefetch`, `queue_prefetch`, `_run_hindsight_operation`, `_recall_disabled`, `_tool_recall`, `handle_tool_call`, `_TOOL_HANDLERS`, `on_memory_write`, `_apply_recall_settings`, `_apply_retain_policy`, `post_setup`.

## How the hash works

The hash is of code, not of the version string. For each guarded method of the stock class, the guard parses the stock file with `ast`, removes a leading docstring, dumps the tree without line numbers (`ast.dump(node, include_attributes=False)`), and keeps the first 16 hex characters of the SHA-256 of that dump. For `_TOOL_HANDLERS` it hashes the value of the assignment.

Consequences, each tested:

- A docstring-only edit, a comment, a blank line or a renumbered line does not change a hash. (An earlier design hashed docstrings; a docstring-only upstream edit would have put production into degraded mode.)
- A one-token change inside a guarded method changes its hash.
- A version bump with identical code stays OK.
- A code change under an unchanged version string is caught.

The known table can hold several accepted revisions. The guard compares the stock code with each row and keeps the best match (fewest failed symbols). If the best match has no failures, the revision is reported by its label; otherwise it is reported as `unknown`.

### What the hash does not see

The guard hashes the methods in the list, not the helpers they call. If a stock revision changes a module-level helper (for example the function that decides whether a result clears a floor) and leaves the guarded methods as they are, the guard stays OK. Review each new stock revision by diff, not only by guard result, and add helpers to the guarded list when the house starts to depend on them. The guard also does not check the behaviour of the server.

## Outcomes

| Status | Meaning | What runs |
|---|---|---|
| OK | every guarded hash and signature matches one reviewed revision, client accepts both parameters | the house provider |
| DRIFT | at least one hash, signature or client parameter differs | the degraded provider; log ERROR `HINDSIGHT_HOUSE_GUARD drift <failed symbols>` |
| FATAL | stock missing, client missing, known table empty or unreadable, the guard itself raised, or the provider class could not be built (`build:<error class>`) | nothing is registered; the profile runs without external memory; log ERROR `HINDSIGHT_HOUSE_GUARD fatal <reason>` |

FATAL holds only because `__init__.py` binds no provider subclass at module level (see ARCHITECTURE.md, loader facts). Any internal guard failure is turned into FATAL; the guard never raises into the loader.

## Degraded mode

The degraded provider is a subclass of the stock provider, built by a factory inside `register()`. It exists so that a drift cannot leave a profile on unguarded stock.

- `name` is `hindsight-house`, so `memory.provider` need not change.
- `_recall_disabled()` returns true: no automatic injection.
- `on_memory_write` does nothing (no mirror).
- `_recall(*args, **kwargs)` calls stock and removes results whose tags hit the exclusion list. It accepts any signature, so it also works on a stock revision whose `_recall` has a different signature.
- For the `hindsight_recall` tool, `handle_tool_call` sets a thread-local flag, calls stock, and returns the error text `recall unavailable: house guard` when the flag shows the filtered `_recall` was never entered. This fails closed instead of returning unfiltered results.
- Degraded settings parsing never raises: a failure is logged as an ERROR with the class name.

Degraded mode is a safe state, not a normal one. It loses injection. Treat any DRIFT as work to do.

## The flag file

On load the guard writes `HERMES_HOME/hindsight-house/guard_state.json` with these fields: `status`, `revision`, `failed` (list), `detail`, `written_at` (seconds since the epoch) and `written_at_iso`. The write is atomic (temporary file in the same folder, then rename). It writes when the status or the failed list changed, and otherwise at most once an hour, so a fresh DRIFT is never hidden by the rate limit. A write failure is a warning and does not stop the load.

A watcher that reads the flag files of the homes you name and prints one JSON line for each home that is not OK is part of the tool set: `tools/hindsight_house_guard_watch.py HOME [HOME ...]`, or the homes in the variable `HINDSIGHT_HOUSE_GUARD_WATCH_HOMES` (paths joined with the path separator of the OS). It has no default list: with no home it prints a message on stderr and exits 2. Otherwise it exits 0; the output contract is in the script's docstring. A home that runs the house provider and has no flag file, or a home whose configuration cannot be read, counts as a problem, not as silence.

## Running the check by hand

    HERMES_HOME=HERMES_HOME  PYTHON_OF_HERMES  tools/guard_check.py  HERMES_HOME/plugins/hindsight  HERMES_HOME/plugins/hindsight-house

It prints one line, `HINDSIGHT_HOUSE_GUARD status=... revision=... failed=...`, and exits 0 for OK, 1 for DRIFT, 2 for FATAL. Use the interpreter of the Hermes dependency environment, so `hindsight_client` can be inspected; under another interpreter the result is FATAL with `client:missing`. Pass both folders explicitly. Without the second argument the house folder is the package copy beside the tool (`../plugin/hindsight-house`), not the installed one; without the first, the stock folder is `HERMES_HOME/plugins/hindsight`. With `HERMES_HOME` unset and no folder argument it prints a FATAL line (`home:unset`) and exits 2, instead of reading `./plugins`. An internal crash of the tool also exits 2, never 1.
