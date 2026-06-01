local LEGACY_TOOL_MARKER = "pixel-car-renderer:furniture-metadata:v1"
local SECTION_TOOL_MARKER = "pixel-car-renderer:tileset-section:v1"
local DEFAULT_TILE_SIZE = 32
local SECTION_NAMES = {
  A1 = true,
  A2 = true,
  A3 = true,
  A4 = true,
  A5 = true,
  B = true,
  C = true,
  D = true,
  E = true,
}
local VALID_ALIGNMENTS = {
  ["back-left"] = true,
  back = true,
  ["back-right"] = true,
  left = true,
  center = true,
  none = true,
  right = true,
  ["front-left"] = true,
  front = true,
  ["front-right"] = true,
}

local function scriptParam(name, default)
  if app and app.params then
    local value = app.params[name]
    if value ~= nil and value ~= "" then
      return value
    end
  end
  return default
end

local function normalizedPath(path)
  return (path or ""):gsub("\\", "/")
end

local function basename(path)
  return normalizedPath(path):match("([^/]+)$") or path
end

local function readFile(path)
  local file = io.open(path, "r")
  if not file then
    return nil
  end
  local text = file:read("*a")
  file:close()
  return text
end

local function writeFile(path, text)
  local file, message = io.open(path, "w")
  if not file then
    error(message)
  end
  file:write(text)
  file:close()
end

local function readJsonOrEmpty(path)
  if not json then
    return {}
  end
  local text = readFile(path)
  if not text or text == "" then
    return {}
  end
  local ok, value = pcall(json.decode, text)
  if ok and type(value) == "table" then
    return value
  end
  return {}
end

local function isArray(value)
  if type(value) ~= "table" then
    return false
  end
  local count = 0
  local maxIndex = 0
  for key in pairs(value) do
    if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then
      return false
    end
    count = count + 1
    maxIndex = math.max(maxIndex, key)
  end
  return maxIndex == count
end

local function escapedString(value)
  local replacements = {
    ['"'] = '\\"',
    ["\\"] = "\\\\",
    ["\b"] = "\\b",
    ["\f"] = "\\f",
    ["\n"] = "\\n",
    ["\r"] = "\\r",
    ["\t"] = "\\t",
  }
  return '"' .. tostring(value):gsub('[\\"%z\1-\31]', function(character)
    return replacements[character] or string.format("\\u%04x", character:byte())
  end) .. '"'
end

local function orderedKeys(value, preferred)
  local keys = {}
  local seen = {}
  for _, key in ipairs(preferred or {}) do
    if value[key] ~= nil then
      table.insert(keys, key)
      seen[key] = true
    end
  end
  local extras = {}
  for key in pairs(value) do
    if not seen[key] then
      table.insert(extras, key)
    end
  end
  table.sort(extras, function(leftKey, rightKey)
    return tostring(leftKey) < tostring(rightKey)
  end)
  for _, key in ipairs(extras) do
    table.insert(keys, key)
  end
  return keys
end

local function keyOrderFor(value)
  if value and value.sprites then
    return {
      "image", "tile_size", "columns", "rows", "count",
      "sprites", "manual_edits",
    }
  end
  if value and value.grid_x then
    return {
      "name", "file", "index", "x", "y", "w", "h",
      "grid_x", "grid_y", "grid_w", "grid_h",
      "manual", "placeholder", "alignment", "width", "keepProportions",
    }
  end
  if value and value.tilewidth and value.tileheight then
    return {
      "columns", "image", "imageheight", "imagewidth", "margin",
      "name", "spacing", "tilecount", "tiledversion", "tileheight",
      "tilewidth", "type", "version",
    }
  end
  return nil
end

local function encodeJsonValue(value, indent)
  local valueType = type(value)
  if valueType == "nil" then
    return "null"
  end
  if valueType == "boolean" then
    return value and "true" or "false"
  end
  if valueType == "number" then
    return tostring(value)
  end
  if valueType == "string" then
    return escapedString(value)
  end
  if valueType ~= "table" then
    return escapedString(tostring(value))
  end

  local nextIndent = indent .. "  "
  if isArray(value) then
    if #value == 0 then
      return "[]"
    end
    local parts = { "[" }
    for index, item in ipairs(value) do
      local suffix = index < #value and "," or ""
      table.insert(parts, nextIndent .. encodeJsonValue(item, nextIndent) .. suffix)
    end
    table.insert(parts, indent .. "]")
    return table.concat(parts, "\n")
  end

  local keys = orderedKeys(value, keyOrderFor(value))
  if #keys == 0 then
    return "{}"
  end
  local parts = { "{" }
  for index, key in ipairs(keys) do
    local suffix = index < #keys and "," or ""
    table.insert(
      parts,
      nextIndent .. escapedString(key) .. ": " ..
        encodeJsonValue(value[key], nextIndent) .. suffix
    )
  end
  table.insert(parts, indent .. "}")
  return table.concat(parts, "\n")
end

local function encodeJson(value)
  return encodeJsonValue(value, "") .. "\n"
