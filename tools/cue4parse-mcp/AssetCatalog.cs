using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CUE4Parse.FileProvider;
using Microsoft.Data.Sqlite;

public sealed class AssetCatalog
{
    private readonly string _databasePath;
    private readonly string _profileId;
    private readonly string _archivesPath;
    private readonly string _installRoot;
    private readonly string _engineVersion;

    public string DatabasePath => _databasePath;

    public AssetCatalog(GameProfile profile)
    {
        _profileId = profile.Id;
        _archivesPath = Path.GetFullPath(profile.ArchivesPath);
        _installRoot = Path.GetFullPath(profile.InstallRoot);
        _engineVersion = profile.EngineVersion ?? "unknown";
        var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "VanillaPlus", "CUE4Parse", "catalogs");
        Directory.CreateDirectory(root);
        _databasePath = Path.Combine(root, $"{profile.Id}.sqlite");
    }

    public object Sync(DefaultFileProvider provider, bool recursive)
    {
        var containerManifest = GetContainerManifest(recursive);
        var parserAssembly = typeof(DefaultFileProvider).Assembly;
        var parserVersion = parserAssembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
            ?? parserAssembly.GetName().Version?.ToString()
            ?? "unknown";
        var fingerprint = Fingerprint(containerManifest, _archivesPath, _installRoot, _engineVersion, parserVersion);
        using var connection = Open();
        EnsureSchema(connection);
        using var transaction = connection.BeginTransaction();
        var previousFingerprint = ScalarString(connection, transaction,
            "SELECT value FROM catalog_metadata WHERE key='container_metadata_fingerprint';");
        var invalidated = previousFingerprint is not null && !string.Equals(previousFingerprint, fingerprint, StringComparison.Ordinal);
        var wasEmpty = ScalarLong(connection, transaction, "SELECT COUNT(*) FROM asset_files;") == 0;
        if (invalidated || wasEmpty)
        {
            Execute(connection, transaction, "DELETE FROM asset_nominal_classifications;");
            Execute(connection, transaction, "DELETE FROM asset_files;");
        }

        Execute(connection, transaction, "DELETE FROM containers;");
        Execute(connection, transaction, "DELETE FROM container_readers;");
        using (var insertContainer = connection.CreateCommand())
        {
            insertContainer.Transaction = transaction;
            insertContainer.CommandText = "INSERT INTO containers(container_key,relative_path,extension,size_bytes,last_write_utc_ticks,metadata_json) VALUES($key,$path,$ext,$size,$ticks,$json);";
            foreach (var item in containerManifest)
            {
                insertContainer.Parameters.Clear();
                insertContainer.Parameters.AddWithValue("$key", item.RelativePath.ToLowerInvariant());
                insertContainer.Parameters.AddWithValue("$path", item.RelativePath);
                insertContainer.Parameters.AddWithValue("$ext", item.Extension);
                insertContainer.Parameters.AddWithValue("$size", item.SizeBytes);
                insertContainer.Parameters.AddWithValue("$ticks", item.LastWriteUtcTicks);
                insertContainer.Parameters.AddWithValue("$json", "{}");
                insertContainer.ExecuteNonQuery();
            }
        }

        using (var insertReader = connection.CreateCommand())
        {
            insertReader.Transaction = transaction;
            insertReader.CommandText = "INSERT INTO container_readers(reader_key,reader_type,name,file_path,mount_point,is_encrypted,encryption_key_guid,metadata_json) VALUES($key,$type,$name,$path,$mount,$encrypted,$guid,$json);";
            foreach (var reader in provider.MountedVfs)
            {
                var metadata = new
                {
                    readerType = reader.GetType().FullName,
                    name = ReadPublic(reader, "Name"),
                    filePath = ReadPublic(reader, "FilePath"),
                    mountPoint = ReadPublic(reader, "MountPoint"),
                    isEncrypted = ReadPublic(reader, "IsEncrypted"),
                    encryptionKeyGuid = ReadPublic(reader, "EncryptionKeyGuid")
                };
                insertReader.Parameters.Clear();
                insertReader.Parameters.AddWithValue("$key", Guid.NewGuid().ToString("N"));
                insertReader.Parameters.AddWithValue("$type", (object?)metadata.readerType ?? DBNull.Value);
                insertReader.Parameters.AddWithValue("$name", (object?)metadata.name?.ToString() ?? DBNull.Value);
                insertReader.Parameters.AddWithValue("$path", (object?)metadata.filePath?.ToString() ?? DBNull.Value);
                insertReader.Parameters.AddWithValue("$mount", (object?)metadata.mountPoint?.ToString() ?? DBNull.Value);
                insertReader.Parameters.AddWithValue("$encrypted", metadata.isEncrypted is bool encrypted ? encrypted ? 1 : 0 : DBNull.Value);
                insertReader.Parameters.AddWithValue("$guid", (object?)metadata.encryptionKeyGuid?.ToString() ?? DBNull.Value);
                insertReader.Parameters.AddWithValue("$json", JsonSerializer.Serialize(metadata));
                insertReader.ExecuteNonQuery();
            }
        }

        var existingCount = ScalarLong(connection, transaction, "SELECT COUNT(*) FROM asset_files;");
        var indexedCount = provider.Files.Values.Count(file => file.IsUePackage);
        var countChanged = existingCount != indexedCount;
        if (countChanged && !invalidated && !wasEmpty)
        {
            Execute(connection, transaction, "DELETE FROM asset_nominal_classifications;");
            Execute(connection, transaction, "DELETE FROM asset_files;");
            existingCount = 0;
        }
        if (existingCount != indexedCount || invalidated || wasEmpty)
        {
            using var insertFile = connection.CreateCommand();
            insertFile.Transaction = transaction;
            insertFile.CommandText = "INSERT OR REPLACE INTO asset_files(path_key,path,name,extension,size_bytes,is_ue_package,is_encrypted,container_key,analysis_status,analysis_stage,first_seen_utc,last_seen_utc) VALUES($key,$path,$name,$extension,$size,1,$encrypted,NULL,'indexed','provider_index',COALESCE((SELECT first_seen_utc FROM asset_files WHERE path_key=$key),$now),$now);";
            using var insertClassification = connection.CreateCommand();
            insertClassification.Transaction = transaction;
            insertClassification.CommandText = "INSERT OR IGNORE INTO asset_nominal_classifications(path_key,taxonomy,classification,matched_term,evidence_kind) VALUES($key,'subsystem-terms-v1',$classification,$term,'path_name_heuristic');";
            var now = DateTimeOffset.UtcNow.ToString("O");
            foreach (var file in provider.Files.Values.Where(file => file.IsUePackage))
            {
                var path = file.Path.Replace('\\', '/');
                insertFile.Parameters.Clear();
                insertFile.Parameters.AddWithValue("$key", path.ToLowerInvariant());
                insertFile.Parameters.AddWithValue("$path", path);
                insertFile.Parameters.AddWithValue("$name", file.NameWithoutExtension);
                insertFile.Parameters.AddWithValue("$extension", Path.GetExtension(path));
                insertFile.Parameters.AddWithValue("$size", file.Size);
                insertFile.Parameters.AddWithValue("$encrypted", file.IsEncrypted ? 1 : 0);
                insertFile.Parameters.AddWithValue("$now", now);
                insertFile.ExecuteNonQuery();

                foreach (var (subsystem, terms) in SubsystemTerms)
                foreach (var term in terms.Where(term => Matches(path, term)))
                {
                    insertClassification.Parameters.Clear();
                    insertClassification.Parameters.AddWithValue("$key", path.ToLowerInvariant());
                    insertClassification.Parameters.AddWithValue("$classification", subsystem);
                    insertClassification.Parameters.AddWithValue("$term", term);
                    insertClassification.ExecuteNonQuery();
                }
            }
        }

        UpsertMetadata(connection, transaction, "container_metadata_fingerprint", fingerprint);
        UpsertMetadata(connection, transaction, "fingerprint_method", "SHA-256 of profile install/archive roots, configured engine/parser versions, and sorted relative container paths, sizes, and last-write UTC ticks; does not hash container payload bytes");
        UpsertMetadata(connection, transaction, "parser_version", parserVersion);
        UpsertMetadata(connection, transaction, "engine_profile", _engineVersion);
        UpsertMetadata(connection, transaction, "archives_root", _archivesPath);
        UpsertMetadata(connection, transaction, "game_install_root", _installRoot);
        UpsertMetadata(connection, transaction, "indexed_file_count", provider.Files.Count.ToString());
        UpsertMetadata(connection, transaction, "indexed_package_count", indexedCount.ToString());
        UpsertMetadata(connection, transaction, "last_synced_utc", DateTimeOffset.UtcNow.ToString("O"));
        transaction.Commit();

        return new
        {
            databasePath = _databasePath,
            status = invalidated ? "rebuilt_fingerprint_changed" : wasEmpty ? "created" : countChanged ? "rebuilt_count_changed" : "refreshed",
            invalidated,
            fingerprint,
            fingerprintMethod = "SHA-256 of install/archive roots, engine/parser versions, and relative container path/size/mtime manifest; payload bytes are not hashed",
            parserVersion,
            engineProfile = _engineVersion,
            indexedFileCount = provider.Files.Count,
            indexedPackageCount = indexedCount,
            containerCount = containerManifest.Count
        };
    }

    public object CompareToProvider(DefaultFileProvider provider)
    {
        using var connection = Open();
        EnsureSchema(connection);
        var memory = provider.Files.Values.Where(file => file.IsUePackage).Select(file => file.Path.Replace('\\', '/')).ToArray();
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT path FROM asset_files ORDER BY path COLLATE NOCASE;";
        using var reader = command.ExecuteReader();
        var stored = new List<string>();
        while (reader.Read()) stored.Add(reader.GetString(0));
        var memorySet = memory.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var storedSet = stored.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var missingFromCatalog = memorySet.Except(storedSet, StringComparer.OrdinalIgnoreCase).Take(10).ToArray();
        var extraInCatalog = storedSet.Except(memorySet, StringComparer.OrdinalIgnoreCase).Take(10).ToArray();
        return new
        {
            equivalent = memory.Length == stored.Count && missingFromCatalog.Length == 0 && extraInCatalog.Length == 0,
            memoryCount = memory.Length,
            catalogCount = stored.Count,
            distinctMemoryPathCount = memorySet.Count,
            distinctCatalogPathCount = storedSet.Count,
            missingFromCatalog,
            extraInCatalog,
            orderingCheck = "set equivalence (case-insensitive); SQL and provider may have different collation tie ordering"
        };
    }

    public object CompareQueries(DefaultFileProvider provider)
    {
        var probes = new[]
        {
            new CatalogQuery("BP_", null, null, null, 0, 25),
            new CatalogQuery("BP_", "Voyage/Content/Animations/Notify/", null, ".uasset", 2, 10),
            new CatalogQuery("BP_", null, "Dropped_Magazine", null, 0, 10),
            new CatalogQuery("DT_", "Voyage/Content/", null, ".uasset", 5, 20)
        };
        var rows = probes.Select(probe =>
        {
            var memory = provider.Files.Values.Where(file => file.IsUePackage)
                .Where(file => file.Path.Contains(probe.Query, StringComparison.OrdinalIgnoreCase))
                .Where(file => probe.PathPrefix is null || file.Path.StartsWith(probe.PathPrefix, StringComparison.OrdinalIgnoreCase))
                .Where(file => probe.AssetName is null || file.NameWithoutExtension.Contains(probe.AssetName, StringComparison.OrdinalIgnoreCase))
                .Where(file => probe.Extension is null || Path.GetExtension(file.Path).Equals(probe.Extension, StringComparison.OrdinalIgnoreCase))
                .OrderBy(file => file.Path, StringComparer.OrdinalIgnoreCase)
                .Skip(probe.Offset).Take(probe.Limit).Select(file => file.Path.Replace('\\', '/')).ToArray();
            var stored = ReadPackages(probe.PathPrefix)
                .Where(file => file.Path.Contains(probe.Query, StringComparison.OrdinalIgnoreCase))
                .Where(file => probe.AssetName is null || file.Name.Contains(probe.AssetName, StringComparison.OrdinalIgnoreCase))
                .Where(file => probe.Extension is null || file.Extension.Equals(probe.Extension, StringComparison.OrdinalIgnoreCase))
                .OrderBy(file => file.Path, StringComparer.OrdinalIgnoreCase)
                .Skip(probe.Offset).Take(probe.Limit).Select(file => file.Path).ToArray();
            return new { query = probe, equivalent = memory.SequenceEqual(stored, StringComparer.OrdinalIgnoreCase), memoryCount = memory.Length, catalogCount = stored.Length, firstMismatch = memory.Zip(stored).FirstOrDefault(pair => !string.Equals(pair.First, pair.Second, StringComparison.OrdinalIgnoreCase)) };
        }).ToArray();
        return new { equivalent = rows.All(row => row.equivalent), probes = rows };
    }

    public object CompareSubsystemQueries(DefaultFileProvider provider)
    {
        const string contentPrefix = "Voyage/Content/";
        var memoryFiles = provider.Files.Values.Where(file => file.IsUePackage && file.Path.Replace('\\', '/').StartsWith(contentPrefix, StringComparison.OrdinalIgnoreCase)).Select(file => new CatalogAsset(file.Path.Replace('\\', '/'), file.NameWithoutExtension, Path.GetExtension(file.Path), file.Size, file.IsEncrypted)).ToArray();
        var catalogFiles = ReadPackages(contentPrefix);
        var results = SubsystemTerms.OrderBy(item => item.Key, StringComparer.OrdinalIgnoreCase).Select(group =>
        {
            static string[] Candidates(IEnumerable<CatalogAsset> files, string[] terms) => files
                .Select(file => new { file.Path, matches = terms.Where(term => Matches(file.Path, term)).ToArray() })
                .Where(item => item.matches.Length > 0)
                .OrderByDescending(item => item.matches.Length)
                .ThenBy(item => item.Path, StringComparer.OrdinalIgnoreCase)
                .Select(item => item.Path)
                .ToArray();
            var memory = Candidates(memoryFiles, group.Value);
            var stored = Candidates(catalogFiles, group.Value);
            return new { subsystemId = group.Key, equivalent = memory.SequenceEqual(stored, StringComparer.OrdinalIgnoreCase), memoryCount = memory.Length, catalogCount = stored.Length };
        }).ToArray();
        return new { equivalent = results.All(result => result.equivalent), groups = results };
    }

    public IReadOnlyList<CatalogAsset> ReadPackages(string? pathPrefix = null)
    {
        using var connection = Open();
        EnsureSchema(connection);
        using var command = connection.CreateCommand();
        command.CommandText = pathPrefix is null
            ? "SELECT path,name,extension,size_bytes,is_encrypted FROM asset_files WHERE is_ue_package=1 ORDER BY path COLLATE NOCASE;"
            : "SELECT path,name,extension,size_bytes,is_encrypted FROM asset_files WHERE is_ue_package=1 AND path LIKE $prefix ESCAPE '\\' ORDER BY path COLLATE NOCASE;";
        if (pathPrefix is not null) command.Parameters.AddWithValue("$prefix", EscapeLike(pathPrefix.Replace('\\', '/').TrimStart('/')) + "%");
        using var reader = command.ExecuteReader();
        var rows = new List<CatalogAsset>();
        while (reader.Read()) rows.Add(new CatalogAsset(reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetInt64(3), reader.GetInt32(4) != 0));
        return rows;
    }

    public CatalogPage SearchPackages(string[] terms, string? pathPrefix, string? assetName, string? extension, int offset, int limit)
    {
        using var connection = Open();
        EnsureSchema(connection);
        var clauses = new List<string> { "is_ue_package=1" };
        if (pathPrefix is not null) clauses.Add("substr(path,1,length($prefix))=$prefix COLLATE NOCASE");
        if (!string.IsNullOrWhiteSpace(assetName)) clauses.Add("instr(lower(name),lower($asset_name))>0");
        if (extension is not null) clauses.Add("extension=$extension COLLATE NOCASE");
        for (var i = 0; i < terms.Length; i++) clauses.Add($"instr(lower(path),lower($term{i}))>0");
        var where = string.Join(" AND ", clauses);
        using var count = connection.CreateCommand();
        count.CommandText = $"SELECT COUNT(*) FROM asset_files WHERE {where};";
        AddSearchParameters(count, terms, pathPrefix, assetName, extension);
        var total = Convert.ToInt32(count.ExecuteScalar());
        using var page = connection.CreateCommand();
        page.CommandText = $"SELECT path,name,extension,size_bytes,is_encrypted FROM asset_files WHERE {where} ORDER BY path COLLATE NOCASE LIMIT $limit OFFSET $offset;";
        AddSearchParameters(page, terms, pathPrefix, assetName, extension);
        page.Parameters.AddWithValue("$limit", limit);
        page.Parameters.AddWithValue("$offset", offset);
        using var reader = page.ExecuteReader();
        var rows = new List<CatalogAsset>();
        while (reader.Read()) rows.Add(new CatalogAsset(reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetInt64(3), reader.GetInt32(4) != 0));
        return new CatalogPage(total, rows);
    }

    public IReadOnlyList<CatalogSubsystemCandidate> ReadSubsystemCandidates(string subsystem, string? pathPrefix)
    {
        using var connection = Open();
        EnsureSchema(connection);
        using var command = connection.CreateCommand();
        command.CommandText = pathPrefix is null
            ? "SELECT f.path,f.size_bytes,c.matched_term FROM asset_files f JOIN asset_nominal_classifications c ON c.path_key=f.path_key WHERE f.is_ue_package=1 AND c.classification=$subsystem ORDER BY f.path COLLATE NOCASE,c.matched_term COLLATE NOCASE;"
            : "SELECT f.path,f.size_bytes,c.matched_term FROM asset_files f JOIN asset_nominal_classifications c ON c.path_key=f.path_key WHERE f.is_ue_package=1 AND c.classification=$subsystem AND substr(f.path,1,length($prefix))=$prefix COLLATE NOCASE ORDER BY f.path COLLATE NOCASE,c.matched_term COLLATE NOCASE;";
        command.Parameters.AddWithValue("$subsystem", subsystem);
        if (pathPrefix is not null) command.Parameters.AddWithValue("$prefix", pathPrefix);
        using var reader = command.ExecuteReader();
        var candidates = new Dictionary<string, (long Size, List<string> Terms)>(StringComparer.OrdinalIgnoreCase);
        while (reader.Read())
        {
            var path = reader.GetString(0);
            if (!candidates.TryGetValue(path, out var candidate)) candidate = (reader.GetInt64(1), []);
            candidate.Terms.Add(reader.GetString(2));
            candidates[path] = candidate;
        }
        return candidates.Select(pair => new CatalogSubsystemCandidate(pair.Key, pair.Value.Size, pair.Value.Terms.ToArray()))
            .OrderByDescending(candidate => candidate.MatchedTerms.Length)
            .ThenBy(candidate => candidate.Path, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public object GetSummary()
    {
        using var connection = Open();
        EnsureSchema(connection);
        var metadata = new Dictionary<string, string>(StringComparer.Ordinal);
        using (var command = connection.CreateCommand())
        {
            command.CommandText = "SELECT key,value FROM catalog_metadata ORDER BY key;";
            using var reader = command.ExecuteReader();
            while (reader.Read()) metadata[reader.GetString(0)] = reader.GetString(1);
        }
        return new
        {
            databasePath = _databasePath,
            profileId = _profileId,
            metadata,
            packageCount = ScalarLong(connection, null, "SELECT COUNT(*) FROM asset_files WHERE is_ue_package=1;"),
            classificationCount = ScalarLong(connection, null, "SELECT COUNT(*) FROM asset_nominal_classifications;"),
            physicalContainerCount = ScalarLong(connection, null, "SELECT COUNT(*) FROM containers;"),
            mountedReaderCount = ScalarLong(connection, null, "SELECT COUNT(*) FROM container_readers;"),
            analysisHistoryCount = ScalarLong(connection, null, "SELECT COUNT(*) FROM analysis_history;"),
            integrityCheck = ScalarString(connection, null, "PRAGMA integrity_check;")
        };
    }

    public void RecordAnalysis(string path, string status, string stage, string? exceptionType, string? exception, string? mappingPath)
    {
        using var connection = Open();
        EnsureSchema(connection);
        var key = path.Replace('\\', '/').ToLowerInvariant();
        using var command = connection.CreateCommand();
        command.CommandText = "UPDATE asset_files SET analysis_status=$status,analysis_stage=$stage,last_seen_utc=$now WHERE path_key=$key; INSERT INTO analysis_history(path_key,attempted_utc,status,stage,exception_type,exception_text,mapping_path,mapping_sha256,container_metadata_fingerprint) VALUES($key,$now,$status,$stage,$type,$error,$mapping,$mapping_hash,(SELECT value FROM catalog_metadata WHERE key='container_metadata_fingerprint'));";
        var now = DateTimeOffset.UtcNow.ToString("O");
        command.Parameters.AddWithValue("$key", key);
        command.Parameters.AddWithValue("$status", status);
        command.Parameters.AddWithValue("$stage", stage);
        command.Parameters.AddWithValue("$now", now);
        command.Parameters.AddWithValue("$type", (object?)exceptionType ?? DBNull.Value);
        command.Parameters.AddWithValue("$error", (object?)exception ?? DBNull.Value);
        command.Parameters.AddWithValue("$mapping", (object?)mappingPath ?? DBNull.Value);
        command.Parameters.AddWithValue("$mapping_hash", MappingHash(mappingPath) is { } hash ? hash : DBNull.Value);
        command.ExecuteNonQuery();
    }

    private SqliteConnection Open()
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = _databasePath, Mode = SqliteOpenMode.ReadWriteCreate, Cache = SqliteCacheMode.Shared }.ToString());
        connection.Open();
        using var pragma = connection.CreateCommand();
        pragma.CommandText = "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;";
        pragma.ExecuteNonQuery();
        return connection;
    }

    private static void EnsureSchema(SqliteConnection connection)
    {
        using var command = connection.CreateCommand();
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS catalog_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS containers(container_key TEXT PRIMARY KEY,relative_path TEXT NOT NULL,extension TEXT NOT NULL,size_bytes INTEGER NOT NULL,last_write_utc_ticks INTEGER NOT NULL,metadata_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS container_readers(reader_key TEXT PRIMARY KEY,reader_type TEXT NULL,name TEXT NULL,file_path TEXT NULL,mount_point TEXT NULL,is_encrypted INTEGER NULL,encryption_key_guid TEXT NULL,metadata_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS asset_files(path_key TEXT PRIMARY KEY,path TEXT NOT NULL,name TEXT NOT NULL,extension TEXT NOT NULL,size_bytes INTEGER NOT NULL,is_ue_package INTEGER NOT NULL,is_encrypted INTEGER NOT NULL,container_key TEXT NULL REFERENCES containers(container_key),analysis_status TEXT NOT NULL,analysis_stage TEXT NOT NULL,first_seen_utc TEXT NOT NULL,last_seen_utc TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_asset_files_name ON asset_files(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS ix_asset_files_extension ON asset_files(extension COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS asset_nominal_classifications(path_key TEXT NOT NULL REFERENCES asset_files(path_key) ON DELETE CASCADE,taxonomy TEXT NOT NULL,classification TEXT NOT NULL,matched_term TEXT NOT NULL,evidence_kind TEXT NOT NULL,PRIMARY KEY(path_key,taxonomy,classification,matched_term));
            CREATE INDEX IF NOT EXISTS ix_nominal_classification ON asset_nominal_classifications(classification,path_key);
            CREATE TABLE IF NOT EXISTS analysis_history(id INTEGER PRIMARY KEY AUTOINCREMENT,path_key TEXT NOT NULL,attempted_utc TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,exception_type TEXT NULL,exception_text TEXT NULL,mapping_path TEXT NULL,mapping_sha256 TEXT NULL,container_metadata_fingerprint TEXT NULL);
            CREATE INDEX IF NOT EXISTS ix_analysis_history_path ON analysis_history(path_key,attempted_utc);
            """;
        command.ExecuteNonQuery();
    }

    private List<ContainerFingerprintEntry> GetContainerManifest(bool recursive)
    {
        if (!Directory.Exists(_archivesPath)) return [];
        return Directory.EnumerateFiles(_archivesPath, "*", recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly)
            .Where(path => Path.GetExtension(path).ToLowerInvariant() is ".pak" or ".utoc" or ".ucas" or ".sig")
            .Select(path =>
            {
                var info = new FileInfo(path);
                return new ContainerFingerprintEntry(Path.GetRelativePath(_archivesPath, path).Replace('\\', '/'), info.Extension.ToLowerInvariant(), info.Length, info.LastWriteTimeUtc.Ticks);
            })
            .OrderBy(item => item.RelativePath, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static string Fingerprint(IEnumerable<ContainerFingerprintEntry> entries, string archivesPath, string installRoot, string engineVersion, string parserVersion)
    {
        var manifest = $"archives={archivesPath}\ninstall={installRoot}\nengine={engineVersion}\nparser={parserVersion}\n" +
            string.Join("\n", entries.Select(item => $"{item.RelativePath}\t{item.Extension}\t{item.SizeBytes}\t{item.LastWriteUtcTicks}"));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(manifest))).ToLowerInvariant();
    }

    private static bool Matches(string path, string term) => term.Equals("AI", StringComparison.OrdinalIgnoreCase)
        ? System.Text.RegularExpressions.Regex.IsMatch(path, @"(?<![\p{L}\p{N}])AI(?![\p{L}\p{N}])", System.Text.RegularExpressions.RegexOptions.IgnoreCase | System.Text.RegularExpressions.RegexOptions.CultureInvariant)
        : path.Contains(term, StringComparison.OrdinalIgnoreCase);

    private static readonly IReadOnlyDictionary<string, string[]> SubsystemTerms = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
    {
        ["energy"] = ["Power", "Energy", "Generator", "Battery"], ["construction"] = ["Build", "Structure", "Foundation"],
        ["inventory"] = ["Inventory", "Item", "Storage"], ["ai"] = ["AI", "Behavior", "NPC"],
        ["vehicles"] = ["Vehicle", "Engine", "Wheel"], ["world"] = ["World", "Biome", "Weather"]
    };

    private static object? ReadPublic(object target, string name)
    {
        try { return target.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance)?.GetValue(target); }
        catch { return null; }
    }

    private static string EscapeLike(string value) => value.Replace("\\", "\\\\").Replace("%", "\\%").Replace("_", "\\_");
    private static string? MappingHash(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path)) return null;
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
    private static void Execute(SqliteConnection connection, SqliteTransaction transaction, string sql) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = sql; command.ExecuteNonQuery(); }
    private static void AddSearchParameters(SqliteCommand command, string[] terms, string? pathPrefix, string? assetName, string? extension)
    {
        if (pathPrefix is not null) command.Parameters.AddWithValue("$prefix", pathPrefix);
        if (!string.IsNullOrWhiteSpace(assetName)) command.Parameters.AddWithValue("$asset_name", assetName);
        if (extension is not null) command.Parameters.AddWithValue("$extension", extension);
        for (var i = 0; i < terms.Length; i++) command.Parameters.AddWithValue($"$term{i}", terms[i]);
    }
    private static long ScalarLong(SqliteConnection connection, SqliteTransaction? transaction, string sql) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = sql; return Convert.ToInt64(command.ExecuteScalar()); }
    private static string? ScalarString(SqliteConnection connection, SqliteTransaction? transaction, string sql) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = sql; return command.ExecuteScalar() as string; }
    private static void UpsertMetadata(SqliteConnection connection, SqliteTransaction transaction, string key, string value) { using var command = connection.CreateCommand(); command.Transaction = transaction; command.CommandText = "INSERT INTO catalog_metadata(key,value) VALUES($key,$value) ON CONFLICT(key) DO UPDATE SET value=excluded.value;"; command.Parameters.AddWithValue("$key", key); command.Parameters.AddWithValue("$value", value); command.ExecuteNonQuery(); }

    private sealed record ContainerFingerprintEntry(string RelativePath, string Extension, long SizeBytes, long LastWriteUtcTicks);
    private sealed record CatalogQuery(string Query, string? PathPrefix, string? AssetName, string? Extension, int Offset, int Limit);
}

public sealed record CatalogAsset(string Path, string Name, string Extension, long SizeBytes, bool IsEncrypted);
public sealed record CatalogPage(int TotalCount, IReadOnlyList<CatalogAsset> Results);
public sealed record CatalogSubsystemCandidate(string Path, long SizeBytes, string[] MatchedTerms);
