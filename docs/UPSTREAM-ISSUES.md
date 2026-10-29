# Draft feature requests for the stock plugin

Status: the text of the six requests. Nothing here speaks for the project, promises a change, or states that the maintainers agreed to anything. Any item may be dropped or merged.

Common context for all six items. The stock memory provider (plugin name `hindsight`, reviewed at revision 1.2.3) has no place where a deployment can change the request arguments of a recall, cap the injected results, or stop injection on scheduled sessions. A deployment that needs these today either patches the stock file or subclasses the provider and reaches into it. The plugin in this repository does the second. Each request below would let the matching house code be deleted. The proposals are written against upstream main (which, at the time of review, differed from 1.2.3 in `queue_prefetch`, `on_memory_write` and `_apply_retain_policy`), not against 1.2.3.

Test evidence in each item refers to tests in this repository (TESTING.md: 437 passed for the plugin suite) and to measurements in PRECISION.md. A request would need its own tests in the project's own test suite; the tests here show the behaviour, not the project's conventions.

## Request 1: cap on the number of auto-injected results (`recall_max_results`)

Problem: the server returns up to a configured number of results, and stock injects all of them that clear the floor. A deployment that wants at most N bullets in the context has no setting for it. Raising the floor reduces the count but also removes relevant bullets (PRECISION.md, Section 4.3, floor sweep: relevant bullets fell from 68 to 59 as the floor rose from 0.90 to 0.94).

Proposal: a config key `recall_max_results`, integer, applied to the automatic injection path after the client returns and the floor is applied. The tool path is not capped. 0 or unset means no cap.

Default that keeps old behaviour: unset, which is no cap.

Test evidence: `test_cap_applies_on_the_auto_path`, `test_cap_never_applies_on_the_tool_path`, `test_no_cap_is_unchanged`, `test_cap_larger_than_the_list_keeps_everything`, `test_cap_of_exactly_the_length`, `test_cap_one_and_empty_list`, `test_the_cap_comes_from_parsed_settings`; parity run on a read-only bank: auto path result count equals the smaller of the server count and the cap.

## Request 2: exclusion tags on both recall paths (`recall_exclude_tags`)

Problem: records that a deployment marks as noise or superseded still come back from recall. The server supports a tag-group filter with a "not" leaf, but stock sends none. A subtle point: the tool path (`hindsight_recall`) and the automatic path both go through `_recall`, so a filter set only in the automatic entry point is lost on the tool path. An early house design had exactly that defect.

Proposal: a config key `recall_exclude_tags` (list, JSON list text or comma text). Stock `_recall` appends `{"not": {"tags": [...]}}` to any `tag_groups` it builds, and never sends `tags` and `tag_groups` together (the API rejects the pair with HTTP 422). Existing `tag_groups` of stock are kept, not replaced.

Default that keeps old behaviour: empty list; the request arguments are then returned unchanged.

Test evidence: `test_unset_is_identical_to_stock` (both origins), `test_exclusion_alone_builds_a_not_group`, `test_exclusion_combines_with_inclusion`, `test_existing_groups_inclusion_and_exclusion_in_order`, `test_existing_tag_groups_without_exclusion_are_untouched`, `test_t1_tool_path_has_preamble_exclusion_and_all_results`, `test_t2_auto_sync_is_capped_and_filtered`; an equality run of the argument rewrite against the patched plugin it replaced: equal in 72 of 72 grid cases (inclusion 3 by match mode 4 by exclusion 3 by origin 2), tags and tag_groups sent together in 0 of 72.

## Request 3: a switch for recall in scheduled sessions (`recall_cron`)

Problem: stock has `retain_cron` to control writes in scheduled sessions and has no matching switch for recall. A scheduled job that runs with an unrelated prompt gets bullets injected that cost tokens and can mislead the job.

Proposal: a config key `recall_cron`, boolean, read next to `retain_cron`. When false and the agent context is `cron`, `_recall_disabled()` returns true.

