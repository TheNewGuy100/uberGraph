# Release flow: dev → hmg → prd

Three long-lived branches, promoted in one direction. Production is `main`.

| Branch | Environment | What lands here | Gate to promote |
|---|---|---|---|
| `dev` | development | Day-to-day work and merged feature branches. May hold untested changes. | `python tools/test_all.py` passes. |
| `hmg` | staging ("homologação") | A stable slice promoted from `dev`. This is what is tried against a real game. | The `dev` gate, plus the manual checks below, run on the operator's machine with a real game and recorded in the changelog. |
| `main` (prd) | production | Released versions only. Every commit on `main` is a version with a tag `vX.Y.Z`. | The `hmg` checks passed on that exact commit, and the operator approves the release. |

## Rules

- **Promotion is a merge from the branch on its left, never a cherry-pick of unverified work and never a direct commit** on `hmg` or `main`.
  Use fast-forward merges (`git merge --ff-only dev` on `hmg`, then `git merge --ff-only hmg` on `main`) so the same commit moves through all three.
  If a fast-forward is impossible, `dev` has diverged: fix it on `dev`, run the gate again, promote again.
- **Commits happen only when the operator asks or closes a version** (see `AGENTS.md`); an agent does not commit or promote on its own initiative.
- **Nothing is pushed or published without the operator's say-so.** These branches are local until a remote exists.
- **Hotfix:** branch from `main`, fix, run the gate, merge to `main`, tag, then merge `main` back into `hmg` and `dev` so nothing is lost.
- **Never commit** game assets, extracted content, mapping files, local profile files or secrets (`tools/check-repo-hygiene.sh` enforces it and is part of the gate).

## The gate

```bash
python tools/test_all.py            # unit tests, Lua syntax, bridge and logger in a Lua VM, hygiene scan
python tools/test_all.py --quick    # skips the Lua VM tests and the hygiene scan (for quick local runs only)
```

A skipped step is reported with its reason; a release needs none skipped. One-time setup for the Lua steps: `cd tools/lua-check && npm install`.

## Manual checks for `hmg` (until CI and a second game exist)

Run on the operator's machine with a game profile. Record the game build and the result in `CHANGELOG.md`.

1. `python tools/drift/check_drift.py <game>` reports no drift for the game build the release targets.
2. Install the bridge (`python tools/bridge/install_bridge.py install --apply`), start the game, `python tools/bridge/bridge_client.py ping` shows the version of the release.
3. `cvar_get`, `find_all` and `describe_class` answer; `console_exec` and the other risky operations are refused while their option is off.
4. `python tools/term/uber_term.py --once --only bridge,probes` shows the bridge and probe lines with no escape characters in the log (`grep -c` for the escape character in `UE4SS.log` does not grow).
5. If the release touches cook or deploy: one cook and install of a small asset, then `deploy.py restore` puts the previous files back.

## Versions

Semantic versioning for the toolkit as a whole (`0.y.z` while it is alpha). The bridge keeps its own version in `bridge/uber-bridge/Scripts/main.lua`
(`VERSION`); a release notes both. Changes to the bridge protocol bump `PROTOCOL` and are called out in the changelog.

## Later (not done)

- CI that runs `tools/test_all.py` on every push to `dev` and blocks promotion on failure (waits for a remote and a second game to test against).
- Branch protection on `hmg` and `main` once the project has a remote.
