"""Runs inside the editor: dumps the reflected layout of the given classes/structs (needs the UbergraphEditorTools plugin built).

Set LAYOUT_NAMES (comma list of bare names or full paths) and LAYOUT_OUT (output JSON path) before running it, for example:
    python tools/ue-editor/ue_remote.py "LAYOUT_NAMES='Actor,Vector'; LAYOUT_OUT='C:/tmp/layouts.json'; exec(open(r'tools/ue-editor/examples/dump_layouts.py', encoding='utf-8').read())"
The function is called through call_method on the class default object, so it works right after a Live Coding compile (the Python
module `unreal` does not gain a new class until the editor restarts, but the class itself is already registered).
Compare with the game's mapping using tools/usmap/compare_layout.py.
"""
import json

import unreal

names = [n.strip() for n in str(globals().get('LAYOUT_NAMES', 'Actor')).split(',') if n.strip()]
out_path = globals().get('LAYOUT_OUT', 'layouts.json')
library = None
for path in ('/Script/UbergraphEditorTools.UbergraphLayoutLibrary', '/Script/VanillaPlusEditorTools.VanillaPlusLayoutLibrary'):  # the second is the old name
    cls = unreal.load_class(None, path)
    if cls:
        library = unreal.get_default_object(cls)
        break
if library is None:
    raise SystemExit('the UbergraphEditorTools plugin is not built in this project (see unreal/example/README.md)')
results = [json.loads(library.call_method('DumpStructLayout', args=(name,))) for name in names]
with open(out_path, 'w', encoding='utf-8') as fh:
    json.dump({'engine': unreal.SystemLibrary.get_engine_version(), 'layouts': results}, fh, indent=1)
print('wrote', out_path, 'with', len(results), 'layouts;', sum(1 for r in results if not r.get('found')), 'not found')