Default that keeps old behaviour: true upstream (recall stays on, as today). The house plugin defaults to false so that a config without the key does not inject on cron; that is a deployment choice and is not part of the request.

Test evidence: `test_cron_sessions_are_skipped_unless_recall_cron_is_on` (default: 0 bullets, 0 client calls; on: 3 bullets, 1 call), `test_recall_cron_default_is_false`, parsing tests for every boolean spelling and bad value.

## Request 4: query cut rules (`recall_query_cuts`)

Problem: the recall query is the first 800 characters of the user message. A gateway notice that carries script output sets the query to that output, and the bank answers the output words. In a replay of 31 such notices the strict relevance of the injected bullets was 8.8 percent (PRECISION.md, Section 1).

Proposal: a config key `recall_query_cuts`, a list of rules `{applies_if, cut_at, window, min_keep}`. A rule matches by a regular expression on the first `window` characters, cuts the query at a literal marker that sits at the start of a line, and fails open (no marker, or a kept part shorter than `min_keep`, leaves the query unchanged). Patterns that nest quantifiers are refused at load. Runs on the automatic path before stock truncation.

Default that keeps old behaviour: empty list.

Test evidence: `test_notice_cut.py` (rule cases, fail-open cases, property tests: never raises, output is a prefix of the input or equal to it, `min_keep` holds), nested-quantifier refusal tests in `test_house_settings.py`; replay on the site's bank: strict precision on 31 long notice turns 8.8 percent to 52.9 percent (interval +29.2 to +58.9 points); on 10 short control notices strict precision fell from 95.0 percent to 67.9 percent (interval -35.7 to -14.6). A reader of this request should know both results. One blind labeller, small samples, controls from another date (PRECISION.md).

## Request 5: switch for mirroring built-in memory writes (`mirror_builtin_memory`)

Problem: stock copies writes to the built-in memory into the bank through `on_memory_write`, with no way to turn this off. A deployment that treats the bank as curated cannot stop the copy without patching or overriding.

Proposal: a config key `mirror_builtin_memory`, boolean, read in `_apply_retain_policy`. When false, `on_memory_write` returns at once.

Default that keeps old behaviour: true upstream. The house plugin defaults to false; that is a deployment choice.

Test evidence: `test_mirror_switch_and_tool_handlers_and_schema`, and boolean parsing tests in `test_house_settings.py`.

## Request 6: a request-arguments hook and name-based tool dispatch

Problem: to change the arguments of `client.arecall` without copying `_recall`, the house plugin sets a thread-local origin, wraps the client in a proxy inside `_run_hindsight_operation`, and counts calls to fail closed. It also copies the class-level `_TOOL_HANDLERS` table to rebind one tool handler. This works, and a drift guard watches thirteen stock symbols, but every one of those couplings is a place where a stock refactor can break the house silently.

Proposal: one small hook, `_recall_request_kwargs(query, kwargs, origin)`, called by stock `_recall` just before it builds the client call, with the origin set to `auto` or `tool` by the two entry points. The default implementation returns `kwargs` unchanged. A second change: dispatch tools by method name (for example `getattr(self, name)`) instead of through a class dict of function objects, so a subclass can override one handler by overriding one method.

Default that keeps old behaviour: identity hook; dispatch result unchanged.

Test evidence in this repository is for the proxy version, which would be deleted if the hook were merged: `test_t1` to `test_t6` (tool path, auto sync path, auto async path on the loop thread, concurrent auto and tool recalls keep their own origin, a bypassing stock recall fails closed and is logged, the stale-daemon retry still carries the filter), `test_t4b_eighty_interleaved_recalls_keep_origin_filter_and_a_clean_thread_local`, `test_the_client_proxy_never_reads_the_thread_local`. The same tests, pointed at a hook, would be the acceptance tests for the request.

## Not proposed

- Short-query context (it reads the Hermes session database, which is outside the memory plugin's scope).
- The tool-output preamble wording (a deployment choice; the stock key `recall_prompt_preamble` already exists).
- Topic scoping with an unscoped retry (not built here; no configuration used it).
