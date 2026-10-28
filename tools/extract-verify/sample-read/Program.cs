using System.Diagnostics;
using System.Text.Json;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Versions;

// Read-only sample read of loose extracted packages with CUE4Parse and a .usmap.
// Usage: sample-read <extraction dir> <usmap> <random sample size> <output json>
if (args.Length != 4) throw new ArgumentException("Usage: sample-read <extraction dir> <usmap> <sampleSize> <out.json>");
var root = args[0];
var usmap = args[1];
var sampleSize = int.Parse(args[2]);
var outPath = args[3];

var gameName = Enum.TryParse<EGame>("GAME_UE5_8", out var g58) ? "GAME_UE5_8" : "GAME_UE5_LATEST";
var game = Enum.Parse<EGame>(gameName);
var provider = new DefaultFileProvider(root, SearchOption.AllDirectories, new VersionContainer(game), StringComparer.OrdinalIgnoreCase);
var sw = Stopwatch.StartNew();
provider.Initialize();
provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmap, StringComparer.OrdinalIgnoreCase);
var initSeconds = sw.Elapsed.TotalSeconds;

var packages = provider.Files.Values.Where(f => f.IsUePackage).Select(f => f.Path).OrderBy(p => p, StringComparer.Ordinal).ToList();

string[] namedSuffixes =
{
    "/IA_SlowMo.uasset",
    "/DA_Item_PlayerBoxLarge.uasset",
    "/DA_Item_PlayerBoxSmall.uasset",
    "/DA_Skill_Engineering_FortiHold_Storage_Container.uasset",
    "/DA_Skill_Light_Basic_Flashlight.uasset",
    "/DA_Equipment_HeadLight.uasset",
    "/BP_Inventory_PlayerBox.uasset",
    "/BP_Inventory_PlayerBox_Large.uasset",
    "/BP_VoyageInGameMenu.uasset",
    "/BP_FocusableButton.uasset",
    "/DA_Widget_Pause.uasset",
    "/BP_VoyageSaveGameSlotsWidget.uasset",
};
var named = new List<string>();
foreach (var suffix in namedSuffixes)
{
    var m = packages.Where(p => p.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)).ToList();
    named.Add(m.Count == 1 ? m[0] : suffix + (m.Count == 0 ? " (not found)" : $" ({m.Count} matches)"));
}

var rng = new Random(12345);
var randomSample = packages.OrderBy(_ => rng.Next()).Take(sampleSize).ToList();

object ReadOne(string path)
{
    var watch = Stopwatch.StartNew();
    try
    {
        if (!provider.TryLoadPackage(path, out IPackage? package) || package == null)
            return new { path, status = "load_failed", detail = "TryLoadPackage returned false", ms = watch.ElapsedMilliseconds };
        var exports = package.GetExports().ToList();
        var types = exports.GroupBy(e => e.ExportType).OrderByDescending(x => x.Count()).Take(4).Select(x => $"{x.Key}x{x.Count()}").ToArray();
        return new { path, status = "ok", exports = exports.Count, topTypes = types, ms = watch.ElapsedMilliseconds };
    }
    catch (Exception ex)
    {
        var msg = ex.Message.Length > 140 ? ex.Message[..140] : ex.Message;
        return new { path, status = "exception", detail = ex.GetType().Name + ": " + msg, ms = watch.ElapsedMilliseconds };
    }
}

var namedResults = named.Select(p => p.Contains(" (") && !p.Contains('/') ? (object)new { path = p, status = "not_found" } : p.StartsWith("/") ? new { path = p, status = "not_found" } : ReadOne(p)).ToList();
var sampleResults = randomSample.Select(ReadOne).ToList();

int Count(IEnumerable<object> results, string status) =>
    results.Count(r => JsonSerializer.SerializeToElement(r).GetProperty("status").GetString() == status);

var failureKinds = sampleResults
    .Select(r => JsonSerializer.SerializeToElement(r))
    .Where(e => e.GetProperty("status").GetString() != "ok")
    .GroupBy(e => e.TryGetProperty("detail", out var d) ? (d.GetString() ?? "")[..Math.Min(90, (d.GetString() ?? "").Length)] : "")
    .Select(gp => new { kind = gp.Key, count = gp.Count(), example = gp.First().GetProperty("path").GetString() })
    .OrderByDescending(x => x.count).Take(10).ToList();

var report = new
{
    engineProfile = gameName,
    root,
    usmapFile = Path.GetFileName(usmap),
    initSeconds,
    indexedFiles = provider.Files.Count,
    indexedPackages = packages.Count,
    namedPackages = new { total = namedResults.Count, ok = Count(namedResults, "ok"), results = namedResults },
    randomSample = new
    {
        seed = 12345, requested = sampleSize, ok = Count(sampleResults, "ok"),
        exception = Count(sampleResults, "exception"), loadFailed = Count(sampleResults, "load_failed"),
        failureKinds,
        slowestMs = sampleResults.Select(r => JsonSerializer.SerializeToElement(r).GetProperty("ms").GetInt64()).DefaultIfEmpty(0).Max(),
    },
    totalSeconds = sw.Elapsed.TotalSeconds,
};
var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
File.WriteAllText(outPath, json);
Console.WriteLine(json.Length > 6000 ? json[..6000] + "\n...(truncated; full file written)" : json);
provider.Dispose();