end

local function decodeSliceData(slice)
  if not slice.data or slice.data == "" or not json then
    return nil
  end
  local ok, data = pcall(json.decode, slice.data)
  if ok and data and (data.tool == nil or data.tool == LEGACY_TOOL_MARKER) then
    return {
      index = tonumber(data.index),
      file = data.file,
      manual = data.manual,
      placeholder = data.placeholder,
      alignment = data.alignment,
      width = data.width,
      keepProportions = data.keepProportions,
    }
  end
  return nil
end

local function isSectionSlice(slice)
  if SECTION_NAMES[tostring(slice.name or "")] then
    return true
  end
  if not slice.data or slice.data == "" or not json then
    return false
  end
  local ok, data = pcall(json.decode, slice.data)
  return ok and data and data.tool == SECTION_TOOL_MARKER
end

local function round(value)
  return math.floor(value + 0.5)
end

local function isAligned(value, tileSize)
  return math.abs((value / tileSize) - round(value / tileSize)) < 0.001
end

local function warn(message)
  io.stderr:write("warning: " .. message .. "\n")
end

local function snappedRect(slice, tileSize, columns, rows)
  local bounds = slice.bounds
  if bounds.width <= 0 or bounds.height <= 0 then
    error("Slice '" .. slice.name .. "' has an empty rectangle.")
  end
  local aligned =
    isAligned(bounds.x, tileSize) and
    isAligned(bounds.y, tileSize) and
    isAligned(bounds.x + bounds.width, tileSize) and
    isAligned(bounds.y + bounds.height, tileSize)
  if not aligned then
    warn("slice '" .. slice.name .. "' is not aligned to the " .. tileSize .. "px grid; snapping")
  end

  local gridX = round(bounds.x / tileSize)
  local gridY = round(bounds.y / tileSize)
  local right = round((bounds.x + bounds.width) / tileSize)
  local bottom = round((bounds.y + bounds.height) / tileSize)
  if gridX < 0 or gridY < 0 or right > columns or bottom > rows then
    error(
      "Slice '" .. slice.name .. "' is outside the sheet bounds: " ..
      bounds.x .. "," .. bounds.y .. " " .. bounds.width .. "x" .. bounds.height
    )
  end
  if right <= gridX or bottom <= gridY then
    error("Slice '" .. slice.name .. "' snaps to an empty grid rectangle.")
  end
  return gridX, gridY, right - gridX, bottom - gridY
end

local function sliceToManifestSprite(slice, tileSize, columns, rows)
  local metadata = decodeSliceData(slice) or {}
  local gridX, gridY, gridW, gridH = snappedRect(slice, tileSize, columns, rows)
  local name = tostring(slice.name or metadata.name or "")
  if name == "" then
    name = "manual_placeholder_" .. gridX .. "_" .. gridY
  end
  local fileName = metadata.file
  if type(fileName) ~= "string" or fileName == "" then
    fileName = name .. ".png"
  end

  local manifestSprite = {
    name = name,
    file = fileName,
    index = tonumber(metadata.index) or 0,
    x = gridX * tileSize,
    y = gridY * tileSize,
    w = gridW * tileSize,
    h = gridH * tileSize,
    grid_x = gridX,
    grid_y = gridY,
    grid_w = gridW,
    grid_h = gridH,
  }
  local manual = metadata.manual
  if manual == nil then
    manual =
      name:match("^wall") ~= nil or
      name:match("^rug") ~= nil or
      name:match("^floor") ~= nil
  end
  if manual == true then
    manifestSprite.manual = true
  end
  if metadata.placeholder or name:match("^manual_placeholder_") then
    manifestSprite.placeholder = true
  end
  if metadata.alignment then
    if not VALID_ALIGNMENTS[metadata.alignment] then
      error(
        "Slice '" .. name .. "' has invalid alignment '" ..
        tostring(metadata.alignment) .. "'."
      )
    end
    manifestSprite.alignment = metadata.alignment
  end
  if metadata.width ~= nil then
    local width = tonumber(metadata.width)
    if width == nil or width <= 0 then
      error(
        "Slice '" .. name .. "' has invalid width '" ..
        tostring(metadata.width) .. "'."
      )
    end
    manifestSprite.width = width
  end
  if metadata.keepProportions ~= nil then
    if type(metadata.keepProportions) ~= "boolean" then
      error(
        "Slice '" .. name .. "' has invalid keepProportions '" ..
        tostring(metadata.keepProportions) .. "'."
      )
    end
    manifestSprite.keepProportions = metadata.keepProportions
  end
  return manifestSprite, tonumber(metadata.index)
end

