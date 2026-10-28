using System.Text.RegularExpressions;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Versions;
using Newtonsoft.Json;

// Read-only spot check of property values in extracted packages. Usage: spot-check <extraction dir> <usmap>
var provider = new DefaultFileProvider(args[0], SearchOption.AllDirectories, new VersionContainer(EGame.GAME_UE5_8), StringComparer.OrdinalIgnoreCase);
provider.Initialize();
provider.MappingsContainer = new FileUsmapTypeMappingsProvider(args[1], StringComparer.OrdinalIgnoreCase);

string Find(string suffix) => provider.Files.Values.Where(f => f.IsUePackage && f.Path.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)).Select(f => f.Path).Single();
string Dump(string suffix)
{
    var path = Find(suffix);
    provider.TryLoadPackage(path, out var pkg);
    return JsonConvert.SerializeObject(pkg!.GetExports(), Formatting.Indented);
}
string Squash(string s) => Regex.Replace(s, @"\s+", " ");
void Show(string json, string pattern, string prefix = "  ", int max = 12)
{
    var found = 0;
    foreach (Match m in Regex.Matches(json, pattern))
    {
        Console.WriteLine(prefix + Squash(m.Value));
        if (++found >= max) break;
    }
    if (found == 0) Console.WriteLine(prefix + "(no match for " + pattern + ")");
}

var item = Dump("/DA_Item_PlayerBoxLarge.uasset");
Console.WriteLine("== DA_Item_PlayerBoxLarge (json chars " + item.Length + ")");
Show(item, @"DA_Part_[A-Za-z]+[^""]*"" *: *[0-9]+");
Show(item, @"""(CraftTime|Weight)"" *: *[^,\n]+");
Show(item, @"BP_Inventory_PlayerBox_Large[^""]*");

var large = Dump("/BP_Inventory_PlayerBox_Large.uasset");
Console.WriteLine("== BP_Inventory_PlayerBox_Large MaxWeightLimit (json chars " + large.Length + ")");
Show(large, @"""MaxWeightLimit"" *: *[^,\n]+");
var small = Dump("/BP_Inventory_PlayerBox_Small.uasset");
Console.WriteLine("== BP_Inventory_PlayerBox_Small MaxWeightLimit");
Show(small, @"""MaxWeightLimit"" *: *[^,\n]+");

var torch = Dump("/DA_Skill_Light_Basic_Flashlight.uasset");
Console.WriteLine("== DA_Skill_Light_Basic_Flashlight Unlock fields");
Show(torch, @"""(UnlockMethod|Cost|Requirement)"" *: *[^,\n]+");

var menu = Dump("/BP_VoyageInGameMenu.uasset");
Console.WriteLine("== BP_VoyageInGameMenu (json chars " + menu.Length + ") text keys");
Show(menu, @"""(SourceString|Key)"" *: *""[^""]{1,80}""", "  ", 25);
provider.Dispose();
