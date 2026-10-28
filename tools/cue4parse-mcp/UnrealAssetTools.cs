using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using CUE4Parse.UE4.Assets;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Versions;
using ModelContextProtocol.Server;
using Serilog;
using Serilog.Core;
using Serilog.Events;

[McpServerToolType]
public static class UnrealAssetTools
{
    private static readonly object ProviderLock = new();
    private static readonly object CueLoggerLock = new();
    private static readonly Dictionary<string, DefaultFileProvider> Providers = new(StringComparer.OrdinalIgnoreCase);
    private static readonly Dictionary<string, AssetCatalog> Catalogs = new(StringComparer.OrdinalIgnoreCase);
    private static readonly JsonSerializerOptions OutputJson = new() { WriteIndented = true };
    private static readonly IReadOnlyDictionary<string, string[]> SubsystemSearchTerms = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
    {
        ["energy"] = new[] { "Power", "Energy", "Generator", "Battery" },
        ["construction"] = new[] { "Build", "Structure", "Foundation" },
        ["inventory"] = new[] { "Inventory", "Item", "Storage" },
        ["ai"] = new[] { "AI", "Behavior", "NPC" },
        ["vehicles"] = new[] { "Vehicle", "Engine", "Wheel" },
        ["world"] = new[] { "World", "Biome", "Weather" }
    };

    private sealed class CueLogSink : ILogEventSink
    {
        private readonly System.Collections.Concurrent.ConcurrentQueue<object> _events = new();
        public int Count => _events.Count;
        public object[] Snapshot(int limit = 100) => _events.Take(limit).ToArray();

        public void Emit(LogEvent logEvent)
        {
            _events.Enqueue(new
            {
                timestamp = logEvent.Timestamp,
                level = logEvent.Level.ToString(),
                message = logEvent.RenderMessage(),
                exception = logEvent.Exception?.ToString()
            });
        }
    }

    private sealed class CueLogScope : IDisposable
    {
        private readonly Serilog.ILogger _previous;
        private readonly Serilog.ILogger _captureLogger;
        private bool _disposed;
        public CueLogSink Sink { get; }

        public CueLogScope(Serilog.ILogger previous, Serilog.ILogger captureLogger, CueLogSink sink)
        {
            _previous = previous;
            _captureLogger = captureLogger;
            Sink = sink;
        }

        public void Dispose()
        {
            if (_disposed) return;
            CUE4Parse.CUE4ParseLog.UseLogger(_previous);
            (_captureLogger as IDisposable)?.Dispose();
            _disposed = true;
            System.Threading.Monitor.Exit(CueLoggerLock);
        }
    }

    private static CueLogScope CaptureCueLogs()
    {
        System.Threading.Monitor.Enter(CueLoggerLock);
        try
        {
            var previous = CUE4Parse.CUE4ParseLog.Log;
            var sink = new CueLogSink();
            var logger = new LoggerConfiguration()
                .MinimumLevel.Verbose()
                .WriteTo.Sink(sink)
                .CreateLogger();
            CUE4Parse.CUE4ParseLog.UseLogger(logger);
            return new CueLogScope(previous, logger, sink);
        }
        catch
        {
            System.Threading.Monitor.Exit(CueLoggerLock);
            throw;
        }
    }

    [McpServerTool, Description("List configured Unreal Engine game profiles. Does not scan or open game files.")]
    public static object ListGameProfiles()
    {
        return new
        {
            configFile = McpRuntime.Profiles.ConfigPath,
            profiles = McpRuntime.Profiles.Profiles.OrderBy(p => p.Id).Select(p => new
            {
                p.Id,
                p.Name,
                p.InstallRoot,
                p.ArchivesPath,
                engineVersion = p.EngineVersion ?? "not configured",
                p.MappingsPath,
                p.RecursiveArchiveSearch
            })
        };
    }

    [McpServerTool, Description("Inventory .pak, .utoc, .ucas and .sig container filenames and sizes for a configured game profile. Reads directory metadata only; does not read large container contents.")]
    public static object InventoryContainers(
        [Description("Configured profile id returned by list_game_profiles.")] string profileId,
        [Description("Maximum number of file records to return (1-10000). Defaults to 1000.")] int limit = 1000)
    {
        if (limit is < 1 or > 10000) throw new ArgumentOutOfRangeException(nameof(limit), "limit must be between 1 and 10000.");
        var profile = McpRuntime.Profiles.GetRequired(profileId);
        var root = Path.GetFullPath(profile.ArchivesPath);
        if (!Directory.Exists(root))
            return new { profileId, archivesPath = root, status = "directory-not-found", containers = Array.Empty<object>() };

        var searchOption = profile.RecursiveArchiveSearch ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly;
        var files = Directory.EnumerateFiles(root, "*", searchOption)
            .Where(path => Path.GetExtension(path).ToLowerInvariant() is ".pak" or ".utoc" or ".ucas" or ".sig")
            .Select(path => new FileInfo(path))
            .OrderBy(info => info.Name, StringComparer.OrdinalIgnoreCase)
            .Take(limit + 1)
            .ToArray();

        var hasMore = files.Length > limit;
        var selected = files.Take(limit).Select(info => new
        {
            name = info.Name,
            extension = info.Extension,
            sizeBytes = info.Length,
            lastWriteUtc = info.LastWriteTimeUtc
        }).ToArray();

        return new
        {
            profileId,
            archivesPath = root,
            status = "ok",
            recursive = profile.RecursiveArchiveSearch,
            countReturned = selected.Length,
            hasMore,
            containers = selected
        };
    }

