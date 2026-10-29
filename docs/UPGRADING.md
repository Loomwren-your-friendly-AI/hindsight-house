# Upgrading the stock plugin

The house plugin sits on a stock plugin it does not control. This page gives the order of steps that never leaves a profile on unguarded stock, and the review that a new stock revision needs before the house trusts it.

## Facts that set the order

- A catalog update of the stock plugin re-pins its folder to a catalog revision. For a plugin folder without a `.git` directory, the update finds no local changes to stash, so a patch you made in the stock folder is lost without a backup. This plugin needs no patch in the stock folder, but a backup of the folder is still the first step.
- The re-pin can stop for consent when the plugin surface changes. Run it interactively and read the change. Do not pass a force flag.
- A stock revision newer than the reviewed one makes the guard report DRIFT. The house then runs degraded: no injection, tool recall filtered. That is safe but costly.
- A profile that points at stock before the house is active has none of the house policy: no exclusion, no cap, and the mirror on. Do not leave a window in which a new process can start on stock.
- Hermes does not trim or case-fold `memory.provider`. A value such as ` hindsight-house ` or `Hindsight-House` loads nothing.

## Switching a profile to the house plugin (cut-over)

Do one profile at a time. Start with a profile that uses recall only through the tool, then the others.

1. Back up the stock folder, `hindsight/config.json` and `config.yaml` to a new dated folder. Refuse to continue if that folder already exists, and make it readable by the owner only. A second attempt must never overwrite the first backup with files that are already changed.
2. Check that no house state exists from an earlier attempt: no `HERMES_HOME/hindsight-house/` folder. A stale `OK` flag would hide a plugin that never loads.
3. Copy the house folder (without `tests/`) to `HERMES_HOME/plugins/hindsight-house/`.
4. Run the config tool in dry-run mode, read the diff, then run it with `--apply`.
5. Set `memory.provider` to `hindsight-house`. On an unreviewed stock revision the house loads degraded. That is the safe state.
6. Run `tools/guard_check.py` with the Hermes interpreter and both folders as arguments. Expect DRIFT on an old stock revision, OK on a reviewed one.
7. Update stock (see below), then run the config tool again with `--drop-legacy` if an old floor key is present, and run the guard check again. Expect OK.
8. Check that the plugin manager lists the house plugin as a manual install and the stock plugin as up to date.
9. Run one live turn that exercises recall. For a profile in tools mode, "reply with one word" exercises no recall: ask something the bank answers.

If another hook plugin tests `memory.provider == "hindsight"`, change it to accept both names before step 5.

## Updating the stock plugin after the cut-over

1. Read the diff of the new stock revision against the reviewed one, at least for the 13 guarded symbols and for every module-level helper those symbols call.
2. In a scratch copy, add the new revision to `known_stock.json` and run the tests (TESTING.md) and the guard check against the new stock folder. Rows are produced by `drift_guard.symbol_table(source_text)`, which returns the hashes and the signatures; a row is the object `{"hashes": {...}, "signatures": {...}}` under `revisions` and the revision label. A tool that writes the row is not part of this draft.
3. Add the row only after the diff review. A hash row that was never reviewed turns the guard into a rubber stamp.
4. Back up, update stock interactively, read the consent text, accept.
5. Run the guard check. OK means every guarded hash and signature matches a reviewed row.
6. Keep the old row in the table while any profile still runs the old revision.

## When the guard says DRIFT

1. Read the failed list: it names the symbols (`_recall`, `sig:_recall`, `client:tag_groups`).
2. The profile already runs degraded; nothing is unguarded. Decide between rolling stock back and reviewing the new revision.
3. After review, add the row (above) or fix the override in the house code, run the tests, and reload.
4. The flag file shows the new status on the next load.

## Rollback of a profile

The order matters: the stock folder comes first, so that no process sees unguarded stock.

1. Move the current stock folder aside, put the backed-up stock folder back (the house now degrades, which is safe).
2. Restore `hindsight/config.json` from the backup.
3. Set `memory.provider` back to `hindsight`.
4. Move the house folder away.
5. Restart the long-running gateway process, if there is one.

## Things that key on the provider name

Before the first cut-over, check each of these. None is changed by the house plugin except the setup wizard.

| Place | Effect of the new name | Action |
|---|---|---|
| Hook plugins that compare `memory.provider` with `hindsight` | they stop acting after the switch | accept both names first |
| Stock setup wizard | writes `hindsight` on finish | handled by `post_setup` |
| Profile clone | copies the folder named like the provider | copy the stock config folder by hand |
| Dashboard memory panel | reads the config of the provider name | edit the file by hand |
| Log labels with the provider name | change | update any parser |
| Auto-install of the stock plugin for the name `hindsight` only | does not fire for the house name | the guard reports FATAL if the stock folder is missing |

## Dependencies

The plugin has no `pyproject.toml`, on purpose. The dependency set of the environment is computed from `plugins.enabled` plus `memory.provider`, so keep `hindsight` in `plugins.enabled`. A package file for the house would remove that need, but a failed build of an enabled plugin makes the plugin manager clear `memory.provider` without a message, which is worse.
