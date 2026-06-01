local function scriptParam(name, default)
  if app and app.params then
    local value = app.params[name]
    if value ~= nil and value ~= "" then
      return value
    end
  end
  return default
end

local function readFile(path)
  local file, message = io.open(path, "r")
  if not file then
    error(message)
  end
  local text = file:read("*a")
  file:close()
  return text
end

local manifestPath = scriptParam("manifest", "tiles/wood_floors_manifest.json")
local outputPath = scriptParam("output", "tiles/wood_floors.aseprite")
local tileSize = tonumber(scriptParam("tile-size", "32")) or 32

if not app.sprite then
  error("Open the spritesheet PNG before running this script.")
end
if not json then
  error("Aseprite JSON support is required.")
end

local manifest = json.decode(readFile(manifestPath))
local sprite = app.sprite

for index = #sprite.slices, 1, -1 do
  sprite:deleteSlice(sprite.slices[index])
end

sprite.gridBounds = Rectangle(0, 0, tileSize, tileSize)

for _, tile in ipairs(manifest.tiles or {}) do
  local slice = sprite:newSlice(Rectangle(tile.x, tile.y, tile.w, tile.h))
  slice.name = tile.asset_id
  slice.data = json.encode({
    asset_id = tile.asset_id,
    display_name = tile.display_name,
    index = tile.index,
    source_kind = tile.source_kind,
    source_url = tile.source_url,
  })
  slice.color = Color{ r=96, g=160, b=255, a=255 }
end

sprite:saveAs(outputPath)
sprite:close()

io.stdout:write(
  "Imported " .. tostring(#(manifest.tiles or {})) ..
  " AmbientCG wood-floor slices to " .. outputPath .. "\n"
)
