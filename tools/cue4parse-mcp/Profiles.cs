using System.Text.Json;
using System.Text.Json.Serialization;

public sealed record GameProfile
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string InstallRoot { get; init; }
    public required string ArchivesPath { get; init; }
    public string? EngineVersion { get; init; }
    public string? MappingsPath { get; init; }
    public bool RecursiveArchiveSearch { get; init; }
}

public sealed record McpSettings
{
    public required List<GameProfile> Profiles { get; init; }
}

public sealed class ProfileStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    private readonly Dictionary<string, GameProfile> _profiles;
    public string ConfigPath { get; }

    private ProfileStore(string configPath, IEnumerable<GameProfile> profiles)
    {
        ConfigPath = configPath;
        _profiles = profiles.ToDictionary(p => p.Id, StringComparer.OrdinalIgnoreCase);
    }

    public static ProfileStore Load(string configPath)
    {
        if (!File.Exists(configPath))
            throw new FileNotFoundException($"Game profile configuration was not found: {configPath}. Copy games.example.json to games.json and add profiles.", configPath);

        var settings = JsonSerializer.Deserialize<McpSettings>(File.ReadAllText(configPath), JsonOptions)
            ?? throw new InvalidDataException("The game profile configuration is empty or invalid.");

        if (settings.Profiles is null) throw new InvalidDataException("The configuration must contain a 'profiles' array.");
        foreach (var profile in settings.Profiles)
        {
            if (string.IsNullOrWhiteSpace(profile.Id) || profile.Id.Any(c => !(char.IsAsciiLetterOrDigit(c) || c is '-' or '_')))
                throw new InvalidDataException($"Invalid profile id '{profile.Id}'. Use only ASCII letters, digits, '-' and '_'.");
            if (string.IsNullOrWhiteSpace(profile.Name)) throw new InvalidDataException($"Profile '{profile.Id}' has no name.");
            if (string.IsNullOrWhiteSpace(profile.InstallRoot)) throw new InvalidDataException($"Profile '{profile.Id}' has no installRoot.");
            if (string.IsNullOrWhiteSpace(profile.ArchivesPath)) throw new InvalidDataException($"Profile '{profile.Id}' has no archivesPath.");
        }
        if (settings.Profiles.Select(p => p.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != settings.Profiles.Count)
            throw new InvalidDataException("Profile ids must be unique, case-insensitively.");

        return new ProfileStore(Path.GetFullPath(configPath), settings.Profiles);
    }

    public IReadOnlyCollection<GameProfile> Profiles => _profiles.Values;

    public bool TryGet(string id, out GameProfile profile) => _profiles.TryGetValue(id, out profile!);

    public GameProfile GetRequired(string id) => _profiles.TryGetValue(id, out var profile)
        ? profile
        : throw new KeyNotFoundException($"Unknown game profile '{id}'. Call list_game_profiles to see configured ids.");
}

public static class McpRuntime
{
    public static ProfileStore Profiles { get; set; } = null!;
}

