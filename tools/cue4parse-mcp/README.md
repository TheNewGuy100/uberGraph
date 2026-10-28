# Generic CUE4Parse MCP

A Windows x64, stdio-based MCP server for inspecting Unreal Engine game archives through CUE4Parse. Game-specific values live in profiles; the server code does not hardcode a title, mount point, or UE minor version.

## Safety and initial scope

- Read-only access to configured game installations. The server does not modify source archives or game files.
- No automatic AES-key, `.usmap`, codec, or third-party binary downloads.
- No automatic AES-key or `.usmap` downloads. An explicitly configured local `mappingsPath` is loaded through CUE4Parse's `FileUsmapTypeMappingsProvider`; its file is never copied or modified. Encrypted packages remain unsupported without a separately reviewed, explicitly supplied key implementation.
- Container inventory reads directory metadata only. Mounting parses archive indexes/metadata; it does not extract assets.
- Asset export is intentionally not implemented in the first milestone.
- CUE4Parse covers many UE4/UE5 formats, not every customized or encrypted game build. A profile must select an explicit `EGame` value; the server never guesses a version.

## Build

Requires .NET 10 SDK and network access to restore pinned NuGet packages:

```powershell
dotnet restore .\cue4parse-mcp.csproj
dotnet build .\cue4parse-mcp.csproj -c Release
```

Dependencies are pinned in the project file. A direct `Microsoft.Bcl.Memory` reference fixes the vulnerable transitive version reported by the initial CUE4Parse restore. Run `dotnet list .\cue4parse-mcp.csproj package --vulnerable --include-transitive` when updating dependencies.

## Configure profiles

Copy `games.example.json` to `games.local.json`, then add one profile per game:

```json
{
  "profiles": [
    {
      "id": "my-game",
      "name": "My Unreal Game",
      "installRoot": "D:/Games/MyGame",
      "archivesPath": "D:/Games/MyGame/Game/Content/Paks",
      "engineVersion": "GAME_UE5_7",
      "mappingsPath": null,
      "recursiveArchiveSearch": false
    }
  ]
}
```

`engineVersion` must exactly match an `EGame` enum value in the pinned CUE4Parse package. Do not assume `GAME_UE5_LATEST` is correct for every UE5 game. If the version is unknown, leave it null: profile listing and container inventory still work, while mounting reports that a version must be identified. Paths and version should be checked independently for each profile.

Set the MCP config path with `--config <absolute-path>` or environment variable `CUE4PARSE_MCP_CONFIG`. No user-level OpenCode configuration is changed by building this project.

## MCP tools

- `list_game_profiles` — lists configured profiles without opening game files.
- `inventory_containers(profileId, limit)` — lists `.pak`, `.utoc`, `.ucas`, and `.sig` file names/sizes.
- `load_game_profile(profileId, reload)` - runs `Initialize()`, `Mount()`, then `PostMount()` via `DefaultFileProvider`; requires explicit UE `EGame` selection and reports required key GUIDs without attempting to retrieve keys.
- `diagnose_io_store(profileId)` - reports matching `.utoc`/`.ucas` files, selected TOC header/index fields, and results/exceptions from the three lifecycle stages. It does not export package payloads.
- `search_assets(profileId, query, limit, offset, pathPrefix, assetName, extension)` - case-insensitive AND search with bounded offset pagination and path/name/extension filters. It does not pretend to filter by class before class metadata has been parsed.
- `discover_subsystems(profileId, subsystemId, pathPrefix, offset, limit)` - exploratory, deterministic groups of package paths for energy, construction, inventory, AI, vehicles, and world. Defaults can be scoped with `pathPrefix=Voyage/Content/`; AI is matched as a token. Results are sorted by descending number of matched terms then path, and each group has its own pagination. It reads the persistent SQLite catalog's nominal path/name classifications and makes no class/property/behavior claims.
- `validate_asset_catalog(profileId)` - reports the per-user SQLite catalog and compares its case-insensitive package-path set, representative paginated search filters, and six subsystem groups to the current mounted provider. `search_assets` applies terms, filters, sorting and pagination in SQLite. `discover_subsystems` reads the separate nominal classification rows.

