using UnrealBuildTool;

// Empty game module: the project is a C++ project only so the editor plugin below can be built. Nothing the game
// loads may depend on this module, because the game does not have /Script/ExampleProject.
public class ExampleProject : ModuleRules
{
	public ExampleProject(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
	}
}
