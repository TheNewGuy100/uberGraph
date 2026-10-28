-- UberGraphLog: the standard logger for Ubergraph mods (see bridge/README.md, "Logging conventions").
--
--   local Log = require("UberGraphLog")
--   local log = Log.new("[uberGraph] Probes/chest")
--   log.info("loaded")                      ->  [uberGraph] Probes/chest: loaded
--   log.warn("no pawn (%s)", reason)        ->  [uberGraph] Probes/chest: WARN no pawn (...)
--   log.error("boom")                       ->  [uberGraph] Probes/chest: ERROR boom
--   log.try("press", fn, ...)               pcall that logs a failure as ERROR and returns ok, result
--
-- Plain text only: ANSI escape sequences and other control characters are removed from every message, so the log stays easy to read
-- with grep and costs no context on useless characters. Colour belongs to the viewer (tools/term/uber_term.py), not to the log.
-- Installed to <ue4ss>/Mods/shared/UberGraphLog/ by tools/bridge/install_bridge.py.
local M = {}

local WORD = {info = "", warn = "WARN ", error = "ERROR "}

-- Drops ANSI escape sequences, then every control character except tab and line feed.
local function clean(text)
    text = tostring(text)
    text = text:gsub("\27%[[%d;]*%a", "")
    text = text:gsub("[\0-\8\11-\31\127]", "")
    return text
end
M.clean = clean

function M.format(prefix, level, message, ...)
    if select("#", ...) > 0 then
        local ok, text = pcall(string.format, message, ...)
        if ok then message = text end
    end
    return tostring(prefix) .. ": " .. WORD[level] .. clean(message)
end

function M.new(prefix)
    local log = {prefix = prefix}
    local function emit(level, message, ...)
        print(M.format(prefix, level, message, ...) .. "\n")
    end
    function log.info(message, ...) emit("info", message, ...) end
    function log.warn(message, ...) emit("warn", message, ...) end
    function log.error(message, ...) emit("error", message, ...) end
    function log.try(label, fn, ...)
        local ok, result = pcall(fn, ...)
        if not ok then emit("error", "%s failed safely: %s", label, tostring(result)) end
        return ok, result
    end
    return log
end

return M
