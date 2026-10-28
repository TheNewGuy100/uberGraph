"""Names shared by the bridge tools: the mod folder as the game's UE4SS mod list shows it, and where its source lives in this repository."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MOD_NAME = "[uberGraph] Bridge"          # folder name inside <ue4ss>/Mods, the name UE4SS lists
SOURCE = os.path.join(ROOT, "bridge", "uber-bridge")
LEGACY_NAME = "ModDevBridge"             # the folder name before the rename


def mod_dir(ue4ss):
    return os.path.join(ue4ss, "Mods", MOD_NAME)
