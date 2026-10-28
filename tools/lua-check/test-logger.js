// Behaviour tests for lua/shared/UberGraphLog/UberGraphLog.lua, run in the fengari Lua VM (UE4SS runs Lua 5.4; fengari is 5.3, enough here).
// Usage: node tools/lua-check/test-logger.js        Exit code 1 if a check fails.
const fs = require("fs");
const path = require("path");
const {lua, lauxlib, lualib, to_luastring} = require("fengari");

const source = fs.readFileSync(path.resolve(__dirname, "..", "..", "lua", "shared", "UberGraphLog", "UberGraphLog.lua"), "utf8");

const test = String.raw`
local lines = {}
print = function(text) lines[#lines + 1] = text end
package.preload["UberGraphLog"] = function() return (load(MODULE_SOURCE, "UberGraphLog"))() end
local Log = require("UberGraphLog")
local log = Log.new("[uberGraph] Probes/chest")
local failures = {}
local function check(name, got, want)
    if got ~= want then failures[#failures + 1] = name .. ": got [" .. tostring(got) .. "] want [" .. tostring(want) .. "]" end
end
local LF = string.char(10)

log.info("loaded")
check("info line", lines[#lines], "[uberGraph] Probes/chest: loaded" .. LF)
log.warn("no pawn")
check("warn line", lines[#lines], "[uberGraph] Probes/chest: WARN no pawn" .. LF)
log.error("boom")
check("error line", lines[#lines], "[uberGraph] Probes/chest: ERROR boom" .. LF)
log.info("%d of %s", 3, "five")
check("format args", lines[#lines], "[uberGraph] Probes/chest: 3 of five" .. LF)
log.info("100%")
check("percent without args is kept", lines[#lines], "[uberGraph] Probes/chest: 100%" .. LF)
log.info("slogan " .. string.char(27) .. "[1;36mBuild. Bridge. Play." .. string.char(27) .. "[0m ok")
check("ansi removed", lines[#lines], "[uberGraph] Probes/chest: slogan Build. Bridge. Play. ok" .. LF)
log.info("a" .. string.char(0) .. "b" .. string.char(8) .. "c" .. string.char(13) .. "d" .. string.char(127) .. "e")
check("control characters removed", lines[#lines], "[uberGraph] Probes/chest: abcde" .. LF)
log.info("tab" .. string.char(9) .. "kept" .. LF .. "second line")
check("tab and line feed kept", lines[#lines], "[uberGraph] Probes/chest: tab" .. string.char(9) .. "kept" .. LF .. "second line" .. LF)
log.info(nil)
check("nil message", lines[#lines], "[uberGraph] Probes/chest: nil" .. LF)

local before = #lines
local ok, result = log.try("press", function(a, b) return a + b end, 2, 3)
check("try ok", ok, true)
check("try result", result, 5)
check("try ok logs nothing", #lines, before)
local ok2 = log.try("press", function() error("bad thing") end)
check("try failure returns false", ok2, false)
check("try failure logged as ERROR", lines[#lines]:match("^%[uberGraph%] Probes/chest: ERROR press failed safely: .*bad thing") ~= nil, true)

check("two loggers keep their own prefix", Log.format("[x]", "warn", "m"), "[x]: WARN m")
return table.concat(failures, "; ")
`;

const L = lauxlib.luaL_newstate();
lualib.luaL_openlibs(L);
lua.lua_pushstring(L, to_luastring(source));
lua.lua_setglobal(L, to_luastring("MODULE_SOURCE"));
if (lauxlib.luaL_dostring(L, to_luastring(test)) !== lua.LUA_OK) {
    console.error("lua error:", lua.lua_tojsstring(L, -1));
    process.exit(1);
}
const failures = lua.lua_tojsstring(L, -1);
if (failures) {
    console.error("FAIL " + failures);
    process.exit(1);
}
console.log("ok     UberGraphLog: 14 checks passed");