    [McpServerTool, Description("Mount a configured game's Unreal containers through CUE4Parse. Requires an explicit CUE4Parse EGame engineVersion in the profile. This reads container indexes/metadata but never writes to the game installation.")]
    public static object LoadGameProfile(
        [Description("Configured profile id returned by list_game_profiles.")] string profileId,
        [Description("Force rebuilding the CUE4Parse provider if this profile is already loaded.")] bool reload = false)
    {
        var profile = McpRuntime.Profiles.GetRequired(profileId);
        if (!Enum.TryParse<EGame>(profile.EngineVersion, ignoreCase: true, out var gameVersion))
            return new { profileId, status = "engine-version-required", message = "Set engineVersion to an exact CUE4Parse EGame enum value in the profile before mounting. No version is guessed." };

        if (!Directory.Exists(profile.ArchivesPath))
            return new { profileId, status = "directory-not-found", archivesPath = Path.GetFullPath(profile.ArchivesPath) };

        lock (ProviderLock)
        {
            if (Providers.TryGetValue(profileId, out var existing) && !reload)
                return MountSummary(profile, existing, "already-loaded");

            if (Providers.Remove(profileId, out var previous)) previous.Dispose();
            var provider = new DefaultFileProvider(
                Path.GetFullPath(profile.ArchivesPath),
                profile.RecursiveArchiveSearch ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly,
                new VersionContainer(gameVersion),
                StringComparer.OrdinalIgnoreCase);

            var stage = "mapping_configuration";
            try
            {
                ConfigureMappings(provider, profile);
                stage = "initialize";
                provider.Initialize();
                stage = "mount";
                var mountedNow = provider.Mount();
                stage = "post_mount";
                provider.PostMount();
                Providers[profileId] = provider;
                var catalog = Catalogs.TryGetValue(profileId, out var existingCatalog) ? existingCatalog : new AssetCatalog(profile);
                Catalogs[profileId] = catalog;
                var catalogSync = catalog.Sync(provider, profile.RecursiveArchiveSearch);
                var mountSummary = MountSummary(profile, provider, $"loaded; mountedNow={mountedNow}; PostMount=completed");
                return new
                {
                    profileId,
                    providerStatus = $"loaded; mountedNow={mountedNow}; PostMount=completed",
                    mountStatus = ReadMember(mountSummary, "mountStatus"),
                    engineVersion = ReadMember(mountSummary, "engineVersion"),
                    indexedFileCount = ReadMember(mountSummary, "indexedFileCount"),
                    indexedPackageCount = ReadMember(mountSummary, "indexedPackageCount"),
                    mountedContainerCount = ReadMember(mountSummary, "mountedContainerCount"),
                    unmountedContainerCount = ReadMember(mountSummary, "unmountedContainerCount"),
                    mountedContainers = ReadMember(mountSummary, "mountedContainers"),
                    unmountedContainers = ReadMember(mountSummary, "unmountedContainers"),
                    requiredKeyGuids = ReadMember(mountSummary, "requiredKeyGuids"),
                    keysMustBeSuppliedExplicitly = ReadMember(mountSummary, "keysMustBeSuppliedExplicitly"),
                    catalog = catalogSync
                };
            }
            catch (Exception ex)
            {
                provider.Dispose();
                return new
                {
                    profileId,
                    status = "failed",
                    stage,
                    exceptionType = ex.GetType().FullName,
                    exception = ex.ToString()
                };
            }
        }
    }

    [McpServerTool, Description("Read IoStore TOC/header metadata for a configured profile, verify matching UCAS files, then run Initialize, Mount, and PostMount. Does not export package payloads or access encryption keys. Exception text includes full ToString() stack traces where an exception escapes CUE4Parse.")]
    public static object DiagnoseIoStore(
        [Description("Configured profile id returned by list_game_profiles.")] string profileId)
    {
        var profile = McpRuntime.Profiles.GetRequired(profileId);
        if (!Enum.TryParse<EGame>(profile.EngineVersion, ignoreCase: true, out var gameVersion))
            return new { profileId, status = "engine-version-required", message = "Set an exploratory or verified CUE4Parse EGame value in the profile. No version is guessed." };
        var root = Path.GetFullPath(profile.ArchivesPath);
        if (!Directory.Exists(root))
            return new { profileId, status = "directory-not-found", archivesPath = root };

        var tocFiles = Directory.EnumerateFiles(root, "*.utoc", profile.RecursiveArchiveSearch ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly)
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToArray();
        var pairs = tocFiles.Select(tocPath =>
        {
            var ucasPath = Path.ChangeExtension(tocPath, ".ucas");
            var tocInfo = new FileInfo(tocPath);
            var ucasInfo = File.Exists(ucasPath) ? new FileInfo(ucasPath) : null;
            return new { tocPath, tocBytes = tocInfo.Length, ucasPath, ucasExists = ucasInfo is not null, ucasBytes = ucasInfo?.Length };
        }).ToArray();

        using var cueLogCapture = CaptureCueLogs();
        using var provider = new DefaultFileProvider(root,
            profile.RecursiveArchiveSearch ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly,
            new VersionContainer(gameVersion), StringComparer.OrdinalIgnoreCase);
        ConfigureMappings(provider, profile);
        string? initializeException = null;
        string? mountException = null;
        string? postMountException = null;
        var initializeCompleted = false;
        var mountCompleted = false;
        var postMountCompleted = false;
        var mountedNow = 0;
        try { provider.Initialize(); initializeCompleted = true; }
        catch (Exception ex) { initializeException = ex.ToString(); }

        var beforeMount = ReadIoStoreReaders(provider);
        try { mountedNow = provider.Mount(); mountCompleted = true; }
        catch (Exception ex) { mountException = ex.ToString(); }
        try { provider.PostMount(); postMountCompleted = true; }
        catch (Exception ex) { postMountException = ex.ToString(); }
        var afterMount = ReadIoStoreReaders(provider);

        return new
        {
            profileId,
            archivesPath = root,
            engineVersion = gameVersion.ToString(),
            pairCount = pairs.Length,
            pairs,
            initializeCompleted,
            initializeException,
            registeredVfsCount = provider.UnloadedVfs.Count + provider.MountedVfs.Count,
            beforeMount,
            mountCompleted,
            mountedNow,
            mountException,
            postMountCompleted,
            postMountException,
            afterMount,
            indexedFileCount = provider.Files.Count,
            indexedPackageCount = provider.Files.Values.Count(file => file.IsUePackage),
            requiredKeyGuids = provider.RequiredKeys.Select(guid => guid.ToString()).ToArray(),
            cue4parseLogEventCount = cueLogCapture.Sink.Count,
            cue4parseLogEvents = cueLogCapture.Sink.Snapshot(),
            caveat = "CUE4Parse may catch reader-registration and per-container mount exceptions internally; scoped Serilog capture returns emitted events, including exception.ToString() when present. Escaping exceptions are reported separately with full ToString()."
        };
    }

