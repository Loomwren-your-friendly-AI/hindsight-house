# Architecture

## Layers

    Hermes plugin loader
      -> plugins/hindsight-house/__init__.py   register(ctx): guard, then provider class
           house_settings.py   parse and validate the house keys (pure)
           recall_policy.py    rewrite_kwargs, cap_results, compose_short_query, credential cue (pure)
           notice_cut.py       cut_query(text, rules) (pure)
           prev_statement.py   read-only lookup of the previous assistant statement
           drift_guard.py      hash the stock code, compare with known_stock.json, write the flag file
           degraded.py         factory for the reduced provider
           known_stock.json    accepted code hashes and signatures per stock revision
      -> plugins/hindsight/                    the stock plugin, untouched, imported through the loader

"Pure" means standard library only and no work at import time. A pure module has its own test file and, in review, 100 percent branch coverage (see TESTING.md).

The house provider is a subclass of the stock `HindsightMemoryProvider`. The subclass is built inside `register()`, after the guard ran, from the class object that the loader returns for the stock plugin. Nothing in the house package imports the stock plugin at module level.

## Loader facts

These were observed by running the real loader on a scratch home (not inferred from a code read):

- The loader gives each plugin a module name of the form `_hermes_user_memory.<folder>__source_<16 hex>`. The hex part hashes the folder path, so no absolute import name is stable.
- The loader publishes a package shell, then runs each top-level `*.py` sibling in directory order (file system order, not sorted), then runs `__init__.py` last. A sibling that another sibling imports runs at that import and is skipped later.
- Siblings can import each other by relative import only (`from . import house_settings`). A bare `import house_settings` fails, and the loader drops that sibling with a DEBUG log. The package still loads. For that reason `__init__.py` imports every sibling it needs by explicit relative import: a broken sibling then fails the load instead of vanishing.
- The loader binds sibling names on the package only after `__init__.py` ran. Code in `__init__.py` must not rely on a bare sibling name in its globals.
- The stock plugin is reached through `plugins.memory.import_provider_module("hindsight")`. It returns one module object per process (the same object on every call). The stock `register()` is never called, so only one provider registers.
- If `__init__.py` binds a `MemoryProvider` subclass at module level and `register()` registers nothing, the loader instantiates that subclass as a fallback. So the house binds no provider subclass at module level. A failure at module level is swallowed with a DEBUG log, and no guard flag would be written; the stock import and the class definitions therefore run inside `register()`.
- Isolation mode `in_process` (the default) was the only mode tested.

## The recall client proxy and the thread-local origin

Stock `_recall` builds the request arguments in the caller thread, then runs a closure on a shared loop thread that calls `client.arecall(bank_id=..., **kwargs)` once per bank. The house needs to change those arguments without copying the stock method.

Design: a module-level `threading.local()` holds the origin of the current recall, and a proxy wraps the client for the duration of one recall.

| Method | Sets | Clears |
|---|---|---|
| `prefetch(query, *, session_id="")` | session id | in `finally` |
| `_do_recall(query)` | origin `auto`, after the notice cut and the short-query context | in `finally` |
| `_recall(query)` | recall context: (origin, counter); origin is the set origin or `tool` when none is set | in `finally` |
| `_run_hindsight_operation(operation)` | calls super with the operation wrapped so it receives the proxy | n/a |

- A thread-local is used, not a context variable. The Hermes helper that spawns context threads copies context variables into child threads. A thread-local cannot leak that way.
- `_recall` always sets the recall context. The tool path (`hindsight_recall`) enters stock `_recall` without passing `_do_recall`, so the origin is `tool` there. An early design set the context only in `_do_recall`; its tool path then sent no tag filter and the exclusion was lost. A test fails on that design.
- The proxy forwards every attribute through `__getattr__` and defines only `arecall`. It appends to a counter, then calls the real `arecall` with the kwargs rewritten by `rewrite_kwargs(kwargs, policy, origin)`.
- The proxy holds its origin and counter from construction. It never reads the thread-local itself, because the real call runs on the loop thread, where the thread-local is empty.
- The stale-daemon retry of stock goes through `operation(...)` again, so the retry also goes through the proxy.

### rewrite_kwargs

- No exclusion tags configured: return the kwargs unchanged.
- Otherwise remove `tags` and `tags_match`, keep any `tag_groups` that stock built, append `{"tags": inclusion, "match": tags_match}` when stock had inclusion tags, then append `{"not": {"tags": exclusion}}`.
- Never return both `tags` and `tag_groups`: the API rejects the pair with HTTP 422.
- Keeping stock's own `tag_groups` is deliberate. Replacing them would silently widen recall.

### Cap and the two paths

The cap applies only when the origin is `auto`: the house `_recall` returns `results[:cap]`, so stock `_do_recall` formats and counts the capped list. The tool path returns every server result. The reviewer confirmed in a parity run that the replaced patched plugin behaves the same way (its cap sat in `_do_recall`).

## Fail closed

After each `super()._recall(...)`, if the proxy counter is empty, the recall bypassed the proxy (for example an upstream change that stops calling `_run_hindsight_operation`). The provider logs an ERROR with the token `HINDSIGHT_HOUSE_GUARD recall-bypass` and raises `HouseGuardError`. The check is unconditional and costs nothing when no house key is set. Effect: on the auto path stock `_do_recall` logs a warning and the turn runs without injection; on the tool path the tool returns an error.

