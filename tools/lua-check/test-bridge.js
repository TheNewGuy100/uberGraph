// Behaviour tests for bridge/uber-bridge/Scripts/main.lua in the fengari Lua VM, against a fake UE4SS API and an in-memory file system.
// No game needed. Covers the request protocol, argument validation, the risk gates (allow_load, allow_hooks, allow_console), the console
// command allow-list and the cvar readings. Usage: node tools/lua-check/test-bridge.js        Exit code 1 if a check fails.
const fs = require("fs");
const path = require("path");
const {lua, lauxlib, lualib, to_luastring} = require("fengari");

const root = path.resolve(__dirname, "..", "..");
const source = fs.readFileSync(path.join(root, "bridge", "uber-bridge", "Scripts", "main.lua"), "utf8");

const test = String.raw`
-- fake file system -------------------------------------------------------------------------------------------------------
local FS = {}
io = {open = function(p, mode)
    local writing = mode:find("w") ~= nil
    if not writing and FS[p] == nil then return nil end
    local handle = {buffer = writing and "" or FS[p]}
    function handle:read(n)
        if n == "*a" or n == "a" then return self.buffer end
        return self.buffer:sub(1, n)
    end
    function handle:write(text) self.buffer = self.buffer .. text end
    function handle:close() if writing then FS[p] = self.buffer end end
    return handle
end}
os.remove = function(p) FS[p] = nil end
os.rename = function(a, b) FS[b] = FS[a]; FS[a] = nil end

-- fake UE objects and API ------------------------------------------------------------------------------------------------
local executed = {}
local function fake(fullName, extra)
    local o = {IsValid = function() return true end, GetFullName = function() return fullName end}
    for k, v in pairs(extra or {}) do o[k] = v end
    return o
end
local controller = fake("PlayerController /Game/Maps/Test.Test:PersistentLevel.PC_0")
local kismet = fake("KismetSystemLibrary /Script/Engine.Default__KismetSystemLibrary", {
    GetConsoleVariableFloatValue = function(self, name) return 100.0 end,
    GetConsoleVariableIntValue = function(self, name) return 100 end,
    GetConsoleVariableBoolValue = function(self, name) return false end,
    ExecuteConsoleCommand = function(self, world, command, pc) executed[#executed + 1] = command end,
})
local registry = {["/Script/Engine.Default__KismetSystemLibrary"] = kismet}
StaticFindObject = function(p) return registry[p] end
FindAllOf = function(class) if class == "PlayerController" then return {controller} end return nil end
RegisterHook = function() return 1, 2 end
FName = function(s) return s end
local loopFunction
LoopAsync = function(ms, fn) loopFunction = fn end
ExecuteInGameThread = function(fn) fn() end
package.preload["UEHelpers"] = function()
    return {GetPlayerController = function() return controller end, GetWorld = function() return fake("World /Game/Maps/Test.Test") end}
end
print = function() end

-- load the bridge as if UE4SS did, from a path that contains brackets and a space ----------------------------------------------
local chunk = assert(load(BRIDGE_SOURCE, "@/fake/ue4ss/Mods/[uberGraph] Bridge/Scripts/main.lua"))
chunk()
local BASE = "/fake/ue4ss/Mods/[uberGraph] Bridge"
local failures = {}
local function check(name, condition)
    if not condition then failures[#failures + 1] = name end
end
local counter = 0
local function ask(op, args, rawId)
    counter = counter + 1
    local id = rawId or string.format("req%05d", counter)
    local lines = {"id=" .. id, "op=" .. op}
    for k, v in pairs(args or {}) do lines[#lines + 1] = "arg." .. k .. "=" .. v end
    FS[BASE .. "/io/request.txt"] = table.concat(lines, "\n") .. "\n"
    loopFunction()
    return FS[BASE .. "/io/response.json"] or ""
end
local function has(text, part) return text:find(part, 1, true) ~= nil end
local function settings(text) FS[BASE .. "/settings.txt"] = text end

-- protocol -------------------------------------------------------------------------------------------------------------
loopFunction() -- the first tick writes the heartbeat
check("heartbeat written with the version", (FS[BASE .. "/io/heartbeat.txt"] or ""):match("^%d+ %d+%.%d+%.%d+$") ~= nil)
local r = ask("ping")
check("ping ok", has(r, '"ok":true') and has(r, '"version":"'))
check("ping echoes protocol and id", has(r, '"protocol":1') and has(r, '"id":"req00001"'))
r = ask("nope")
check("unknown op rejected", has(r, '"ok":false') and has(r, "unknown op: nope"))
check("unknown op lists the new operations", has(r, "cvar_get") and has(r, "console_exec"))
r = ask("ping", nil, "x")
check("invalid id rejected", has(r, '"id":"invalid"') and has(r, "missing or invalid id"))
FS[BASE .. "/io/request.txt"] = string.rep("a", 9000)
loopFunction()
check("oversized request rejected", has(FS[BASE .. "/io/response.json"], "request too large"))
check("request file is consumed", FS[BASE .. "/io/request.txt"] == nil)

-- reading --------------------------------------------------------------------------------------------------------------
r = ask("find_all", {})
check("find_all needs a class", has(r, "arg 'class' is required"))
r = ask("find_all", {class = "PlayerController"})
check("find_all finds the fake controller", has(r, '"count":1') and has(r, "PC_0"))
r = ask("find_all", {class = "Nothing"})
check("find_all with no match is empty", has(r, '"count":0'))
r = ask("describe_class", {})
check("describe_class needs an argument", has(r, '"ok":false'))

-- cvar_get ---------------------------------------------------------------------------------------------------------------
r = ask("cvar_get", {name = "r.ScreenPercentage"})
check("cvar_get float and int", has(r, '"float":100') and has(r, '"int":100'))
check("cvar_get keeps a false bool as false (no 'error: false')", has(r, '"bool":false') and not has(r, "error: false"))
r = ask("cvar_get", {name = "r.x;y"})
check("cvar_get rejects odd names", has(r, '"ok":false') and has(r, "console variable name"))
r = ask("cvar_get", {})
check("cvar_get needs a name", has(r, '"ok":false'))

-- risk gates: off by default ---------------------------------------------------------------------------------------------
r = ask("load_asset", {path = "/Game/X/Y"})
check("load_asset is off by default", has(r, "load_asset is disabled"))
r = ask("watch_function", {action = "list"})
check("watch_function is off by default", has(r, "watch_function is disabled"))
r = ask("console_exec", {command = "stat fps"})
check("console_exec is off by default", has(r, "console_exec is disabled"))
check("nothing ran while it was off", #executed == 0)

-- console_exec with the option on ----------------------------------------------------------------------------------------
settings("# comment\nallow_console=true\n")
r = ask("console_exec", {command = "stat fps"})
check("stat fps runs", has(r, '"ok":true') and has(r, '"executed":"stat fps"') and executed[#executed] == "stat fps")
r = ask("console_exec", {command = "r.ScreenPercentage 100"})
check("r. cvar runs", has(r, '"ok":true') and executed[#executed] == "r.ScreenPercentage 100")
r = ask("console_exec", {command = "Stat Unit"})
check("first word is case-insensitive", has(r, '"ok":true') and executed[#executed] == "Stat Unit")
local ran = #executed
for _, bad in ipairs({"quit", "exit", "open /Game/Maps/X", "servertravel X", "stat fps; quit", "stat fps|x", "gc.CollectGarbage 1", "", string.rep("r.a ", 40)}) do
    r = ask("console_exec", {command = bad})
    check("refused: [" .. bad:sub(1, 20) .. "]", has(r, '"ok":false'))
end
check("no refused command was executed", #executed == ran)

-- settings are read on every use -------------------------------------------------------------------------------------------
settings("allow_console=false\n")
r = ask("console_exec", {command = "stat fps"})
check("turning the option off takes effect without a restart", has(r, "console_exec is disabled"))
settings("allow_console = true  \n")
r = ask("console_exec", {command = "stat fps"})
check("settings tolerate spaces around =", has(r, '"ok":true'))

-- hooks gate and path validation ---------------------------------------------------------------------------------------------
settings("allow_hooks=true\n")
r = ask("watch_function", {action = "start", path = "not a path"})
check("watch_function validates the path", has(r, "must look like"))
r = ask("watch_function", {action = "list"})
check("watch_function list works when on", has(r, '"ok":true') and has(r, '"watchers":[]'))
settings("allow_hooks=false\n")
r = ask("watch_function", {action = "list"})
check("watch_function off again", has(r, "watch_function is disabled"))

return table.concat(failures, "; ")
`;

const L = lauxlib.luaL_newstate();
lualib.luaL_openlibs(L);
lua.lua_pushstring(L, to_luastring(source));
lua.lua_setglobal(L, to_luastring("BRIDGE_SOURCE"));
if (lauxlib.luaL_dostring(L, to_luastring(test)) !== lua.LUA_OK) {
    console.error("lua error:", lua.lua_tojsstring(L, -1));
    process.exit(1);
}
const failures = lua.lua_tojsstring(L, -1);
if (failures) {
    console.error("FAIL " + failures);
    process.exit(1);
}
console.log("ok     bridge: all checks passed");
