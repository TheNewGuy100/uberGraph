#include "UbergraphLayoutLibrary.h"

#include "UObject/UnrealType.h"
#include "UObject/Class.h"
#include "UObject/UObjectGlobals.h"

namespace
{
	FString JsonEscape(const FString& In)
	{
		FString Out;
		for (TCHAR C : In)
		{
			if (C == TEXT('"') || C == TEXT('\\')) { Out.AppendChar(TEXT('\\')); }
			Out.AppendChar(C);
		}
		return Out;
	}

	// Same notation as usmap_tool.py: Bool, Struct(Vector), Enum(EFoo), Array<...>, Map<K,V>, Optional<...>.
	FString TypeToString(const FProperty* Property)
	{
		if (const FStructProperty* S = CastField<FStructProperty>(Property)) { return FString::Printf(TEXT("Struct(%s)"), *S->Struct->GetName()); }
		if (const FEnumProperty* E = CastField<FEnumProperty>(Property)) { return FString::Printf(TEXT("Enum(%s)"), E->GetEnum() ? *E->GetEnum()->GetName() : TEXT("?")); }
		if (const FByteProperty* B = CastField<FByteProperty>(Property)) { return B->Enum ? FString::Printf(TEXT("Byte(Enum %s)"), *B->Enum->GetName()) : FString(TEXT("Byte")); }
		if (const FArrayProperty* A = CastField<FArrayProperty>(Property)) { return FString::Printf(TEXT("Array<%s>"), *TypeToString(A->Inner)); }
		if (const FSetProperty* S = CastField<FSetProperty>(Property)) { return FString::Printf(TEXT("Set<%s>"), *TypeToString(S->ElementProp)); }
		if (const FMapProperty* M = CastField<FMapProperty>(Property)) { return FString::Printf(TEXT("Map<%s,%s>"), *TypeToString(M->KeyProp), *TypeToString(M->ValueProp)); }
		if (const FOptionalProperty* O = CastField<FOptionalProperty>(Property)) { return FString::Printf(TEXT("Optional<%s>"), *TypeToString(O->GetValueProperty())); }
		FString Name = Property->GetClass()->GetName();
		Name.RemoveFromEnd(TEXT("Property"));
		return Name;
	}
}

FString UUbergraphLayoutLibrary::DumpStructLayout(const FString& StructPath)
{
	UStruct* Root = FindObject<UStruct>(nullptr, *StructPath);
	if (!Root) { Root = FindFirstObject<UStruct>(*StructPath, EFindFirstObjectOptions::NativeFirst); }
	if (!Root)
	{
		return FString::Printf(TEXT("{\"requested\":\"%s\",\"found\":false}"), *JsonEscape(StructPath));
	}

	FString Json = FString::Printf(TEXT("{\"requested\":\"%s\",\"found\":true,\"path\":\"%s\",\"chain\":["), *JsonEscape(StructPath), *JsonEscape(Root->GetPathName()));
	TArray<const UStruct*> Chain;
	for (const UStruct* S = Root; S; S = S->GetSuperStruct()) { Chain.Add(S); }
	for (int32 i = 0; i < Chain.Num(); ++i) { Json += FString::Printf(TEXT("%s\"%s\""), i ? TEXT(",") : TEXT(""), *Chain[i]->GetName()); }
	Json += TEXT("],\"structs\":{");
	for (int32 i = 0; i < Chain.Num(); ++i)
	{
		Json += FString::Printf(TEXT("%s\"%s\":{\"path\":\"%s\",\"props\":["), i ? TEXT(",") : TEXT(""), *Chain[i]->GetName(), *JsonEscape(Chain[i]->GetPathName()));
		int32 Index = 0;
		for (TFieldIterator<FProperty> It(Chain[i], EFieldIteratorFlags::ExcludeSuper); It; ++It, ++Index)
		{
			const FProperty* P = *It;
			Json += FString::Printf(TEXT("%s{\"index\":%d,\"name\":\"%s\",\"type\":\"%s\",\"array\":%d,\"transient\":%s,\"editor_only\":%s}"),
				Index ? TEXT(",") : TEXT(""), Index, *JsonEscape(P->GetName()), *JsonEscape(TypeToString(P)), P->ArrayDim,
				P->HasAnyPropertyFlags(CPF_Transient) ? TEXT("true") : TEXT("false"),
				P->IsEditorOnlyProperty() ? TEXT("true") : TEXT("false"));
		}
		Json += TEXT("]}");
	}
	Json += TEXT("}}");
	return Json;
}
