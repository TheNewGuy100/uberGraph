-- [uberGraph] Bridge: development bridge for UE4SS games. Development use only; never ship it to players.
--
-- A client writes io/request.txt (key=value lines), this mod runs the request on the GAME THREAD and writes io/response.json.
-- Read-only by default; optional, separately approved asset loads and observe-only hooks. No eval, no value overrides. Objects are found
-- again by name on every request (a cached UObject was garbage collected and crashed the game in an earlier project).
-- Ideas credited in CREDITS.md (ue4ss-bridge, unreal-vibe-modding: polling, game thread, breadcrumb, soft-pointer rule).
local VERSION, PROTOCOL = "0.1.3", 1
local POLL_MS = 100
local MAX_REQUEST_BYTES = 8192
local MAX_LIST = 200
local MAX_STRING = 4000

local UEHelpers = require("UEHelpers")

-- Mod folder from this script's own path (.../Mods/[uberGraph] Bridge/Scripts/main.lua); falls back to the usual relative path.
local function modDir()
    local ok, info = pcall(function() return debug.getinfo(1, "S") end)
    local source = ok and info and info.source or ""
    local dir = source:match("^@(.*)[/\\][Ss]cripts[/\\][^/\\]+$")
    return dir or "ue4ss/Mods/[uberGraph] Bridge"
end
local BASE = modDir():gsub("\\", "/")
local IO = BASE .. "/io/"
local REQUEST, RESPONSE, HEARTBEAT, LASTOP = IO .. "request.txt", IO .. "response.json", IO .. "heartbeat.txt", IO .. "lastop.log"

local SETTINGS = BASE .. "/settings.txt"

-- Settings are read from settings.txt on every use (no restart needed). Missing file or key means the safe default (off).
local function readSettings()
    local out = {}
    local fh = io.open(SETTINGS, "rb")
    if not fh then return out end
    local text = fh:read("*a") or ""
    fh:close()
    for line in text:gmatch("[^\r\n]+") do
        if not line:match("^%s*[#;]") then
            local key, value = line:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
            if key then out[key] = value end
        end
    end
    return out
end

local startedAt = os.time()
local busy = false

local function log(message) print("[uberGraph] bridge: " .. tostring(message) .. "\n") end