local function sortedManifestSprites(sprite, tileSize, includeUnmanaged)
  if sprite.width % tileSize ~= 0 or sprite.height % tileSize ~= 0 then
    error("Sheet size must be divisible by tile size.")
  end
  local columns = math.floor(sprite.width / tileSize)
  local rows = math.floor(sprite.height / tileSize)
  local entries = {}
  for _, slice in ipairs(sprite.slices) do
    local metadata = decodeSliceData(slice)
    if not isSectionSlice(slice) and (metadata or includeUnmanaged) then
      local manifestSprite, originalIndex =
        sliceToManifestSprite(slice, tileSize, columns, rows)
      table.insert(entries, {
        hasIndex = originalIndex ~= nil,
        sortIndex = originalIndex or 0,
        sprite = manifestSprite,
      })
    end
  end

  table.sort(entries, function(leftEntry, rightEntry)
    if leftEntry.hasIndex ~= rightEntry.hasIndex then
      return leftEntry.hasIndex
    end
    if leftEntry.sortIndex ~= rightEntry.sortIndex then
      return leftEntry.sortIndex < rightEntry.sortIndex
    end
    if leftEntry.sprite.grid_y ~= rightEntry.sprite.grid_y then
      return leftEntry.sprite.grid_y < rightEntry.sprite.grid_y
    end
    if leftEntry.sprite.grid_x ~= rightEntry.sprite.grid_x then
      return leftEntry.sprite.grid_x < rightEntry.sprite.grid_x
    end
    return leftEntry.sprite.name < rightEntry.sprite.name
  end)

  local names = {}
  local occupied = {}
  local manifestSprites = {}
  for index, entry in ipairs(entries) do
    local manifestSprite = entry.sprite
    if names[manifestSprite.name] then
      error("Duplicate slice name '" .. manifestSprite.name .. "'.")
    end
    names[manifestSprite.name] = true
    for y = manifestSprite.grid_y, manifestSprite.grid_y + manifestSprite.grid_h - 1 do
      for x = manifestSprite.grid_x, manifestSprite.grid_x + manifestSprite.grid_w - 1 do
        local key = x .. "," .. y
        if occupied[key] then
          error(
            "Slice '" .. manifestSprite.name .. "' overlaps slice '" ..
            occupied[key] .. "' at tile " .. key .. "."
          )
        end
        occupied[key] = manifestSprite.name
      end
    end
    manifestSprite.index = index - 1
    table.insert(manifestSprites, manifestSprite)
  end
  return manifestSprites, columns, rows
end

local function countPlaceholders(sprites)
  local count = 0
  for _, manifestSprite in ipairs(sprites) do
    if manifestSprite.placeholder then
      count = count + 1
    end
  end
  return count
end

local function updateTileset(tileset, sprite, tileSize, imageReference)
  local columns = math.floor(sprite.width / tileSize)
  local rows = math.floor(sprite.height / tileSize)
  tileset = tileset or {}
  tileset.type = tileset.type or "tileset"
  tileset.version = tileset.version or "1.10"
  tileset.tiledversion = tileset.tiledversion or "1.12.2-2-geb83ddb9"
  tileset.name = tileset.name or "interior_furniture"
  tileset.margin = tileset.margin or 0
  tileset.spacing = tileset.spacing or 0
  tileset.columns = columns
  tileset.image = imageReference
  tileset.imageheight = sprite.height
  tileset.imagewidth = sprite.width
  tileset.tileheight = tileSize
  tileset.tilewidth = tileSize
  tileset.tilecount = columns * rows
  return tileset
end

local sourcePath = scriptParam("source", "interior_furniture.aseprite")
local manifestPath = scriptParam("manifest", "output/furniture_manifest.json")
local tilesetPath = scriptParam("tileset", "interior_furniture.tsj")
local sheetPath = scriptParam("sheet", "output/interior_furniture.png")
local imageReference = scriptParam("image-ref", "output/interior_furniture.png")
local tileSize = tonumber(scriptParam("tile-size", tostring(DEFAULT_TILE_SIZE))) or DEFAULT_TILE_SIZE
local includeUnmanaged = scriptParam("include-unmanaged", "1") ~= "0"

local sprite = app.open(sourcePath)
if not sprite then
  error("Could not open " .. sourcePath)
end

local manifestSprites, columns, rows = sortedManifestSprites(sprite, tileSize, includeUnmanaged)
if #manifestSprites == 0 then
  error("No slices found in " .. sourcePath)
end

local manifest = readJsonOrEmpty(manifestPath)
manifest.image = basename(sheetPath)
manifest.tile_size = tileSize
manifest.columns = columns
manifest.rows = rows
manifest.count = #manifestSprites
manifest.sprites = manifestSprites
manifest.manual_edits = manifest.manual_edits or {}
manifest.manual_edits.placeholder_sprites = countPlaceholders(manifestSprites)
manifest.manual_edits.metadata_source = basename(sourcePath)
writeFile(manifestPath, encodeJson(manifest))

local tileset = updateTileset(readJsonOrEmpty(tilesetPath), sprite, tileSize, imageReference)
writeFile(tilesetPath, encodeJson(tileset))

io.stdout:write(
  "Exported " .. #manifestSprites .. " Aseprite slices to " ..
  manifestPath .. " and " .. tilesetPath .. "\n"
)
pcall(function()
  sprite:close()
end)