    private static object[] ReadIoStoreReaders(DefaultFileProvider provider)
    {
        var readers = provider.UnloadedVfs.Concat(provider.MountedVfs)
            .Where(reader => reader.GetType().Name == "IoStoreReader")
            .Distinct()
            .OrderBy(reader => reader.Name, StringComparer.OrdinalIgnoreCase);

        return readers.Select(reader =>
        {
            var tocResource = ReadField(reader, "TocResource");
            var header = tocResource is null ? null : ReadField(tocResource, "Header");
            return (object)new
            {
                name = reader.Name,
                readerPath = reader.Path,
                isMounted = provider.MountedVfs.Contains(reader),
                isEncrypted = reader.IsEncrypted,
                hasDirectoryIndex = reader.HasDirectoryIndex,
                mountPoint = reader.MountPoint,
                encryptionKeyGuid = reader.EncryptionKeyGuid.ToString(),
                tocVersion = ReadMember(header, "Version"),
                containerFlags = ReadMember(header, "ContainerFlags"),
                tocChunkCount = ReadMember(header, "TocEntryCount"),
                directoryIndexSizeBytes = ReadMember(header, "DirectoryIndexSize"),
                tocHeaderSizeBytes = ReadMember(header, "TocHeaderSize"),
                compressionBlockCount = ReadMember(header, "TocCompressedBlockEntryCount"),
                partitionCount = ReadMember(header, "PartitionCount"),
                containerId = ReadMember(header, "ContainerId"),
                metadataException = header is null ? "CUE4Parse did not expose TocResource.Header for this reader." : null
            };
        }).ToArray();
    }

    private static object? ReadField(object target, string name)
    {
        try { return target.GetType().GetField(name, System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)?.GetValue(target); }
        catch { return null; }
    }

    private static object? ReadMember(object? target, string name)
    {
        if (target is null) return null;
        try
        {
            var type = target.GetType();
            return type.GetProperty(name, System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)?.GetValue(target)
                ?? type.GetField(name, System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)?.GetValue(target);
        }
        catch (Exception ex) { return $"metadata-read-error: {ex}"; }
    }

    [McpServerTool, Description("Search the local SQLite catalog synchronized from mounted CUE4Parse package paths, with case-insensitive name/path terms and optional path/name/extension filters. Results are bounded and paginated; class filtering is not claimed because it requires parsing package exports.")]
    public static object SearchAssets(
        [Description("Configured profile id that has been loaded with load_game_profile.")] string profileId,
        [Description("One or more terms to find in asset paths.")] string query,
        [Description("Maximum number of results per page (1-200). Defaults to 50.")] int limit = 50,
        [Description("Zero-based result offset for pagination.")] int offset = 0,
        [Description("Optional package path prefix, for example Voyage/Content/Blueprints/.")] string? pathPrefix = null,
        [Description("Optional asset basename substring, without requiring an extension.")] string? assetName = null,
        [Description("Optional extension filter, such as .uasset or .umap.")] string? extension = null)
    {
        if (limit is < 1 or > 200) throw new ArgumentOutOfRangeException(nameof(limit), "limit must be between 1 and 200.");
        if (offset < 0) throw new ArgumentOutOfRangeException(nameof(offset), "offset cannot be negative.");
        if (string.IsNullOrWhiteSpace(query)) throw new ArgumentException("query cannot be empty.", nameof(query));
        _ = GetProvider(profileId);
        var terms = query.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var normalizedPrefix = string.IsNullOrWhiteSpace(pathPrefix) ? null : pathPrefix.Replace('\\', '/').TrimStart('/');
        var normalizedExtension = string.IsNullOrWhiteSpace(extension) ? null : extension.StartsWith('.') ? extension : $".{extension}";
        var catalog = GetCatalog(profileId);
        var page = catalog.SearchPackages(terms, normalizedPrefix, assetName, normalizedExtension, offset, limit + 1);
        var matches = page.Results;
        return new
        {
            profileId,
            query,
            pathPrefix = normalizedPrefix,
            assetName,
            extension = normalizedExtension,
            offset,
            pageSize = limit,
            totalMatches = page.TotalCount,
            countReturned = Math.Min(matches.Count, limit),
            hasMore = matches.Count > limit,
            nextOffset = matches.Count > limit ? offset + limit : (int?)null,
            results = matches.Take(limit).Select(file => new { path = file.Path, sizeBytes = file.SizeBytes, isEncrypted = file.IsEncrypted })
        };
    }

