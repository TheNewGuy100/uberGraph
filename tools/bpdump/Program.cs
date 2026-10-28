using Newtonsoft.Json;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Versions;

// Read-only: dumps the functions of Blueprint packages (and their Kismet bytecode) from a loose extraction, so logic such as "where
// does this menu take its list from" can be read without running the game.
// Usage: bpdump <extraction dir> <usmap> <package path suffix, e.g. /BP_VaultWidget.uasset> <output dir> [function name contains]
if (args.Length < 4) throw new ArgumentException("Usage: bpdump <extraction dir> <usmap> <package suffix> <output dir> [function filter]");
var root = args[0]; var usmap = args[1]; var suffix = args[2]; var outDir = args[3];
var filter = args.Length > 4 ? args[4] : null;
Directory.CreateDirectory(outDir);

var game = Enum.TryParse<EGame>("GAME_UE5_8", out var g) ? g : EGame.GAME_UE5_LATEST;
var provider = new DefaultFileProvider(root, SearchOption.AllDirectories, new VersionContainer(game), StringComparer.OrdinalIgnoreCase);
provider.Initialize();
provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmap, StringComparer.OrdinalIgnoreCase);

var matches = provider.Files.Values.Where(f => f.IsUePackage && f.Path.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)).Select(f => f.Path).ToList();
if (matches.Count != 1) { Console.WriteLine($"{matches.Count} packages match {suffix}: " + string.Join(", ", matches.Take(5))); return 2; }
if (!provider.TryLoadPackage(matches[0], out IPackage? package) || package == null) { Console.WriteLine("load failed: " + matches[0]); return 3; }

var settings = new JsonSerializerSettings { Formatting = Formatting.Indented, ReferenceLoopHandling = ReferenceLoopHandling.Ignore, MaxDepth = 64 };
var summary = new List<string>();
foreach (var export in package.GetExports())
{
    if (export is not UFunction fn) continue;
    if (filter != null && !fn.Name.Contains(filter, StringComparison.OrdinalIgnoreCase)) continue;
    var name = fn.Name;
    var path = Path.Combine(outDir, Path.GetFileNameWithoutExtension(matches[0]) + "." + name + ".json");
    try
    {
        File.WriteAllText(path, JsonConvert.SerializeObject(new { name, flags = fn.FunctionFlags.ToString(), bytecode = fn.ScriptBytecode }, settings));
        summary.Add($"{name}: {fn.ScriptBytecode?.Length ?? 0} expressions -> {Path.GetFileName(path)}");
    }
    catch (Exception ex) { summary.Add($"{name}: serialize failed: {ex.GetType().Name}: {ex.Message[..Math.Min(100, ex.Message.Length)]}"); }
}
Console.WriteLine(matches[0]);
foreach (var line in summary) Console.WriteLine("  " + line);
if (summary.Count == 0)
{
    var types = package.GetExports().GroupBy(e => e.ExportType).OrderByDescending(x => x.Count()).Select(x => $"{x.Key}x{x.Count()}");
    Console.WriteLine("  no functions found; export types: " + string.Join(", ", types));
    foreach (var e in package.GetExports().Where(e => e.ExportType.Contains("Function", StringComparison.OrdinalIgnoreCase) || e.ExportType.Contains("Class")).Take(10))
        Console.WriteLine($"    {e.ExportType}: {e.Name} ({e.GetType().Name})");
}
return 0;