## Other overrides

| Override | Behaviour |
|---|---|
| `name` | `hindsight-house` |
| `_apply_recall_settings(cfg)` | calls super, then parses the house keys from the same dict |
| `_apply_retain_policy(cfg)` | calls super, then reads `mirror_builtin_memory` |
| `_recall_disabled()` | true when super says so, or when `recall_cron` is false and the agent context is `cron` |
| `_do_recall(query)` | notice cut, short-query context, origin `auto`, then super |
| `_tool_recall(args)` | calls super and prepends the stock preamble (`recall_prompt_preamble`) unless the result is the stock empty-result sentence |
| `_TOOL_HANDLERS` | class dict copied from stock, with the `hindsight_recall` entry rebound to the house method |
| `on_memory_write(...)` | same signature as stock; returns at once when `mirror_builtin_memory` is false |
| `get_config_schema()` | stock schema plus the house keys |
| `post_setup(hermes_home, config)` | see below |

`post_setup`: the stock setup wizard writes `memory.provider = "hindsight"` on its finish path, which would switch the profile back to the stock plugin without any guard. The override sets the provider name before calling super and restores the earlier value in `finally` unless the wizard finished (a wizard cancelled at a prompt must leave the configuration as stock leaves it). When the wizard finished, it sets `hindsight-house` and saves the configuration again.

## Notice cut

A rule is `{applies_if, cut_at, window, min_keep}` (defaults for the last two: 400 and 40).

1. `applies_if` is a regular expression matched with `re.search` on the first `window` characters only. It is compiled once at config load. A bad pattern drops that rule with a warning.
2. `cut_at` is a literal. A hit counts only at index 0 or right after a line break (`\n`, `\r`, U+2028, U+2029) in the original text. The query is cut there and trailing whitespace is stripped. No normalisation, no mapping back.
3. Fail open: no marker, or a kept part shorter than `min_keep`, returns the query unchanged. An empty cut is refused even with `min_keep` 0.
4. Rules apply in order; the first rule that applies and yields a usable cut wins. A rule that applies but finds no usable cut falls through to the next.
5. Auto path only. It runs before the short-query context and before stock truncation.
6. `cut_query` has no timeout. A pattern that nests quantifiers (for example `(a+)+`) is dropped at load with a warning. The check is a heuristic. It does not catch overlapping alternation such as `(a|aa)+`, a nested quantifier through an inner group such as `((a+))+`, or adjacent quantifiers such as `\s*\s*\s*`. Review every new rule by hand.

## Short-query context

Applies when `recall_sync` is true, `recall_short_query_chars` is above 0, a session id is known, and the trimmed query is shorter than the threshold.

- `previous_assistant_statement(hermes_home, session_id)` opens the session database read-only (a `file:` URI with `mode=ro`), runs one parameterised query for the newest usable assistant row, with a 0.2 second busy timeout, and fails open to an empty string. `hermes_home` must be an absolute path; a relative or empty path gives an empty string, so a database in the working folder is never read. The SQL trims space, tab, LF, VT, FF and CR, so a newer blank row does not hide the older usable one.
- `compose_short_query(query, previous, policy, max_input_chars, redact)` builds `Context (assistant's previous statement): <last N characters>` plus `User message: <query>`. N is `recall_short_query_context_chars`. The room left by the stock input limit is computed first, so stock truncation cannot cut the user's own words.
- The previous statement is passed through a redaction function before use. If redaction is unavailable, raises, or returns a non-text value, no context is added. Only the class of a failure is logged.
- A credential cue in the text (words such as password, passphrase, api key, private key, bearer, credential; six to eight digits near otp, one-time, verification or 2fa; a base64 run of 60 or more characters; a key-armor line; credentials inside a URL) also adds no context. The words "secret", "token" and "code" are deliberately not cues. Only the cue class is logged.

## Failure modes

| Situation | Result | Where you see it |
|---|---|---|
| Guard OK | house provider | flag file status `OK` |
| Stock code differs from every reviewed revision, or the client lacks `tag_groups` or `min_scores` | degraded provider | log `HINDSIGHT_HOUSE_GUARD drift <symbols>`; flag status `DRIFT` |
| Stock module cannot be imported, has no source file, client package missing, known table empty, guard raised, provider class could not be built | nothing registered; the profile runs without external memory | log `HINDSIGHT_HOUSE_GUARD fatal ...`; flag status `FATAL` |
| A recall bypasses the proxy at run time | recall fails closed (no injection or a tool error) | log `HINDSIGHT_HOUSE_GUARD recall-bypass` |
| Bad config value | default used | one warning that names the key |
| Previous-statement lookup fails or times out | query sent without context | none (fail open) |
| Redaction unavailable or failed | no context added | DEBUG log line with the failure class only |
| Flag file cannot be written | provider still loads | warning `flag not written` |
| Setup wizard run | provider name kept at `hindsight-house` | config file read-back |
| `plugins.enabled` loses `hindsight` | client dependency may vanish from the environment; guard reports FATAL | log |

Other places that key on the provider name `hindsight` (and so need a decision before the switch): any hook plugin that tests `memory.provider == "hindsight"`, the stock setup wizard (handled), the profile-clone command (copies the folder of the provider name, so copy the stock config folder by hand), the dashboard memory panel (reads the config of the provider name; edit the file by hand), and log labels that contain the provider name.