    [McpServerTool, Description("Discover candidate asset packages by exploratory path/name terms. Results are deterministically paginated per subsystem, sorted by descending matched-term count then path, and explicitly do not establish decoded classes, properties, or behavior. Uses the local SQLite catalog synchronized from the mounted provider; nominal classifications remain separate from confirmed metadata.")]
    public static object DiscoverSubsystems(
        [Description("Configured profile id that has been loaded with load_game_profile.")] string profileId,
        [Description("Optional subsystem id: energy, construction, inventory, ai, vehicles, world. Omit to return one page for each group.")] string? subsystemId = null,
        [Description("Optional package path prefix. For this game use Voyage/Content/ to exclude Engine/Content candidates.")] string? pathPrefix = null,
        [Description("Zero-based result offset, applied independently to each selected group.")] int offset = 0,
        [Description("Maximum candidate paths per group (1-50). Defaults to 20.")] int limit = 20)
    {
        if (offset < 0) throw new ArgumentOutOfRangeException(nameof(offset), "offset cannot be negative.");
        if (limit is < 1 or > 50) throw new ArgumentOutOfRangeException(nameof(limit), "limit must be between 1 and 50.");
        if (subsystemId is not null && !SubsystemSearchTerms.ContainsKey(subsystemId))
            throw new ArgumentException($"Unknown subsystem '{subsystemId}'. Supported ids: {string.Join(", ", SubsystemSearchTerms.Keys)}.", nameof(subsystemId));

        _ = GetProvider(profileId);
        var catalog = GetCatalog(profileId);
        var normalizedPrefix = string.IsNullOrWhiteSpace(pathPrefix) ? null : pathPrefix.Replace('\\', '/').TrimStart('/');
        var groups = string.IsNullOrWhiteSpace(subsystemId)
            ? SubsystemSearchTerms
            : new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase) { [subsystemId] = SubsystemSearchTerms[subsystemId] };
        var results = groups.OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase).Select(pair =>
        {
            var candidates = catalog.ReadSubsystemCandidates(pair.Key, normalizedPrefix);
            var page = candidates.Skip(offset).Take(limit + 1).ToArray();
            var hasMore = page.Length > limit;
            return new
            {
                subsystemId = pair.Key,
                queryTerms = pair.Value,
                totalCandidatePackages = candidates.Count,
                offset,
                pageSize = limit,
                countReturned = Math.Min(page.Length, limit),
                hasMore,
                nextOffset = hasMore ? offset + limit : (int?)null,
                candidates = page.Take(limit).Select(candidate => new
                {
                    path = candidate.Path,
                    sizeBytes = candidate.SizeBytes,
                    matchedTerms = candidate.MatchedTerms
                }).ToArray()
            };
        }).ToArray();

        return new
        {
            profileId,
            status = "candidate_paths_only",
            pathPrefix = normalizedPrefix,
            indexSource = "local SQLite catalog synchronized from the mounted CUE4Parse provider",
            persistentIndexAvailable = true,
            indexedPackageCount = ReadMember(catalog.GetSummary(), "packageCount"),
            groups = results,
            caveat = "Term and path matches are exploratory candidates only. They do not prove asset classes, serialized properties, dependencies, or subsystem behavior."
        };
    }

    [McpServerTool, Description("Summarize the local persistent SQLite asset catalog and compare its ordered package paths with the currently mounted CUE4Parse in-memory index. Reports the container metadata fingerprint and whether index equivalence holds.")]
    public static object ValidateAssetCatalog(
        [Description("Configured profile id that has been loaded with load_game_profile.")] string profileId)
    {
        var provider = GetProvider(profileId);
        var catalog = GetCatalog(profileId);
        return new
        {
            catalog = catalog.GetSummary(),
            packagePathComparison = catalog.CompareToProvider(provider),
            searchQueryComparison = catalog.CompareQueries(provider),
            subsystemQueryComparison = catalog.CompareSubsystemQueries(provider)
        };
    }

    private static bool MatchesSubsystemTerm(string path, string term)
    {
        if (term.Equals("AI", StringComparison.OrdinalIgnoreCase))
            return Regex.IsMatch(path, @"(?<![\p{L}\p{N}])AI(?![\p{L}\p{N}])", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        return path.Contains(term, StringComparison.OrdinalIgnoreCase);
    }

    [McpServerTool, Description("Inspect one indexed Unreal package on demand. It can return index-only status, package-loaded status, or bounded export/property parsing. Every reported class, superclass, property, and reference comes from a successful CUE4Parse read; exceptions include ToString() stack traces.")]
    public static object InspectAsset(
        [Description("Configured profile id that has been loaded with load_game_profile.")] string profileId,
        [Description("Canonical package path returned by search_assets.")] string packagePath,
        [Description("Load package summary and exports. False returns indexed metadata only. Defaults to true.")] bool load = true,
        [Description("Deserialize exports and properties after loading the package. False returns status=loaded. Defaults to true.")] bool parseExports = true,
        [Description("Maximum exports to deserialize (1-40). Defaults to 12.")] int maxExports = 12,
        [Description("Maximum properties to return per export (1-100). Defaults to 40.")] int maxProperties = 40)
    {
        if (maxExports is < 1 or > 40) throw new ArgumentOutOfRangeException(nameof(maxExports), "maxExports must be between 1 and 40.");
        if (maxProperties is < 1 or > 100) throw new ArgumentOutOfRangeException(nameof(maxProperties), "maxProperties must be between 1 and 100.");
        if (string.IsNullOrWhiteSpace(packagePath) || packagePath.IndexOf('\0') >= 0)
            throw new ArgumentException("packagePath must be a non-empty package path.", nameof(packagePath));
        var provider = GetProvider(profileId);
        var mappingPath = McpRuntime.Profiles.GetRequired(profileId).MappingsPath;
        if (!provider.TryGetGameFile(packagePath, out var gameFile))
        {
            GetCatalog(profileId).RecordAnalysis(packagePath, "failed", "lookup", "FileNotFound", "Package path was not found in the mounted file index.", mappingPath);
            return new { profileId, path = packagePath, status = "failed", stage = "lookup", error = "Package path was not found in the mounted file index." };
        }

        var indexed = new { path = gameFile.Path, sizeBytes = gameFile.Size, isEncrypted = gameFile.IsEncrypted };
        if (!load)
        {
            GetCatalog(profileId).RecordAnalysis(gameFile.Path, "indexed", "index", null, null, mappingPath);
            return new { profileId, asset = indexed, status = "indexed", stage = "index" };
        }

        using var cueLogCapture = CaptureCueLogs();
        IPackage package;
        try
        {
            package = provider.LoadPackage(gameFile);
        }
        catch (Exception ex)
        {
            GetCatalog(profileId).RecordAnalysis(gameFile.Path, "failed", "package_load", ex.GetType().FullName, ex.ToString(), mappingPath);
            return new { profileId, asset = indexed, status = "failed", stage = "package_load", exceptionType = ex.GetType().FullName, exception = ex.ToString(), cue4parseLogEventCount = cueLogCapture.Sink.Count, cue4parseLogEvents = cueLogCapture.Sink.Snapshot() };
        }

        var packageSummary = new
        {
            packageName = package.Name,
            packageCanDeserialize = package.CanDeserialize,
            packageFullyLoaded = package.IsFullyLoaded,
            packageExportCount = package.ExportMapLength,
            packageImportCount = package.ImportMapLength,
            nameMapCount = package.NameMap.Length,
            mappingsAvailable = package.Mappings is not null
        };
        if (!parseExports)
        {
            GetCatalog(profileId).RecordAnalysis(gameFile.Path, "loaded", "package", null, null, mappingPath);
            return new { profileId, path = gameFile.Path, status = "loaded", stage = "package", assetClass = (string?)null, superClass = (string?)null, package = packageSummary, properties = Array.Empty<object>(), references = Array.Empty<object>(), cue4parseLogEventCount = cueLogCapture.Sink.Count, cue4parseLogEvents = cueLogCapture.Sink.Snapshot() };
        }

        var exports = new List<object>();
        var references = new List<object>();
        var propertyErrors = new List<object>();
        var failedExports = new List<object>();
        var exportsLazy = package.ExportsLazy;
        var attempted = Math.Min(exportsLazy.Length, maxExports);
        for (var i = 0; i < attempted; i++)
        {
            try
            {
                var value = exportsLazy[i].Value;
                var exportProperties = new List<object>();
                var tags = value.Properties;
                foreach (var property in tags.Take(maxProperties))
                {
                    try
                    {
                        var rawValue = property.Tag?.GenericValue;
                        exportProperties.Add(new
                        {
                            name = property.Name.ToString(),
                            type = property.PropertyType.ToString(),
                            value = ProjectValue(rawValue, 0, references)
                        });
                    }
                    catch (Exception ex)
                    {
                        propertyErrors.Add(new { exportName = value.Name, propertyName = property.Name.ToString(), exception = ex.ToString() });
                    }
                }
                exports.Add(new
                {
                    name = value.Name,
                    assetClass = value.Class?.GetFullName() ?? value.ExportType,
                    superClass = value.Super?.GetFullName(),
                    propertiesReturned = exportProperties.Count,
                    propertiesTruncated = tags.Count > maxProperties,
                    properties = exportProperties
                });
            }
            catch (Exception ex)
            {
                failedExports.Add(new { exportIndex = i, exceptionType = ex.GetType().FullName, exception = ex.ToString() });
            }
        }

        var exportsTruncated = exportsLazy.Length > maxExports;
        var partiallyParsed = failedExports.Count > 0 || propertyErrors.Count > 0 || exportsTruncated || exports.Any(item => (bool)item.GetType().GetProperty("propertiesTruncated")!.GetValue(item)!);
        var status = partiallyParsed ? "partially_parsed" : "parsed";
        var firstExport = exports.FirstOrDefault();

        var result = new
        {
            profileId,
            path = gameFile.Path,
            status,
            stage = "exports_and_properties",
            assetClass = firstExport?.GetType().GetProperty("assetClass")?.GetValue(firstExport),
            superClass = firstExport?.GetType().GetProperty("superClass")?.GetValue(firstExport),
            package = packageSummary,
            exportsAttempted = attempted,
            exportsReturned = exports.Count,
            exportsTruncated,
            failedExports,
            propertyErrors,
            properties = exports,
            references = references.DistinctBy(item => JsonSerializer.Serialize(item)).Take(200).ToArray(),
            cue4parseLogEventCount = cueLogCapture.Sink.Count,
            cue4parseLogEvents = cueLogCapture.Sink.Snapshot(),
            warnings = new[] { "Status describes the bounded operation requested; truncated exports/properties are reported as partially_parsed, not parsed." }
        };
        var partialError = status == "partially_parsed" ? JsonSerializer.Serialize(new { failedExports, propertyErrors }) : null;
        GetCatalog(profileId).RecordAnalysis(gameFile.Path, status, "exports_and_properties", partialError is null ? null : "PartialParse", partialError, mappingPath);
        return result;
    }

    [McpServerTool, Description("Validate an explicitly supplied local .usmap without downloading or selecting mappings automatically. Reports file integrity/hash, CUE4Parse structural-load result, declared (not independently proven) provenance/build claims, mapping class coverage, and optionally bounded tests of four previously selected packages. Sample deserialization is opt-in and does not export raw assets.")]
    public static object ValidateMappings(
        [Description("Configured profile id returned by list_game_profiles. The profile must already be mounted.")] string profileId,
        [Description("Explicit local .usmap path. No discovery or download is performed by this tool.")] string? mappingPath = null,
        [Description("User-provided provenance/source description, such as an official release record. This is recorded as a claim, not verified automatically.")] string? mappingSource = null,
        [Description("Build identifier claimed for the mapping, if known.")] string? mappingBuildId = null,
        [Description("Target game build identifier to compare against, for example Steam build 25191271.")] string? targetBuildId = null,
        [Description("Optional executable path to hash. Defaults to the known The Last Caretaker Shipping executable path under InstallRoot when present.")] string? targetExecutablePath = null,
        [Description("Optional exact class/type names to check in this mapping's class table.")] string[]? requiredClassNames = null,
        [Description("Run bounded deserialization attempts for the four documented sample packages. Defaults to false; must be explicitly enabled for any candidate mapping.")] bool runSampleTests = false)
    {
        var profile = McpRuntime.Profiles.GetRequired(profileId);
        if (string.IsNullOrWhiteSpace(mappingPath))
            return new { profileId, status = "blocked_no_mapping_path", message = "Supply an explicit local .usmap path. No local .usmap was discovered in the previously searched game/workspace locations; this tool does not search or download mappings." };

        var fullMappingPath = Path.GetFullPath(mappingPath);
        if (!File.Exists(fullMappingPath))
            return new { profileId, mappingPath = fullMappingPath, status = "failed", stage = "mapping_file", errorCategory = "mapping_file_missing", error = "The explicitly configured local mapping file does not exist." };

        var mappingInfo = new FileInfo(fullMappingPath);
        string mappingSha256;
        using (var stream = File.OpenRead(fullMappingPath))
            mappingSha256 = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();

        string? resolvedExecutable = targetExecutablePath;
        if (string.IsNullOrWhiteSpace(resolvedExecutable))
        {
            var candidate = Path.Combine(profile.InstallRoot, "Voyage", "Binaries", "Win64", "VoyageSteam-Win64-Shipping.exe");
            if (File.Exists(candidate)) resolvedExecutable = candidate;
        }
        var executableExists = !string.IsNullOrWhiteSpace(resolvedExecutable) && File.Exists(resolvedExecutable);
        var executableHash = executableExists ? ComputeSha256(resolvedExecutable!) : null;

        var provenanceComplete = !string.IsNullOrWhiteSpace(mappingSource)
            && !string.IsNullOrWhiteSpace(mappingBuildId)
            && !string.IsNullOrWhiteSpace(targetBuildId);
        var buildClaimMatches = provenanceComplete && string.Equals(mappingBuildId!.Trim(), targetBuildId!.Trim(), StringComparison.OrdinalIgnoreCase);
        var provider = GetProvider(profileId);
        var requiredClasses = (requiredClassNames ?? Array.Empty<string>()).Where(name => !string.IsNullOrWhiteSpace(name)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();

        using var cueLogCapture = CaptureCueLogs();
        CUE4Parse.MappingsProvider.Usmap.FileUsmapTypeMappingsProvider candidateMappings;
        try
        {
            candidateMappings = new FileUsmapTypeMappingsProvider(fullMappingPath, StringComparer.OrdinalIgnoreCase);
        }
        catch (Exception ex)
        {
            return new
            {
                profileId,
                mapping = new { path = fullMappingPath, sizeBytes = mappingInfo.Length, sha256 = mappingSha256 },
                status = "failed",
                stage = "mapping_structure",
                errorCategory = "invalid_or_unreadable_mapping",
                exceptionType = ex.GetType().FullName,
                exception = ex.ToString(),
                provenance = new { source = mappingSource, mappingBuildId, targetBuildId, assessment = "declared_not_independently_verified" },
                targetExecutable = new { path = resolvedExecutable, exists = executableExists, sha256 = executableHash },
                cue4parseLogEventCount = cueLogCapture.Sink.Count,
                cue4parseLogEvents = cueLogCapture.Sink.Snapshot()
            };
        }

        var typeMappings = candidateMappings.MappingsForGame
            ?? throw new InvalidDataException("CUE4Parse constructed a mapping provider but did not expose a type table.");
        var typeNames = typeMappings.Types.Keys.OrderBy(name => name, StringComparer.OrdinalIgnoreCase).ToArray();
        var presentRequiredClasses = requiredClasses.Where(name => typeMappings.Types.Keys.Contains(name, StringComparer.OrdinalIgnoreCase)).ToArray();
        var missingRequiredClasses = requiredClasses.Except(presentRequiredClasses, StringComparer.OrdinalIgnoreCase).ToArray();
        object[]? sampleTests = null;
        var sampleTestStatus = "not-run-explicit-opt-in-required";
        if (runSampleTests)
        {
            lock (ProviderLock)
            {
                var originalMappings = provider.MappingsContainer;
                provider.MappingsContainer = candidateMappings;
                try
                {
                    var samplePaths = new[]
                    {
                        "Voyage/Content/Animations/Notify/BP_Dropped_Magazine.uasset",
                        "Voyage/Content/Blueprints/Subsystems/DA_WorldSpawnData.uasset",
                        "Voyage/Content/Data/GameProgress/DT_VoyageCharacterLevels.uasset",
                        "Voyage/Content/AdvancedGlassPack/Materials/05_Wet/M_Glass_WetMaster.uasset"
                    };
                    sampleTests = samplePaths.Select(path => (object)SummarizeMappingTest(path, InspectAsset(profileId, path, load: true, parseExports: true, maxExports: 12, maxProperties: 40))).ToArray();
                    sampleTestStatus = sampleTests.All(item => (string)item.GetType().GetProperty("status")!.GetValue(item)! is "parsed")
                        ? "all-samples-parsed"
                        : "one-or-more-samples-not-fully-parsed";
                }
                finally
                {
                    provider.MappingsContainer = originalMappings;
                }
            }
        }

        var allRequestedClassesPresent = requiredClasses.Length == 0 || missingRequiredClasses.Length == 0;
        var buildClaimStatus = !provenanceComplete ? "unknown" : buildClaimMatches ? "claimed-match" : "claimed-mismatch";
        var status = buildClaimStatus == "claimed-mismatch" ? "declared-build-mismatch"
            : !allRequestedClassesPresent ? "class-coverage-incomplete"
            : runSampleTests && sampleTestStatus == "all-samples-parsed" && provenanceComplete && buildClaimMatches
                ? "candidate-passes-configured-checks-but-compatibility-unverified"
            : runSampleTests ? "sample-tests-inconclusive-or-failed"
            : "structurally-readable-compatibility-unverified";

        return new
        {
            profileId,
            mapping = new { path = fullMappingPath, sizeBytes = mappingInfo.Length, lastWriteUtc = mappingInfo.LastWriteTimeUtc, sha256 = mappingSha256, structuralLoad = "passed", mappedTypeCount = typeNames.Length, typeNameSample = typeNames.Take(80).ToArray(), typeNamesTruncated = typeNames.Length > 80 },
            provenance = new
            {
                source = mappingSource,
                mappingBuildId,
                targetBuildId,
                detailsProvided = provenanceComplete,
                buildClaimMatches,
                buildClaimStatus,
                assessment = "declared_not_independently_verified",
                compatibility = buildClaimMatches ? "claimed-build-match; exact UE minor and mapping provenance remain unverified" : "unverified"
            },
            targetExecutable = new { path = resolvedExecutable, exists = executableExists, sha256 = executableHash },
            classCoverage = new { requestedClassCount = requiredClasses.Length, present = presentRequiredClasses, missing = missingRequiredClasses, note = "Coverage only checks exact names in the mapping table. It does not prove those classes occur in the selected packages; package class identities are reported only after successful deserialization." },
            sampleTestStatus,
            sampleTests,
            cue4parseLogEventCount = cueLogCapture.Sink.Count,
            cue4parseLogEvents = cueLogCapture.Sink.Snapshot(),
            status,
            validationLimit = "A readable .usmap, matching declared build string, and successful sample parse are necessary evidence, not independent proof of provenance or exact engine compatibility. Review parsed classes, superclass chains, property names/types/values, references, and logs before trusting results."
        };
    }

    private static object SummarizeMappingTest(string packagePath, object inspection)
    {
        var type = inspection.GetType();
        var status = type.GetProperty("status")?.GetValue(inspection)?.ToString() ?? "unknown";
        var exceptionType = type.GetProperty("exceptionType")?.GetValue(inspection)?.ToString();
        var exception = type.GetProperty("exception")?.GetValue(inspection)?.ToString();
        var exports = type.GetProperty("properties")?.GetValue(inspection) as System.Collections.IEnumerable;
        var exportSummaries = exports?.Cast<object>().Select(export =>
        {
            var exportType = export.GetType();
            var propertyValues = exportType.GetProperty("properties")?.GetValue(export) as System.Collections.IEnumerable;
            var propertySample = propertyValues?.Cast<object>().Take(10).Select(property =>
            {
                var propertyType = property.GetType();
                var valueText = JsonSerializer.Serialize(propertyType.GetProperty("value")?.GetValue(property), OutputJson);
                return new
                {
                    name = propertyType.GetProperty("name")?.GetValue(property)?.ToString(),
                    type = propertyType.GetProperty("type")?.GetValue(property)?.ToString(),
                    valueSample = valueText.Length <= 240 ? valueText : valueText[..240]
                };
            }).ToArray() ?? Array.Empty<object>();
            return new
            {
                name = exportType.GetProperty("name")?.GetValue(export)?.ToString(),
                assetClass = exportType.GetProperty("assetClass")?.GetValue(export)?.ToString(),
                superClass = exportType.GetProperty("superClass")?.GetValue(export)?.ToString(),
                propertiesReturned = exportType.GetProperty("propertiesReturned")?.GetValue(export),
                propertyNameTypeSample = propertySample
            };
        }).ToArray() ?? Array.Empty<object>();
        var failedExports = type.GetProperty("failedExports")?.GetValue(inspection) as System.Collections.IEnumerable;
        var propertyErrors = type.GetProperty("propertyErrors")?.GetValue(inspection) as System.Collections.IEnumerable;
        var logEvents = type.GetProperty("cue4parseLogEvents")?.GetValue(inspection) as System.Collections.IEnumerable;
        var category = exceptionType?.Contains("MappingException", StringComparison.OrdinalIgnoreCase) == true
            ? "mapping_or_class_coverage_error"
            : exceptionType?.Contains("VersionException", StringComparison.OrdinalIgnoreCase) == true
                || exception?.Contains("unsupported engine version", StringComparison.OrdinalIgnoreCase) == true
                || exception?.Contains("version mismatch", StringComparison.OrdinalIgnoreCase) == true
                ? "version_incompatibility_explicit"
                : status is "failed" or "partially_parsed" ? "deserialization_or_partial_parse_error" : null;
        return new
        {
            path = packagePath,
            status,
            errorCategory = category,
            exceptionType,
            exception,
            exportCount = exportSummaries.Length,
            exports = exportSummaries,
            failedExportCount = failedExports?.Cast<object>().Count() ?? 0,
            propertyErrorCount = propertyErrors?.Cast<object>().Count() ?? 0,
            failedExportDetails = failedExports?.Cast<object>().Take(4).ToArray() ?? Array.Empty<object>(),
            propertyErrorDetails = propertyErrors?.Cast<object>().Take(4).ToArray() ?? Array.Empty<object>(),
            cue4parseLogEventCount = type.GetProperty("cue4parseLogEventCount")?.GetValue(inspection),
            cue4parseLogEvents = logEvents?.Cast<object>().Take(20).ToArray() ?? Array.Empty<object>(),
            note = category == "mapping_or_class_coverage_error" ? "A mapping-related error does not by itself prove a wrong engine version." : null
        };
    }

    private static string ComputeSha256(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static object? ProjectValue(object? value, int depth, List<object> references)
    {
        if (value is null) return null;
        var type = value.GetType();
        if (value is string || type.IsPrimitive || type.IsEnum || value is decimal) return value;
        if (type.FullName == "CUE4Parse.UE4.Objects.UObject.FName") return value.ToString();
        if (type.FullName == "CUE4Parse.UE4.Objects.UObject.FPackageIndex")
        {
            var isNull = (bool)(type.GetProperty("IsNull")?.GetValue(value) ?? false);
            if (isNull) return null;
            var name = type.GetProperty("Name")?.GetValue(value)?.ToString();
            var resolved = type.GetProperty("ResolvedObject")?.GetValue(value);
            var pathMethod = resolved?.GetType().GetMethod("GetPathName", new[] { typeof(bool) });
            var path = pathMethod?.Invoke(resolved, new object[] { false })?.ToString();
            var reference = new { name, path };
            if (references.Count < 500) references.Add(reference);
            return new { reference = true, name, path };
        }
        if (depth >= 2) return new { valueType = type.FullName, summary = value.ToString() };

        var propertyList = type.GetProperty("Properties", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)?.GetValue(value) as System.Collections.IEnumerable;
        if (propertyList is not null)
        {
            var fields = new List<object>();
            foreach (var item in propertyList.Cast<object>().Take(30))
            {
                var itemType = item.GetType();
                var name = itemType.GetField("Name")?.GetValue(item)?.ToString();
                var propType = itemType.GetField("PropertyType")?.GetValue(item)?.ToString();
                var tag = itemType.GetProperty("Tag")?.GetValue(item);
                var raw = tag?.GetType().GetProperty("GenericValue")?.GetValue(tag);
                fields.Add(new { name, type = propType, value = ProjectValue(raw, depth + 1, references) });
            }
            return new { valueType = type.FullName, fields };
        }

        if (value is System.Collections.IEnumerable sequence)
        {
            var items = new List<object?>();
            foreach (var item in sequence)
            {
                if (items.Count >= 30) break;
                items.Add(ProjectValue(item, depth + 1, references));
            }
            return new { valueType = type.FullName, items };
        }
        return new { valueType = type.FullName, summary = value.ToString() };
    }

    private static void ConfigureMappings(DefaultFileProvider provider, GameProfile profile)
    {
        if (string.IsNullOrWhiteSpace(profile.MappingsPath)) return;
        var path = Path.GetFullPath(profile.MappingsPath);
        if (!File.Exists(path)) throw new FileNotFoundException($"Configured local .usmap file was not found: {path}", path);
        provider.MappingsContainer = new FileUsmapTypeMappingsProvider(path, StringComparer.OrdinalIgnoreCase);
    }

    public static void DisposeProviders()
    {
        lock (ProviderLock)
        {
            foreach (var provider in Providers.Values) provider.Dispose();
            Providers.Clear();
            Catalogs.Clear();
        }
    }
    private static DefaultFileProvider GetProvider(string profileId)
    {
        lock (ProviderLock)
            return Providers.TryGetValue(profileId, out var provider)
                ? provider
                : throw new InvalidOperationException($"Profile '{profileId}' is not mounted. Call load_game_profile first.");
    }

    private static AssetCatalog GetCatalog(string profileId)
    {
        lock (ProviderLock)
            return Catalogs.TryGetValue(profileId, out var catalog)
                ? catalog
                : throw new InvalidOperationException($"Profile '{profileId}' has no synchronized SQLite catalog. Call load_game_profile first.");
    }

    private static object MountSummary(GameProfile profile, DefaultFileProvider provider, string providerStatus)
    {
        var mounted = provider.MountedVfs.ToArray();
        var unmounted = provider.UnloadedVfs.ToArray();
        var requiredKeys = provider.RequiredKeys.Select(guid => guid.ToString()).ToArray();
        var mountStatus = mounted.Length > 0
            ? unmounted.Length > 0 ? "partial" : "mounted"
            : requiredKeys.Length > 0 ? "blocked-on-key-or-container-format" : "no-containers-mounted";

        return new
        {
            profileId = profile.Id,
            providerStatus,
            mountStatus,
            engineVersion = provider.Versions.Game.ToString(),
            indexedFileCount = provider.Files.Count,
            indexedPackageCount = provider.Files.Values.Count(file => file.IsUePackage),
            mountedContainerCount = mounted.Length,
            unmountedContainerCount = unmounted.Length,
            mountedContainers = mounted.Select(DescribeContainer).ToArray(),
            unmountedContainers = unmounted.Select(DescribeContainer).ToArray(),
            requiredKeyGuids = requiredKeys,
            keysMustBeSuppliedExplicitly = requiredKeys.Length > 0
        };
    }

    private static object DescribeContainer(object reader) => new
    {
        readerType = reader.GetType().FullName,
        name = ReadPublicProperty(reader, "Name"),
        path = ReadPublicProperty(reader, "FilePath"),
        mountPoint = ReadPublicProperty(reader, "MountPoint"),
        isEncrypted = ReadPublicProperty(reader, "IsEncrypted"),
        encryptionKeyGuid = ReadPublicProperty(reader, "EncryptionKeyGuid")
    };

    private static object? ReadPublicProperty(object target, string name)
    {
        try
        {
            return target.GetType().GetProperty(name, System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)?.GetValue(target);
        }
        catch
        {
            return null;
        }
    }
}