-- JSON encoder (responses only; requests are plain key=value lines, so no decoder and no code is ever executed) -----------
local ESCAPES = {['"'] = '\\"', ["\\"] = "\\\\", ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t"}
local function jsonString(s)
    s = tostring(s)
    if #s > MAX_STRING then s = s:sub(1, MAX_STRING) .. "...[truncated]" end
    s = s:gsub('[%c"\\]', function(c) return ESCAPES[c] or string.format("\\u%04x", c:byte()) end)
    return '"' .. s .. '"'
end
local function encode(value)
    local kind = type(value)
    if value == nil then return "null"
    elseif kind == "boolean" then return value and "true" or "false"
    elseif kind == "number" then
        if value ~= value or value == math.huge or value == -math.huge then return "null" end
        return (math.type(value) == "integer") and tostring(value) or string.format("%.9g", value)
    elseif kind == "string" then return jsonString(value)
    elseif kind == "table" then
        if #value > 0 or next(value) == nil then
            local parts = {}
            for i = 1, #value do parts[i] = encode(value[i]) end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        local keys = {}
        for k in pairs(value) do keys[#keys + 1] = tostring(k) end
        table.sort(keys)
        local parts = {}
        for _, k in ipairs(keys) do parts[#parts + 1] = jsonString(k) .. ":" .. encode(value[k]) end
        return "{" .. table.concat(parts, ",") .. "}"
    end
    return jsonString("<" .. kind .. ">")
end

local function writeFile(path, text)
    local fh = io.open(path, "wb")
    if not fh then return false end
    fh:write(text)
    fh:close()
    return true
end

local function writeResponse(id, payload)
    payload.id = id
    payload.protocol = PROTOCOL
    local tmp = RESPONSE .. ".tmp"
    if not writeFile(tmp, encode(payload)) then log("cannot write " .. tmp); return end
    os.remove(RESPONSE)
    os.rename(tmp, RESPONSE)
end

-- Reading objects and properties -------------------------------------------------------------------------------------------
local function valid(object)
    if object == nil then return false end
    local ok, result = pcall(function() return object:IsValid() end)
    return ok and result == true
end

-- "pc", "pawn", "pcm", "world", "cdo:/Script/Mod.Class" (class default object), a full path ("/Game/...") or what GetFullName() prints ("Class /Path...").
local function resolveObject(ref)
    if ref == "pc" then return UEHelpers.GetPlayerController() end
    if ref == "pawn" then local pc = UEHelpers.GetPlayerController(); return valid(pc) and pc.Pawn or nil end
    if ref == "pcm" then local pc = UEHelpers.GetPlayerController(); return valid(pc) and pc.PlayerCameraManager or nil end
    if ref == "world" then return UEHelpers.GetWorld() end
    local cdoPath = ref:match("^cdo:(.+)$")
    if cdoPath then
        local okClass, class = pcall(StaticFindObject, cdoPath)
        if not (okClass and valid(class)) then return nil end
        local okCdo, cdo = pcall(function() return class:GetCDO() end)
        return okCdo and cdo or nil
    end
    local path = ref:match("^%S+ (/.*)$") or ref
    if path:sub(1, 1) ~= "/" then return nil end
    local ok, object = pcall(StaticFindObject, path)
    return ok and object or nil
end

-- Soft pointers crash UE4SS's property reader (seen in other projects), so the property type is checked first.
local SKIP_TYPES = {SoftObjectProperty = true, SoftClassProperty = true, LazyObjectProperty = true}
local function findProperty(object, name)
    local foundType, foundProp
    local ok = pcall(function()
        local class = object:GetClass()
        for _ = 1, 12 do
            -- GetSuperStruct() returns an invalid wrapper (not nil) past the top of the chain; calling into it crashed the game
            -- on 2026-10-26 (access violation, only when the property was NOT found). Check IsValid and stop at UObject.
            if foundType or not valid(class) then break end
            if class:GetFullName() == "Class /Script/CoreUObject.Object" then break end
            class:ForEachProperty(function(property)
                if not foundType and property:GetFName():ToString() == name then
                    foundType, foundProp = property:GetClass():GetFName():ToString(), property
                end
            end)
            class = class:GetSuperStruct()
        end
    end)
    if not ok then return nil, nil end
    return foundType, foundProp
end
local function propertyTypeName(object, name)
    local typeName = findProperty(object, name)
    return typeName
end

local function describe(value)
    local kind = type(value)
    if kind == "number" or kind == "boolean" or kind == "string" or kind == "nil" then return value end
    local ok, text = pcall(function() return value:GetFullName() end)
    if ok and type(text) == "string" then return {object = text} end
    ok, text = pcall(function() return value:ToString() end)
    if ok and type(text) == "string" then return text end
    for _, fields in ipairs({{"X", "Y", "Z", "W"}, {"Pitch", "Yaw", "Roll"}, {"R", "G", "B", "A"}}) do
        local out, any = {}, false
        for _, f in ipairs(fields) do
            local okF, v = pcall(function() return value[f] end)
            if okF and type(v) == "number" then out[f] = v; any = true end
        end
        if any then return out end
    end
    return "<" .. kind .. ">"
end

-- Operations (all read-only) -----------------------------------------------------------------------------------------------
local OPS = {}

OPS.ping = function()
    return {version = VERSION, uptime_s = os.time() - startedAt}
end

OPS.status = function()
    local out = {}
    local world = UEHelpers.GetWorld()
    out.world = valid(world) and world:GetFullName() or nil
    local pc = UEHelpers.GetPlayerController()
    out.player_controller = valid(pc) and pc:GetFullName() or nil
    local pawn = valid(pc) and pc.Pawn or nil
    out.pawn = valid(pawn) and pawn:GetFullName() or nil
    return out
end

OPS.find_all = function(args)
    local class = args.class
    if not class or class == "" then error("arg 'class' is required") end
    local limit = math.min(tonumber(args.limit) or 20, MAX_LIST)
    local list = FindAllOf(class) or {}
    local items = {}
    for i = 1, math.min(#list, limit) do
        local ok, name = pcall(function() return list[i]:GetFullName() end)
        items[#items + 1] = ok and name or "<unreadable>"
    end
    return {count = #list, returned = #items, truncated = #list > #items, items = items}
end

OPS.get = function(args)
    local ref, names = args.object, args.property
    if not ref or not names then error("args 'object' and 'property' are required") end
    local object = resolveObject(ref)
    if not valid(object) then error("object not found: " .. ref) end
    local out, count = {}, 0
    for name in names:gmatch("[^,]+") do
        count = count + 1
        if count > 8 then out["..."] = "at most 8 properties per request"; break end
        name = name:match("^%s*(.-)%s*$")
        local typeName = propertyTypeName(object, name)
        if typeName == nil then out[name] = {error = "property not found"}
        elseif SKIP_TYPES[typeName] then out[name] = {skipped = typeName}
        else
            local ok, value = pcall(function() return object[name] end)
            out[name] = ok and {type = typeName, value = describe(value)} or {error = tostring(value)}
        end
    end
    return {object = object:GetFullName(), properties = out}
end


-- describe_class: the reflection listing our hand-written probes did with ForEachProperty / ForEachFunction. Own members of each
-- class up the chain (stops at UObject), names and property types only; nothing is read from instances.
OPS.describe_class = function(args)
    local class
    if args.class and args.class ~= "" then
        local ok, found = pcall(StaticFindObject, args.class)
        class = ok and found or nil
    elseif args.object then
        local object = resolveObject(args.object)
        class = valid(object) and object:GetClass() or nil
    else
        error("give arg 'class' (a path like /Script/Voyage.VoyageSkill) or arg 'object'")
    end
    if not valid(class) then error("class not found") end
    local limit = math.max(1, math.min(tonumber(args.limit) or 100, 400))
    local withFunctions = args.functions ~= "false"
    local chain = {}
    for _ = 1, 12 do
        if not valid(class) then break end
        local full = class:GetFullName()
        if full == "Class /Script/CoreUObject.Object" then break end
        local entry = {class = full, properties = {}, functions = {}}
        class:ForEachProperty(function(property)
            if #entry.properties < limit then
                entry.properties[#entry.properties + 1] = {name = property:GetFName():ToString(), type = property:GetClass():GetFName():ToString()}
            end
        end)
        if withFunctions then
            class:ForEachFunction(function(fn)
                if #entry.functions < limit then entry.functions[#entry.functions + 1] = fn:GetFName():ToString() end
            end)
        end
        chain[#chain + 1] = entry
        class = class:GetSuperStruct()
    end
    return {chain = chain}
end

-- get_array: elements of an array property (TArray), up to `limit`. Only properties whose reflected type is ArrayProperty.
OPS.get_array = function(args)
    local ref, name = args.object, args.property
    if not ref or not name then error("args 'object' and 'property' are required") end
    local object = resolveObject(ref)
    if not valid(object) then error("object not found: " .. ref) end
    local typeName = propertyTypeName(object, name)
    if typeName ~= "ArrayProperty" then error("property is not an ArrayProperty: " .. tostring(typeName)) end
    local limit = math.max(1, math.min(tonumber(args.limit) or 50, MAX_LIST))
    local array = object[name]
    local count = array:GetArrayNum()
    local items = {}
    for i = 1, math.min(count, limit) do
        local ok, value = pcall(function() return array[i] end)
        items[#items + 1] = ok and describe(value) or {error = tostring(value)}
    end
    return {object = object:GetFullName(), property = name, count = count, returned = #items, truncated = count > #items, items = items}
end


-- read: typed, bounded reader for structs, arrays and enums (depth <= 4, <= 100 array items). Struct fields come from the reflected
-- StructProperty; maps and sets are not supported and are reported as skipped. Soft pointers are skipped.
local function structFields(property)
    local fields = {}
    local ok = pcall(function()
        local struct = property:GetStruct()
        struct:ForEachProperty(function(p)
            if #fields < 40 then fields[#fields + 1] = {name = p:GetFName():ToString(), type = p:GetClass():GetFName():ToString(), prop = p} end
        end)
    end)
    return ok and fields or nil
end

-- Values handed to ForEach callbacks may be wrapped (RemoteUnrealParam); get() unwraps them.
local function unwrap(param)
    if type(param) == "userdata" then
        local ok, inner = pcall(function() return param:get() end)
        if ok and inner ~= nil then return inner end
    end
    return param
end

-- Key and value properties of a MapProperty; the method names differ between UE4SS builds, so several are tried.
local function mapProps(prop)
    local keyProp, valueProp
    for _, pair in ipairs({{"GetKeyProp", "GetValueProp"}, {"GetKeyProperty", "GetValueProperty"}}) do
        local ok = pcall(function() keyProp = prop[pair[1]](prop); valueProp = prop[pair[2]](prop) end)
        if ok and keyProp and valueProp then return keyProp, valueProp end
        keyProp, valueProp = nil, nil
    end
    return nil, nil
end

local readTyped
readTyped = function(value, typeName, prop, depth, limit)
    if SKIP_TYPES[typeName] then return {skipped = typeName} end
    if typeName == "SetProperty" then return {skipped = typeName .. " (not supported yet)"} end
    if typeName == "MapProperty" then
        if depth <= 0 then return {depth_limit = "map"} end
        local keyProp, valueProp = mapProps(prop)
        if not keyProp then return {skipped = "MapProperty (key/value property not reachable)"} end
        local keyType, valueType
        pcall(function()
            keyType = keyProp:GetClass():GetFName():ToString()
            valueType = valueProp:GetClass():GetFName():ToString()
        end)
        if not keyType or not valueType then return {skipped = "MapProperty (key/value type unreadable)"} end
        -- Soft pointers crash UE4SS's reader; refuse before touching any entry.
        if SKIP_TYPES[keyType] or SKIP_TYPES[valueType] then return {skipped = "MapProperty with soft pointers", key = keyType, value = valueType} end
        local entries, count = {}, 0
        local okIter, err = pcall(function()
            value:ForEach(function(k, v)
                count = count + 1
                if count <= limit then
                    entries[#entries + 1] = {key = readTyped(unwrap(k), keyType, keyProp, depth - 1, limit),
                                             value = readTyped(unwrap(v), valueType, valueProp, depth - 1, limit)}
                end
            end)
        end)
        if not okIter then return {unreadable = "map ForEach failed: " .. tostring(err), key = keyType, value = valueType} end
        return {key_type = keyType, value_type = valueType, count = count, returned = #entries, truncated = count > #entries, entries = entries}
    end
    if (typeName == "ObjectProperty" or typeName == "ClassProperty") and type(value) == "userdata" and not valid(value) then
        return {null_object = true}
    end
    if typeName == "StructProperty" then
        if depth <= 0 then return {depth_limit = "struct"} end
        local fields = structFields(prop)
        if not fields then return {unreadable = "struct fields"} end
        local out = {}
        for _, f in ipairs(fields) do
            local ok, v = pcall(function() return value[f.name] end)
            -- explicit branch: "ok and X or Y" turns a legitimate false/nil value into the error branch (seen with bool fields)
            if ok then out[f.name] = readTyped(v, f.type, f.prop, depth - 1, limit)
            else out[f.name] = {error = tostring(v)} end
        end
        return out
    end
    if typeName == "ArrayProperty" then
        if depth <= 0 then return {depth_limit = "array"} end
        local okN, count = pcall(function() return value:GetArrayNum() end)
        if not okN then return {unreadable = "array"} end
        local inner, innerType
        pcall(function() inner = prop:GetInner(); innerType = inner:GetClass():GetFName():ToString() end)
        local items = {}
        for i = 1, math.min(count, limit) do
            local ok, v = pcall(function() return value[i] end)
            if not ok then items[#items + 1] = {error = tostring(v)}
            elseif innerType then items[#items + 1] = readTyped(v, innerType, inner, depth - 1, limit)
            else items[#items + 1] = describe(v) end
        end
        return {count = count, returned = #items, truncated = count > #items, items = items}
    end
    if (typeName == "EnumProperty" or typeName == "ByteProperty") and type(value) == "number" then
        local name
        pcall(function() name = prop:GetEnum():GetNameByValue(value):ToString() end)
        return name and {value = value, name = name} or value
    end
    local described = describe(value)
    if described == "<userdata>" then return {unreadable = typeName} end
    return described
end

OPS.read = function(args)
    local ref, name = args.object, args.property
    if not ref or not name then error("args 'object' and 'property' are required") end
    local object = resolveObject(ref)
    if not valid(object) then error("object not found: " .. ref) end
    local depth = math.max(1, math.min(tonumber(args.depth) or 2, 4))
    local limit = math.max(1, math.min(tonumber(args.limit) or 20, 100))
    local typeName, prop = findProperty(object, name)
    if typeName == nil then error("property not found: " .. name) end
    local ok, value = pcall(function() return object[name] end)
    if not ok then error("read failed: " .. tostring(value)) end
    return {object = object:GetFullName(), property = name, type = typeName, value = readTyped(value, typeName, prop, depth, limit)}
end

OPS.find_object = function(args)
    local path = args.path
    if not path or path:sub(1, 1) ~= "/" then error("arg 'path' must start with /") end
    local ok, object = pcall(StaticFindObject, path)
    if not (ok and valid(object)) then return {found = false} end
    local out = {found = true, name = object:GetFullName()}
    pcall(function() out.class = object:GetClass():GetFullName() end)
    pcall(function() out.outer = object:GetOuter():GetFullName() end)
    return out
end

-- scan: a bounded, filtered pass over all objects (ForEachUObject). Needs `contains` and/or `class`; stops doing work after 2 s.
OPS.scan = function(args)
    local needle, classPrefix = args.contains, args.class
    if (not needle or needle == "") and (not classPrefix or classPrefix == "") then error("give arg 'contains' and/or arg 'class'") end
    local limit = math.max(1, math.min(tonumber(args.limit) or 50, MAX_LIST))
    local items, matches, visited, timedOut = {}, 0, 0, false
    local started = os.clock()
    ForEachUObject(function(object)
        if timedOut then return end
        visited = visited + 1
        if visited % 2000 == 0 and os.clock() - started > 2.0 then timedOut = true; return end
        local ok, name = pcall(function() return object:GetFullName() end)
        if ok and type(name) == "string" then
            local classOk = not classPrefix or classPrefix == "" or name:sub(1, #classPrefix + 1) == classPrefix .. " "
            local nameOk = not needle or needle == "" or name:find(needle, 1, true)
            if classOk and nameOk then
                matches = matches + 1
                if #items < limit then items[#items + 1] = name end
            end
        end
    end)
    return {matches = matches, returned = #items, truncated = matches > #items, visited = visited, timed_out = timedOut,
        elapsed_ms = math.floor((os.clock() - started) * 1000), items = items}
end


-- map_info: what the reflected MapProperty and the map value expose; iterates nothing. Used to learn the API of this UE4SS build.
OPS.map_info = function(args)
    local ref, name = args.object, args.property
    if not ref or not name then error("args 'object' and 'property' are required") end
    local object = resolveObject(ref)
    if not valid(object) then error("object not found: " .. ref) end
    local typeName, prop = findProperty(object, name)
    if typeName ~= "MapProperty" then error("property is not a MapProperty: " .. tostring(typeName)) end
    local value = object[name]
    local out = {lua_type = type(value), methods = {}, property_methods = {}}
    pcall(function() out.ue_type = value:type() end)
    for _, m in ipairs({"ForEach", "Num", "GetMapNum", "Find", "Keys", "Values", "Length"}) do
        local ok, f = pcall(function() return value[m] end)
        out.methods[m] = ok and type(f) or "error"
    end
    for _, m in ipairs({"GetKeyProp", "GetValueProp", "GetKeyProperty", "GetValueProperty"}) do
        local ok, f = pcall(function() return prop[m] end)
        out.property_methods[m] = ok and type(f) or "error"
    end
    local keyProp, valueProp = mapProps(prop)
    if keyProp then
        pcall(function() out.key_type = keyProp:GetClass():GetFName():ToString() end)
        pcall(function() out.value_type = valueProp:GetClass():GetFName():ToString() end)
    end
    return out
end


-- probe_methods: which names exist on a property's reflected Property object (target=property) or on its value (target=value, the
-- default). Reports only the Lua type of each member (function / nil / ...), never calls anything. Lets us learn this UE4SS build's
-- API (for example what a TMap or a MapProperty offers) without editing and restarting the mod for every guess.
OPS.probe_methods = function(args)
    local ref, name, names = args.object, args.property, args.names
    if not ref or not name or not names then error("args 'object', 'property' and 'names' (comma list, max 40) are required") end
    local object = resolveObject(ref)
    if not valid(object) then error("object not found: " .. ref) end
    local typeName, prop = findProperty(object, name)
    if typeName == nil then error("property not found: " .. name) end
    local target
    if args.target == "property" then target = prop
    else
        if SKIP_TYPES[typeName] then error("refusing to read a " .. typeName) end
        local ok, value = pcall(function() return object[name] end)
        if not ok then error("read failed: " .. tostring(value)) end
        target = value
    end
    local out, count = {}, 0
    for member in names:gmatch("[^,]+") do
        count = count + 1
        if count > 40 then break end
        member = member:match("^%s*(.-)%s*$")
        local ok, found = pcall(function() return target[member] end)
        out[member] = ok and type(found) or "error"
    end
    local info = {property_type = typeName, target = args.target == "property" and "property" or "value", members = out}
    pcall(function() info.ue_type = target:type() end)
    return info
end

-- map_peek: the first entry of a map, reporting only the Lua type and the wrapper type() of key and value. get() is never called,
-- so nothing is read from the entry itself (soft pointers in maps crash UE4SS's reader).
OPS.map_peek = function(args)
    local ref, name = args.object, args.property
    if not ref or not name then error("args 'object' and 'property' are required") end
    local object = resolveObject(ref)
    if not valid(object) then error("object not found: " .. ref) end
    local typeName = findProperty(object, name)
    if typeName ~= "MapProperty" then error("property is not a MapProperty: " .. tostring(typeName)) end
    local value = object[name]
    local out, entries = {}, 0
    local ok, err = pcall(function()
        value:ForEach(function(k, v)
            entries = entries + 1
            if entries > 1 then return end
            out.key_lua, out.value_lua = type(k), type(v)
            pcall(function() out.key_type = k:type() end)
            pcall(function() out.value_type = v:type() end)
        end)
    end)
    out.entries_seen = entries
    out.foreach_ok = ok
    if not ok then out.error = tostring(err) end
    return out
end


-- load_asset: asks the game to load an asset from its own containers by object path so the read operations can inspect it. OFF by
-- default (settings.txt: allow_load=true). It changes the game's in-memory state: it can pause the game thread, use memory, pull in
-- dependencies and run the asset's PostLoad logic. Only /Game/ paths, one per request. An AI agent must ask the user first and
-- explain these consequences before turning it on (see bridge/README.md).
OPS.load_asset = function(args)
    if readSettings().allow_load ~= "true" then
        error("load_asset is disabled (allow_load is not true in settings.txt). An AI agent must first ask the user and explain the consequences; see bridge/README.md")
    end
    local path = args.path
    if not path or #path > 300 or not path:match("^/Game/[%w_/%-%.]+$") or path:find("..", 1, true) or path:find("//", 1, true) then
        error("arg 'path' must be a /Game/ object path (letters, digits, _ - / .; no '..' and no '//')")
    end
    if not path:find(".", 1, true) then path = path .. "." .. path:match("[^/]+$") end
    local out = {requested = path}
    -- In a cooked game a Blueprint asset has no UBlueprint object, only its generated class "<path>_C"; check both.
    local function present()
        local okA, asset = pcall(StaticFindObject, path)
        local okC, class = pcall(StaticFindObject, path .. "_C")
        return (okA and valid(asset)) and asset or nil, (okC and valid(class)) and class or nil
    end
    local assetBefore, classBefore = present()
    if assetBefore or classBefore then
        out.already_loaded = true
        out.generated_class = classBefore and (path .. "_C") or nil
        pcall(function() out.class = (assetBefore or classBefore):GetClass():GetFullName() end)
        return out
    end
    local started = os.clock()
    local okLoad, err = pcall(function() LoadAsset(path) end)
    out.elapsed_ms = math.floor((os.clock() - started) * 1000)
    if not okLoad then out.load_error = tostring(err) end
    local asset, class = present()
    out.loaded = (asset or class) ~= nil
    if out.loaded then
        out.generated_class = class and (path .. "_C") or nil
        pcall(function() out.class = (asset or class):GetClass():GetFullName() end)
        pcall(function() out.name = (asset or class):GetFullName() end)
    end
    return out
end


-- describe_function: parameters (names and reflected types, in order) and flags of a UFunction, by path
-- ("/Game/.../BP_Container_Base.BP_Container_Base_C:CanThisUnWeld"). Reads reflection only; calls nothing.
OPS.describe_function = function(args)
    local path = args.path
    if not path or #path > 300 or not path:match("^/[%w_/%-%.]+:[%w_]+$") or path:find("..", 1, true) then
        error("arg 'path' must look like /Game/Dir/Pkg.Class_C:FunctionName")
    end
    local ok, fn = pcall(StaticFindObject, path)
    if not (ok and valid(fn)) then error("function not found (is its class loaded?): " .. path) end
    local params = {}
    local okProps = pcall(function()
        fn:ForEachProperty(function(property)
            if #params < 40 then params[#params + 1] = {name = property:GetFName():ToString(), type = property:GetClass():GetFName():ToString()} end
        end)
    end)
    local out = {function_name = fn:GetFullName(), params = params, params_readable = okProps}
    pcall(function() out.flags = fn:GetFunctionFlags() end)
    return out
end

-- cvar_get: read a console variable through the engine's own KismetSystemLibrary getters. Read-only, always available. The getters
-- return 0 for a variable that does not exist, so the answer carries all three readings and the caller judges.
OPS.cvar_get = function(args)
    local name = args.name
    if not name or #name > 80 or not name:match("^[%w_%.]+$") then error("arg 'name' must be a console variable name (letters, digits, _ and .)") end
    local lib = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
    if not valid(lib) then error("KismetSystemLibrary not found") end
    local out = {name = name}
    for key, fn in pairs({float = "GetConsoleVariableFloatValue", int = "GetConsoleVariableIntValue", bool = "GetConsoleVariableBoolValue"}) do
        local ok, value = pcall(function() return lib[fn](lib, name) end)
        if ok then out[key] = value else out[key] = "error: " .. tostring(value) end
    end
    return out
end

-- console_exec: run ONE console command. OFF by default (settings.txt: allow_console=true). It changes the running game (a cvar, a
-- stat overlay, a log category); only commands whose first word is in CONSOLE_ALLOWED run, no chaining, and never quit/open/travel. An AI
-- agent must ask the user first and explain the consequences before turning it on (see bridge/README.md).
local CONSOLE_ALLOWED = {["stat"] = true, ["r."] = true, ["sg."] = true, ["t."] = true, ["log"] = true, ["obj"] = true, ["showflag"] = true,
    ["dumpconsolecommands"] = true, ["listtimers"] = true, ["memreport"] = false}
OPS.console_exec = function(args)
    if readSettings().allow_console ~= "true" then
        error("console_exec is disabled (allow_console is not true in settings.txt). An AI agent must first ask the user and explain the consequences; see bridge/README.md")
    end
    local command = args.command
    if not command or #command > 120 or command:find("[;|%c]") or not command:match("^[%w_%.%- =/]+$") then
        error("arg 'command' must be one console command of at most 120 characters (letters, digits, _ . - = / and spaces; no ';' or '|')")
    end
    local first = command:match("^(%S+)")
    local allowed = CONSOLE_ALLOWED[first:lower()] or CONSOLE_ALLOWED[first:lower():match("^(%a+%.)") or ""]
    if not allowed then error("command not allowed; the first word must be one of: stat, log, obj, showflag, dumpconsolecommands, listtimers, or a cvar starting r. sg. t.") end
    local pc = UEHelpers.GetPlayerController()
    local lib = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
    if not (valid(pc) and valid(lib)) then error("no player controller or KismetSystemLibrary (is a save loaded?)") end
    local ok, err = pcall(function() lib:ExecuteConsoleCommand(pc, command, pc) end)
    if not ok then error("ExecuteConsoleCommand failed: " .. tostring(err)) end
    return {executed = command}
end

-- watch_function: OBSERVE-ONLY hook on one UFunction. OFF by default (settings.txt: allow_hooks=true). Records, in a ring buffer of
-- 50 strings, the object name the function ran on and the primitive arguments / return value; changes nothing and keeps no UObject.
-- Hooks have been a crash suspect in earlier projects; an AI agent must ask the user and explain the consequences before enabling.
local watchers = {}
local watchCount = 0
local MAX_WATCHERS = 3
local MAX_EVENTS = 50

local function primitive(param)
    local ok, value = pcall(function() return param:get() end)
    if not ok then return "<unreadable>" end
    local kind = type(value)
    if kind == "boolean" or kind == "number" or kind == "string" then return tostring(value) end
    local okName, name = pcall(function() return value:GetFullName() end)
    return okName and tostring(name) or ("<" .. kind .. ">")
end

local function record(watcher, phase, self, ...)
    local entry = {phase = phase, self = primitive(self), args = {}}
    local n = select("#", ...)
    for i = 1, math.min(n, 4) do entry.args[#entry.args + 1] = primitive((select(i, ...))) end
    watcher.events[#watcher.events + 1] = os.date("%H:%M:%S") .. " " .. phase .. " self=" .. entry.self .. " args=[" .. table.concat(entry.args, ", ") .. "]"
    if #watcher.events > MAX_EVENTS then table.remove(watcher.events, 1) end
end

OPS.watch_function = function(args)
    if readSettings().allow_hooks ~= "true" then
        error("watch_function is disabled (allow_hooks is not true in settings.txt). An AI agent must first ask the user and explain the consequences; see bridge/README.md")
    end
    local action, path = args.action or "list", args.path
    if action == "list" then
        local out = {}
        for hookPath, watcher in pairs(watchers) do out[#out + 1] = {path = hookPath, events = #watcher.events} end
        return {watchers = out}
    end
    if not path or #path > 300 or not path:match("^/[%w_/%-%.]+:[%w_]+$") or path:find("..", 1, true) then
        error("arg 'path' must look like /Game/Dir/Pkg.Class_C:FunctionName")
    end
    if action == "start" then
        if watchers[path] then error("already watching " .. path) end
        if watchCount >= MAX_WATCHERS then error("at most " .. MAX_WATCHERS .. " watchers at a time") end
        local ok, fn = pcall(StaticFindObject, path)
        if not (ok and valid(fn)) then error("function not found (is its class loaded?): " .. path) end
        local watcher = {events = {}}
        local firstPhase = path:match("^/Script/") and "pre" or "post"
        local okHook, preId, postId = pcall(RegisterHook, path,
            function(self, ...) record(watcher, firstPhase, self, ...) end,
            function(self, ...) record(watcher, "post", self, ...) end)
        if not okHook then error("RegisterHook failed: " .. tostring(preId)) end
        watcher.preId, watcher.postId = preId, postId
        watchers[path] = watcher
        watchCount = watchCount + 1
        return {watching = path}
    elseif action == "log" then
        local watcher = watchers[path]
        if not watcher then error("not watching " .. path) end
        local copy = {}
        for i, line in ipairs(watcher.events) do copy[i] = line end
        return {path = path, events = copy}
    elseif action == "stop" then
        local watcher = watchers[path]
        if not watcher then error("not watching " .. path) end
        pcall(UnregisterHook, path, watcher.preId, watcher.postId)
        watchers[path] = nil
        watchCount = watchCount - 1
        return {stopped = path, events_seen = #watcher.events}
    end
    error("arg 'action' must be start, log, stop or list")
end

-- Request handling ---------------------------------------------------------------------------------------------------------
local function readRequest()
    local fh = io.open(REQUEST, "rb")
    if not fh then return nil end
    local text = fh:read(MAX_REQUEST_BYTES + 1)
    fh:close()
    os.remove(REQUEST)
    return text
end

local function parse(text)
    local request = {args = {}}
    for line in text:gmatch("[^\r\n]+") do
        local key, value = line:match("^([%w_.]+)=(.*)$")
        if key == "id" then request.id = value
        elseif key == "op" then request.op = value
        elseif key and key:sub(1, 4) == "arg." then request.args[key:sub(5)] = value end
    end
    return request
end

local function handle(text)
    if #text > MAX_REQUEST_BYTES then return writeResponse("invalid", {ok = false, error = "request too large"}) end
    local request = parse(text)
    local id = request.id
    if not id or not id:match("^%w+$") or #id < 8 or #id > 32 then
        return writeResponse("invalid", {ok = false, error = "missing or invalid id (8-32 letters/digits)"})
    end
    local op = OPS[request.op or ""]
    if not op then return writeResponse(id, {ok = false, error = "unknown op: " .. tostring(request.op), ops = {"ping", "status", "find_all", "get", "describe_class", "get_array", "read", "find_object", "scan", "map_info", "probe_methods", "map_peek", "load_asset", "describe_function", "watch_function", "cvar_get", "console_exec"}}) end
    local oneLine = text:gsub("[\r\n]+", " | "):sub(1, 300)
    writeFile(LASTOP, string.format("%s id=%s op=%s %s\n", os.date("%Y-%m-%d %H:%M:%S"), id, request.op, oneLine))
    local ok, result = pcall(op, request.args)
    if ok then writeResponse(id, {ok = true, op = request.op, result = result})
    else writeResponse(id, {ok = false, op = request.op, error = tostring(result)}) end
end

local lastBeat = 0
LoopAsync(POLL_MS, function()
    local now = os.time()
    if now ~= lastBeat then lastBeat = now; writeFile(HEARTBEAT, tostring(now) .. " " .. VERSION) end
    if busy then return false end
    local fh = io.open(REQUEST, "rb")
    if not fh then return false end
    fh:close()
    busy = true
    local text = readRequest()
    ExecuteInGameThread(function()
        local ok, err = pcall(handle, text or "")
        if not ok then log("handler error: " .. tostring(err)) end
        busy = false
    end)
    return false
end)

log("v" .. VERSION .. " ready, io folder: " .. IO)
