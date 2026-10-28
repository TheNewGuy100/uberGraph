#!/usr/bin/env bash
# Fails if the repository would publish or index something it must not (AGENTS.md rule 11 and the Guardrails):
# game or generated binaries, mappings, secrets, oversized files, Unreal build folders, or a missing ignore rule.
# Checks tracked files, staged files and untracked-but-not-ignored files (what `git add .` would pick up).
# Run before every commit and before `gitnexus analyze`:  bash tools/check-repo-hygiene.sh
set -u
cd "$(git rev-parse --show-toplevel)" || exit 2

MAX_BYTES=$((2 * 1024 * 1024))
FORBIDDEN_EXT='pyc|uasset|uexp|ubulk|umap|usmap|jmap|pak|utoc|ucas|dll|exe|dmp|ushaderbytecode|uptnl|sqlite|db'
FORBIDDEN_DIR='(^|/)(Intermediate|Binaries|Saved|DerivedDataCache|\.vs|bin|obj)/|^unreal/[^/]+/Content/'
SECRET_RE='(SecurityToken|api[_-]?key|secret|password|token)[[:space:]]*[=:][[:space:]]*[A-Za-z0-9_\-]{16,}'

status=0
fail() { echo "FAIL: $1"; status=1; }

files=$( { git ls-files; git diff --cached --name-only; git ls-files --others --exclude-standard; } | sort -u )

while IFS= read -r f; do
    [ -f "$f" ] || continue
    ext="${f##*.}"
    if [[ "$ext" =~ ^($FORBIDDEN_EXT)$ ]]; then fail "forbidden extension: $f"; fi
    if [[ "$f" =~ $FORBIDDEN_DIR ]]; then fail "forbidden folder: $f"; fi
    size=$(stat -c %s "$f" 2>/dev/null || echo 0)
    if [ "$size" -gt "$MAX_BYTES" ]; then fail "larger than 2 MB ($size bytes): $f"; fi
    case "$ext" in
        md|lua|py|sh|ps1|cs|json|ini|txt|tsv|uplugin|uproject|csproj|cpp|h)
            if grep -I -n -i -E "$SECRET_RE" "$f" >/dev/null 2>&1; then fail "possible secret in: $f"; fi ;;
    esac
done <<< "$files"

for rule in 'unreal/**/Content/' 'unreal/**/Intermediate/' 'unreal/**/Binaries/' 'unreal/**/Saved/' '*.usmap' 'profiles/*.local.json'; do
    grep -qxF "$rule" .gitnexusignore 2>/dev/null || fail ".gitnexusignore is missing: $rule"
done

if [ "$status" -eq 0 ]; then echo "OK: no forbidden files, no oversized files, ignore rules present ($(echo "$files" | grep -c .) files checked)"; fi
exit "$status"
