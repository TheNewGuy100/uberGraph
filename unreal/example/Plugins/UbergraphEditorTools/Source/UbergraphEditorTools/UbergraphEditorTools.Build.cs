using UnrealBuildTool;

public class UbergraphEditorTools : ModuleRules
{
	public UbergraphEditorTools(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		// UnrealEd, UMG, UMGEditor and MovieScene join here when the first tool needs them.
	}
}
