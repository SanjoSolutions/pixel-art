local SECTION_TOOL_MARKER = "pixel-car-renderer:tileset-section:v1"
local SECTION_ORDER = { "A1", "A2", "A3", "A4", "A5", "B", "C", "D", "E" }
local SECTION_NAMES = {}
for _, sectionName in ipairs(SECTION_ORDER) do
  SECTION_NAMES[sectionName] = true
end

local function scriptParam(name, default)
  if app and app.params then
    local value = app.params[name]
    if value ~= nil and value ~= "" then
      return value
    end
  end
  return default
end

local function joinPath(directory, filename)
  if directory:sub(-1) == "/" or directory:sub(-1) == "\\" then
    return directory .. filename
  end
  return directory .. "/" .. filename
end

local function firstCel(sprite)
  if sprite.cels and #sprite.cels > 0 then
    return sprite.cels[1]
  end
  local layer = sprite.layers[1] or sprite:newLayer()
  local frame = sprite.frames[1]
  local image = Image(sprite.width, sprite.height, sprite.colorMode)
  image:clear()
  return sprite:newCel(layer, frame, image, Point(0, 0))
end

local function decodeSliceData(slice)
  if slice.data and slice.data ~= "" and json then
    local ok, data = pcall(json.decode, slice.data)
    if ok and type(data) == "table" then
      return data
    end
  end
  return {}
end

local function isSectionSlice(slice)
  if SECTION_NAMES[tostring(slice.name or "")] then
    return true
  end
  local data = decodeSliceData(slice)
  return data.tool == SECTION_TOOL_MARKER
end

local function imageHasVisiblePixel(image)
  for pixel in image:pixels() do
    if app.pixelColor.rgbaA(pixel()) > 0 then
      return true
    end
  end
  return false
end

local sourcePath = scriptParam("source", "interior_furniture.aseprite")
local outDir = scriptParam("out-dir", "output/rpg-maker")
local prefix = scriptParam("prefix", "interior_furniture")

local source = app.open(sourcePath)
if not source then
  error("Could not open " .. sourcePath)
end

local sourceCel = firstCel(source)
local sectionsByName = {}
for _, slice in ipairs(source.slices) do
  if isSectionSlice(slice) then
    sectionsByName[tostring(slice.name or "")] = slice
  end
end

local exported = 0
local skippedEmpty = 0
for _, sectionName in ipairs(SECTION_ORDER) do
  local section = sectionsByName[sectionName]
  if not section then
    error("Missing RPG Maker section slice '" .. sectionName .. "' in " .. sourcePath)
  end

  local bounds = section.bounds
  local output = Sprite(bounds.width, bounds.height, source.colorMode)
  output.gridBounds = Rectangle(0, 0, source.gridBounds.width, source.gridBounds.height)
  local outputCel = firstCel(output)
  outputCel.position = Point(0, 0)
  outputCel.image:clear()
  outputCel.image:drawImage(
    sourceCel.image,
    Point(sourceCel.position.x - bounds.x, sourceCel.position.y - bounds.y)
  )
  if imageHasVisiblePixel(outputCel.image) then
    output:saveAs(joinPath(outDir, prefix .. "_" .. sectionName .. ".png"))
    exported = exported + 1
  else
    skippedEmpty = skippedEmpty + 1
  end
  output:close()
end

source:close()

io.stdout:write(
  "Exported " .. tostring(exported) .. " RPG Maker section PNGs to " ..
  outDir .. " (skipped " .. tostring(skippedEmpty) .. " empty section(s))\n"
)
