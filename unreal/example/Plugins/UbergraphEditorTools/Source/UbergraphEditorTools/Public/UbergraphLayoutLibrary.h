#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "UbergraphLayoutLibrary.generated.h"

/**
 * Editor-side reflection dump used to check that a stand-in class has the same serialized layout as the game's class
 * (see docs/COOKED-ASSET-PIPELINE.md). Never cooked into the mod.
 */
UCLASS()
class UBERGRAPHEDITORTOOLS_API UUbergraphLayoutLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * JSON text describing a class or struct and its super chain: for each struct in the chain its own properties in declaration
	 * order (name, a type string in the same notation as tools/usmap/usmap_tool.py, array dimension, flags).
	 * StructPath is a full path such as "/Script/Engine.Actor"; a bare name is tried as a fallback.
	 */
	UFUNCTION(BlueprintCallable, Category = "Ubergraph|Layout")
	static FString DumpStructLayout(const FString& StructPath);
};