## Persistent catalog

The default database is `%LOCALAPPDATA%/VanillaPlus/CUE4Parse/catalogs/<profile-id>.sqlite`; it is outside the game installation and workspace. It stores provider-confirmed package paths, basename, extension, size, `IsUePackage` and `IsEncrypted`; physical container path/extension/size/UTC mtime; observed mounted-reader metadata; parser informational version, configured engine profile, and a SHA-256 fingerprint over install/archive roots, parser/engine versions, and the sorted container metadata manifest. The fingerprint deliberately does **not** hash container payload bytes; it is suitable for ordinary metadata-change invalidation, not proof of content integrity.

`asset_nominal_classifications` is separate and labeled `path_name_heuristic`; it contains only the current exploratory subsystem term taxonomy. Per-asset inspection status and `analysis_history` record bounded operations, exceptions, mapping path/hash when configured, and the catalog fingerprint. Individual package-to-container association remains NULL because the current CUE4Parse file index does not expose a verified relation in this tool. No asset payloads are stored.
- `inspect_asset(profileId, packagePath, load, parseExports, maxExports, maxProperties)` - bounded on-demand package/export/property inspection. Statuses distinguish `indexed`, `loaded`, `parsed`, `partially_parsed`, and `failed`; exceptions preserve `Exception.ToString()` including stack traces. It never writes or exports raw package payloads.
- `validate_mappings(profileId, mappingPath, mappingSource, mappingBuildId, targetBuildId, targetExecutablePath, requiredClassNames, runSampleTests)` - validates only an explicitly supplied local `.usmap`, reports its SHA-256, size, CUE4Parse type-table coverage and executable hash when found. Provenance/build fields are recorded as caller claims, not independently verified. Four sample parse attempts are disabled unless `runSampleTests=true`; this tool never discovers or downloads candidate mappings.

## Independent external dependency resolution

`../resolve_external_dependencies.py` (v1.0.1) resolves `/Game/...` package imports in an `inspect_legacy_exports` JSON report against the existing SQLite metadata catalog. It is an independent Python standard-library script, not an MCP tool and not part of the legacy reader. It opens SQLite with URI `mode=ro` and `PRAGMA query_only=ON`, performs exact case-insensitive `path_key` lookups, and never opens asset payloads.

For this game's catalog, normalization is `/Game/<relative>` → `Voyage/Content/<relative>` with exact `.uasset` and `.umap` candidates. `package_found` means one exact catalog row; `package_not_found` is limited to that catalog snapshot; multiple exact candidates are `ambiguous`; malformed `/Game/...` references are returned separately as `reference_unresolved`. All found/not-found/ambiguous rows leave `object_status=not_verified` and `load_status=not_tested`. `/Script/...` imports are preserved in `excluded_non_game_references`, not looked up as game packages. Invocation:

```powershell
python .\tools\resolve_external_dependencies.py <inspect-legacy-exports.json> `
  --catalog "$env:LOCALAPPDATA\VanillaPlus\CUE4Parse\catalogs\the-last-caretaker.sqlite" `
  --output <dependency-resolution.json>
```

The report preserves the original `/Game/...` package reference, normalized candidates, matching rows, and import objects whose outer points at the referenced package. It does not assert that an indexed package contains the referenced object, can load, matches the game's engine version, or is compatible.

## Current local profile

The ignored `games.local.json` contains the The Last Caretaker installation path for local testing. Its UE minor version remains unset; normal profile loading stays blocked until an explicit version is configured. `diagnose_io_store` may be used with an explicitly temporary exploratory enum, with results treated as compatibility evidence rather than exact-version proof. Package inspection may also require a local `.usmap`; configure its exact file path in `mappingsPath` only after independently validating its provenance/build compatibility. No mapping file was found in the searched game/workspace locations; FModel was also included in the earlier local-only scan. Other game profiles can be added without changing code.

