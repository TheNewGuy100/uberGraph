"""Generates an editor-side stand-in plugin (module `Voyage`) for chosen game classes from the game's usmap. Read-only on the mapping.

    python tools/usmap/gen_stubs.py --out <project>/Plugins/<GameName>Stubs <GameClass> <OtherGameClass>

What comes out: one UE plugin whose module is named after the game module (so cooked assets that reference /Script/Voyage.* resolve
to it in the editor), with one header holding the enums, structs and classes needed by the seeds (the closure of their properties),
property by property in the mapping's order. The mapping gives names, types and order only, so every ObjectProperty becomes
TObjectPtr<UObject> and every soft pointer TSoftObjectPtr<UObject> (the serialized bytes are the same). No functions, no defaults,
no flags. Engine types come from the tables below; anything else that is not a seed's own type is generated.

The output is derived from the proprietary game's mapping: keep it LOCAL (the plugin folder is git-ignored). Check the result with
tools/ue-editor/examples/dump_layouts.py and tools/usmap/compare_layout.py before trusting it.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "profile"))
import usmap_tool  # noqa: E402

ENGINE_STRUCTS = {  # mapping name -> (C++ type, include)
    "Vector": ("FVector", None), "Quat": ("FQuat", None), "Rotator": ("FRotator", None), "Transform": ("FTransform", None),
    "LinearColor": ("FLinearColor", None), "SoftObjectPath": ("FSoftObjectPath", None), "TopLevelAssetPath": ("FTopLevelAssetPath", None),
    "PrimaryAssetType": ("FPrimaryAssetType", "UObject/PrimaryAssetId.h"), "PrimaryAssetId": ("FPrimaryAssetId", "UObject/PrimaryAssetId.h"),
}
ENGINE_ENUMS = {  # mapping name -> (C++ type, include)
    "ECollisionChannel": ("ECollisionChannel", "Engine/EngineTypes.h"), "ECollisionResponse": ("ECollisionResponse", "Engine/EngineTypes.h"),
}
ENGINE_CLASSES = {  # mapping name -> (C++ type, include)
    "Object": ("UObject", None), "DataAsset": ("UDataAsset", "Engine/DataAsset.h"), "PrimaryDataAsset": ("UPrimaryDataAsset", "Engine/DataAsset.h"),
}
SIMPLE = {"Bool": "bool", "Byte": "uint8", "Int": "int32", "Float": "float", "Double": "double", "UInt64": "uint64", "UInt32": "uint32",
          "UInt16": "uint16", "Int64": "int64", "Int16": "int16", "Int8": "int8", "Name": "FName", "Str": "FString", "Text": "FText",
          "Object": "TObjectPtr<UObject>", "WeakObject": "TWeakObjectPtr<UObject>", "LazyObject": "TLazyObjectPtr<UObject>",
          "SoftObject": "TSoftObjectPtr<UObject>", "AssetObject": "TSoftObjectPtr<UObject>"}
KEYWORDS = {"class", "struct", "enum", "default", "new", "delete", "template", "typename", "operator", "register", "this", "union", "namespace"}


def cpp_type(u, t, engine_enum_names):
    kind = t["t"]
    if kind in SIMPLE:
        return SIMPLE[kind]
    if kind == "Struct":
        return ENGINE_STRUCTS[t["struct"]][0] if t["struct"] in ENGINE_STRUCTS else "F" + t["struct"]
    if kind == "Enum":
        # unscoped engine enums must be wrapped to be used in UPROPERTY containers and properties
        return "TEnumAsByte<%s>" % t["enum"] if t["enum"] in ENGINE_ENUMS else t["enum"]
    if kind == "Array":
        return "TArray<%s>" % cpp_type(u, t["inner"], engine_enum_names)
    if kind == "Set":
        return "TSet<%s>" % cpp_type(u, t["inner"], engine_enum_names)
    if kind == "Optional":
        return "TOptional<%s>" % cpp_type(u, t["inner"], engine_enum_names)
    if kind == "Map":
        key = t["key"]
        if key["t"] == "Struct":
            raise SystemExit("a map with a struct key needs a hash function; not handled: " + usmap_tool.fmt(t))
        return "TMap<%s, %s>" % (cpp_type(u, key, engine_enum_names), cpp_type(u, t["value"], engine_enum_names))
    raise SystemExit("unsupported property type in a stand-in: " + usmap_tool.fmt(t))


def ident(name):
    clean = "".join(c if (c.isalnum() or c == "_") else "_" for c in name)
    if clean and clean[0].isdigit():
        clean = "_" + clean
    return clean + "_" if clean in KEYWORDS else clean


def closure(u, seeds):
    schemas, enums, todo = [], set(), list(seeds)
    seen = set()
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        if n in u.enums:
            enums.add(n); continue
        if n not in u.schemas:
            raise SystemExit("not in the mapping: " + n)
        schemas.append(n)
        s = u.schemas[n]
        if s["super"]:
            todo.append(s["super"])
        for p in s["props"]:
            todo.extend(u.refs(p["type"]))
    return schemas, enums


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seeds", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--module", default="Voyage")
    ap.add_argument("--usmap")
    args = ap.parse_args(argv)
    path = args.usmap
    if not path:
        import game_profile
        path = game_profile.get(game_profile.load(), "mappings.path")
    u = usmap_tool.Usmap(path)
    schemas, enums = closure(u, args.seeds)

    # a schema is a class when its chain reaches Object through a super link; plain structs have no super
    classes = [n for n in schemas if u.schemas[n]["super"] is not None or n in ENGINE_CLASSES]
    structs = [n for n in schemas if n not in classes and n not in ENGINE_STRUCTS]
    gen_classes = [n for n in classes if n not in ENGINE_CLASSES]
    gen_enums = sorted(e for e in enums if e not in ENGINE_ENUMS)

    # structs in dependency order
    ordered, done = [], set()

    def visit(n):
        if n in done or n in ENGINE_STRUCTS:
            return
        done.add(n)
        for p in u.schemas[n]["props"]:
            for r in u.refs(p["type"]):
                if r in structs:
                    visit(r)
        ordered.append(n)
    for n in sorted(structs):
        visit(n)

    # classes in chain order (parents first)
    cls_ordered, cdone = [], set()

    def cvisit(n):
        if n in cdone or n in ENGINE_CLASSES:
            return
        cdone.add(n)
        sup = u.schemas[n]["super"]
        if sup and sup not in ENGINE_CLASSES:
            cvisit(sup)
        cls_ordered.append(n)
    for n in sorted(gen_classes):
        cvisit(n)

    includes = {"CoreMinimal.h"}
    for table in (ENGINE_STRUCTS, ENGINE_ENUMS, ENGINE_CLASSES):
        for name, (_cpp, inc) in table.items():
            if inc and (name in schemas or name in enums):
                includes.add(inc)

    lines = ["// GENERATED by tools/usmap/gen_stubs.py from the game's usmap. Local only; never commit or distribute.",
             "// Stand-ins for editor authoring: property names, types and order only (see the generator's docstring).",
             "#pragma once", ""]
    lines += ["#include \"%s\"" % i for i in sorted(includes)]
    lines += ["#include \"VoyageStubs.generated.h\"", ""]
    for e in gen_enums:
        values = [(n.split("::")[-1], v) for n, v in u.enums[e]]
        values = [(n, v) for n, v in values if not n.endswith("_MAX")]
        low, high = min(v for _, v in values), max(v for _, v in values)
        base = "uint8" if low >= 0 and high <= 255 else ("uint16" if low >= 0 and high <= 65535 else "int32")
        lines.append("UENUM()")
        lines.append("enum class %s : %s" % (e, base))
        lines.append("{")
        for n, v in values:
            lines.append("\t%s = %d," % (ident(n), v))
        lines += ["};", ""]
    for n in ordered:
        lines += ["USTRUCT()", "struct F%s" % n, "{", "\tGENERATED_BODY()", ""]
        for p in u.schemas[n]["props"]:
            t = cpp_type(u, p["type"], ENGINE_ENUMS)
            dim = "[%d]" % p["array"] if p["array"] > 1 else ""
            lines += ["\tUPROPERTY(EditAnywhere)", "\t%s %s%s{};" % (t, ident(p["name"]), dim), ""]
        lines += ["};", ""]
    for n in cls_ordered:
        sup = u.schemas[n]["super"]
        sup_cpp = ENGINE_CLASSES[sup][0] if sup in ENGINE_CLASSES else "U" + sup
        lines += ["UCLASS()", "class VOYAGE_API U%s : public %s" % (n, sup_cpp), "{", "\tGENERATED_BODY()", "", "public:"]
        for p in u.schemas[n]["props"]:
            t = cpp_type(u, p["type"], ENGINE_ENUMS)
            dim = "[%d]" % p["array"] if p["array"] > 1 else ""
            lines += ["\tUPROPERTY(EditAnywhere)", "\t%s %s%s{};" % (t, ident(p["name"]), dim), ""]
        lines += ["};", ""]
    header = "\n".join(lines)

    out = args.out
    src = os.path.join(out, "Source", args.module)
    os.makedirs(os.path.join(src, "Public"), exist_ok=True)
    os.makedirs(os.path.join(src, "Private"), exist_ok=True)
    plugin_name = os.path.basename(os.path.normpath(out))
    open(os.path.join(out, plugin_name + ".uplugin"), "w", encoding="utf-8", newline="\n").write(
        '{\n\t"FileVersion": 3,\n\t"Version": 1,\n\t"VersionName": "0.1",\n\t"FriendlyName": "Voyage stand-ins (generated, local only)",\n'
        '\t"Description": "Editor-side stand-ins for the game classes, generated from the usmap. Never shipped; the cooked assets reference /Script/%s.",\n'
        '\t"Category": "Editor",\n\t"CanContainContent": false,\n\t"Installed": false,\n'
        '\t"Modules": [\n\t\t{\n\t\t\t"Name": "%s",\n\t\t\t"Type": "Runtime",\n\t\t\t"LoadingPhase": "Default"\n\t\t}\n\t]\n}\n' % (args.module, args.module))
    open(os.path.join(src, args.module + ".Build.cs"), "w", encoding="utf-8", newline="\n").write(
        'using UnrealBuildTool;\n\npublic class %s : ModuleRules\n{\n\tpublic %s(ReadOnlyTargetRules Target) : base(Target)\n\t{\n'
        '\t\tPCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;\n\t\tPublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });\n\t}\n}\n' % (args.module, args.module))
    open(os.path.join(src, "Private", args.module + ".cpp"), "w", encoding="utf-8", newline="\n").write(
        '#include "Modules/ModuleManager.h"\n\nIMPLEMENT_MODULE(FDefaultModuleImpl, %s)\n' % args.module)
    open(os.path.join(src, "Public", "VoyageStubs.h"), "w", encoding="utf-8", newline="\n").write(header)
    print("plugin:", out)
    print("classes: %d, structs: %d, enums: %d, properties: %d" % (len(cls_ordered), len(ordered), len(gen_enums),
          sum(len(u.schemas[n]["props"]) for n in cls_ordered + ordered)))
    print("classes:", ", ".join(cls_ordered))
    print("structs:", ", ".join(ordered))
    print("enums:", ", ".join(gen_enums))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
