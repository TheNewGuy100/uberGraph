# Credits

This project builds on the work of others. All of the following are MIT licensed; where code is copied, the original copyright and licence notice must be kept next to it. So far **no code has been copied**; the entries below are ideas and prior art we studied.

| Project | What we learned from it |
|---|---|
| [UE4SS-RE/RE-UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) | The scripting system everything here runs on (Lua mods, game-thread execution, dumpers) |
| [littleRabbit94/ue4ss-bridge](https://github.com/littleRabbit94/ue4ss-bridge) | File-polling bridge on the game thread, read-only mode enforced inside the mod, crash breadcrumb, skipping soft-pointer reads, objects re-resolved by name |
| [glitchbunny0/unreal-vibe-modding](https://github.com/glitchbunny0/unreal-vibe-modding) and [ue4ss-devbridge](https://github.com/glitchbunny0/ue4ss-devbridge) | Request journal that names the request which killed the game, an instruction budget as a request timeout, a reflection index, a mock UE4SS for tests |
| [rkuhn153/unreal-engine-mcp](https://github.com/rkuhn153/unreal-engine-mcp), [4piu/UE4SS-mcp](https://github.com/4piu/UE4SS-mcp), [pd3-modding/RE-UE4SS-MCP](https://github.com/pd3-modding/RE-UE4SS-MCP) | Different ways to expose a running game to an MCP client (file IPC, installable bridge mod, server inside UE4SS) |
| [Glmour/ue-live-bridge](https://github.com/Glmour/ue-live-bridge) | The idea that a check must be shown able to fail before its pass means anything |
| [drpsyko101/MotorTownMods](https://github.com/drpsyko101/MotorTownMods) | An HTTP server from UE4SS Lua using LuaSocket (considered, not used) |

The notes above come from reading READMEs and, for two of them, the source code; we did not run their code.
