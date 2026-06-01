_G.FURNITURE_SLICE_MANUAL_ACTION = true

local function dirname(path)
  return path:match("^(.*)/[^/]*$") or "."
end

local function shellQuote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

local function resolvedPath(path)
  local pipe = io.popen("readlink -f " .. shellQuote(path) .. " 2>/dev/null")
  if not pipe then
    return nil
  end
  local resolved = pipe:read("*l")
  pipe:close()
  return resolved
end

local function existingPath(path)
  local file = io.open(path, "r")
  if file then
    file:close()
    return path
  end
  return nil
end

local scriptPath = debug.getinfo(1, "S").source:gsub("^@", "")
local helperPath =
  existingPath(dirname(scriptPath) .. "/aseprite_furniture_slice_tools.lua") or
  existingPath(dirname(resolvedPath(scriptPath) or scriptPath) .. "/aseprite_furniture_slice_tools.lua")

if not helperPath then
  error("Cannot find aseprite_furniture_slice_tools.lua")
end

dofile(helperPath)
