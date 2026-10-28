"""Print the widget tree JSON returned by UMGToolSet.GetWidgets (read from stdin)."""
import json
import sys


def name(x):
    if isinstance(x, dict):
        x = x.get("refPath", "")
    return str(x).split(".")[-1]


result = json.loads(sys.stdin.read())["returnValue"]
widgets = result.get("widgets") or result.get("Widgets") or []
for w in widgets:
    print(w.get("widgetName"), "|", name(w.get("parent")), "|", name(w.get("widgetClassPath")), "| var =", w.get("bIsVariable"))
print(len(widgets), "widgets")
