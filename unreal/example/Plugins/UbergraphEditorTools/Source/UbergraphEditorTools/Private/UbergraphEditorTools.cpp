#include "Modules/ModuleManager.h"

DEFINE_LOG_CATEGORY_STATIC(LogUbergraphEditorTools, Log, All);

class FUbergraphEditorToolsModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		UE_LOG(LogUbergraphEditorTools, Display, TEXT("UbergraphEditorTools loaded (no tools yet)"));
	}
};

IMPLEMENT_MODULE(FUbergraphEditorToolsModule, UbergraphEditorTools)
