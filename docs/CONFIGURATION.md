# Configuration

The house keys live in the same file as the stock keys: `HERMES_HOME/hindsight/config.json` (the file the stock provider already reads). The house provider calls the stock settings reader first, then parses the house keys from the same dictionary. A key that is missing gives its default. A key with a bad value logs one warning that names the key and never the value, and gives its default. The parser never raises.

`memory.provider` in `HERMES_HOME/config.yaml` must read `hindsight-house` (exact text; Hermes does not trim or case-fold it). `hindsight` must stay in `plugins.enabled`.

## House keys

| Key | Type | Default | Meaning | Auto path | Tool path |
|---|---|---|---|---|---|
| `recall_exclude_tags` | list of text, JSON list text, or comma-separated text | empty | Results that carry any of these tags are removed by the server filter. Blank and duplicate entries are dropped. | applied | applied |
| `recall_max_results` | integer, 0 or more | 0 | Maximum number of results that the automatic path injects. 0 means no cap. | applied (cut after the client returns) | not applied: every server result is returned |
| `recall_cron` | boolean (true, false, 1, 0, yes, no, on, off) | false | Whether a cron session gets automatic injection. | applied through the stock disable test, which guards only the automatic path (`prefetch` and `queue_prefetch`) | not applied |
| `mirror_builtin_memory` | boolean | false | Whether writes to the built-in memory are copied into the bank. | n/a (write path) | n/a |
| `recall_query_cuts` | list of rule objects, or JSON text of such a list | empty | Query cut rules, see below. | applied | not applied (the tool query is what the model wrote) |
| `recall_short_query_chars` | integer, 0 or more | 0 | A query shorter than this (after trimming) gets context. 0 turns the feature off. Needs `recall_sync` true. | applied | not applied |
| `recall_short_query_context_chars` | integer, 0 or more | 400 | How many trailing characters of the previous assistant statement to add. | applied | not applied |

Negative numbers, fractions, a boolean given for an integer key, and text that is not a number warn and give the default. A negative window or context size is not clamped to zero.

`recall_topic_rules` (a stock-patch feature of an older plugin) is not built. If it is set, the plugin logs one warning and ignores it.

### recall_query_cuts rule

| Field | Type | Default | Meaning |
|---|---|---|---|
| `applies_if` | text, regular expression | required | Matched with `re.search` on the first `window` characters of the query. A pattern that nests quantifiers is dropped. |
| `cut_at` | text, literal | required | The marker. A hit counts at index 0 or right after a line break. |
| `window` | integer, 1 or more | 400 | How many leading characters `applies_if` can see. |
| `min_keep` | integer, 0 or more | 40 | A cut that would keep fewer characters is not made. An empty cut is never made. |

A rule that is not an object, lacks a text `applies_if` or `cut_at`, has a bad pattern, a nested quantifier or a window of 0 is dropped, with a warning that names its index. A negative `window` or `min_keep` is a bad integer: it warns and takes the default (400 or 40), and the rule is kept.

## Stock keys that the house relies on

These belong to the stock plugin. Check its own documentation for the full list.

| Key | Why it matters here |
|---|---|
| `recall_min_scores` | The relevance floor, for example `{"final": 0.92}`. Stock sends it on both paths. The house does not touch it. Older patched plugins used a single number `recall_min_score`; stock 1.2.3 ignores that key. |
| `recall_sync` | Short-query context only runs when this is true. |
| `recall_max_input_chars` | Stock truncates the query to this length (default 800). The house computes the room that is left for the context so the user's own words are not cut. |
| `recall_prompt_preamble` | Text that stock puts before the injected memories. The house also puts it before the output of the `hindsight_recall` tool. It is not a house key. |
| `retain_cron`, `auto_retain` | Write-side switches. Not changed by the house. |

## Worked example

A profile in `hybrid` mode: automatic injection on interactive sessions, no injection on cron, at most 3 results injected, a floor of 0.92, noise and superseded records excluded on both paths, short messages under 60 characters get 400 characters of context, and background-process notices are cut before the `Output:` line.

    {
      "recall_sync": true,
      "recall_min_scores": {"final": 0.92},
      "recall_exclude_tags": "noise,superseded",
      "recall_max_results": 3,
      "recall_cron": false,
      "mirror_builtin_memory": false,
      "recall_short_query_chars": 60,
      "recall_short_query_context_chars": 400,
      "recall_query_cuts": [
        {
          "applies_if": "\\A\\s*\\[IMPORTANT: Background process proc_[0-9a-f]{8,32} [^\\n]{1,160}\\n[ \\t]*Command:",
          "cut_at": "Output:",
          "window": 400,
          "min_keep": 40
        }
      ]
    }

Leave out the connection keys of the stock plugin here; they are not part of the house policy and stay as they are.

For a profile in `tools` mode (no automatic injection) set only `recall_exclude_tags` and `recall_min_scores`. The cap, the cuts and the context apply to the automatic path and do nothing in that mode.

## Switches that restore stock behaviour

| To get stock behaviour for | Set |
|---|---|
| exclusion | leave `recall_exclude_tags` empty (kwargs are returned unchanged) |
| cap | `recall_max_results` 0 |
| cron injection | `recall_cron` true |
| memory mirror | `mirror_builtin_memory` true |
| cuts | leave `recall_query_cuts` empty |
| short-query context | `recall_short_query_chars` 0 |

Two defaults differ from a plain stock config on purpose: `recall_cron` is false and `mirror_builtin_memory` is false. A config that lacks both keys therefore does not inject on cron and does not mirror built-in memory writes. Set the keys explicitly in every config, so the value survives a future change of this plugin or of stock.

## The config tool

`tools/apply_house_config.py --home HERMES_HOME` prints a key diff and writes nothing. With `--apply` it writes `hindsight/config.json` after a dated backup, through a temporary file and an atomic rename, with the original file mode. It never prints the value of a key outside its whitelist (so never a key or a URL). It writes `recall_min_scores` from a legacy `recall_min_score` when needed (a legacy 0 writes no floor), `recall_cron` false, `mirror_builtin_memory` false and the notice-cut rule. It never touches `recall_max_results`, the exclusion, short-query and preamble keys. `--drop-legacy` removes the legacy key once a valid floor is in place, or at once when the legacy value is 0 (no floor either way). Exit codes: 0 done, 2 refused, 1 write failed. The notice-cut rule it writes fits the background-process notice format shown in the worked example, and the legacy-key handling serves configs of an older patched plugin. Check both against your own deployment before you use `--apply`.
