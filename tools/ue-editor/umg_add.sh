#!/bin/bash
# Add one widget to a Widget Blueprint via UMGToolSet. Usage:
#   umg_add.sh <session> <asset path without _C> <UMG class, e.g. Border> <name> <parent name | none>
S="$1"; BP="$2"; CLS="$3"; NAME="$4"; PARENT="$5"
HERE="$(dirname "$0")"
if [ "$PARENT" = "none" ]; then P=""; else P=",\"parentWidget\":{\"refPath\":\"$BP:WidgetTree.$PARENT\"}"; fi
"$HERE/mcp_call.sh" "$S" call "{\"toolset_name\":\"UMGToolSet.UMGToolSet\",\"tool_name\":\"AddWidget\",\"arguments\":{\"widgetBlueprint\":{\"refPath\":\"$BP\"},\"widgetClass\":{\"refPath\":\"/Script/UMG.$CLS\"},\"widgetDisplayName\":\"$NAME\"$P}}"
