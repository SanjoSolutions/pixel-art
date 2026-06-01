local TILE_SIZE = tonumber(app.params["tile-size"] or "32") or 32
local SHEET_COLUMNS = 16
local SHEET_ROWS = 16
local TOOL_MARKER = "pixel-car-renderer:furniture-metadata:v1"
local AUTO_COLOR = { r = 64, g = 169, b = 255, a = 255 }
local MANUAL_COLOR = { r = 0, g = 230, b = 118, a = 255 }
local PLACEHOLDER_COLOR = { r = 255, g = 176, b = 0, a = 255 }

local OUTPUT_CATEGORY_ORDER = { "B", "C", "D", "E" }
local INPUT_CATEGORY_ORDER = { "B", "C", "D", "E", "F" }

local function scriptParam(name, default)
  if app and app.params then
    local value = app.params[name]
    if value ~= nil and value ~= "" then
      return value
    end
  end
  return default
end

local function startsWith(value, prefix)
  return value:sub(1, #prefix) == prefix
end

local function hasPrefix(value, prefixes)
  for _, prefix in ipairs(prefixes) do
    if startsWith(value, prefix) then
      return true
    end
  end
  return false
end

local function hasName(value, names)
  for _, name in ipairs(names) do
    if value == name then
      return true
    end
  end
  return false
end

local function isOfficeName(name)
  return hasPrefix(name, { "computer" }) or
    hasName(name, { "chairDesk", "desk", "deskCorner", "laptop" })
end

local function categoryForName(name)
  if hasPrefix(name, { "bed", "cabinetBed", "pillow" }) then
    return "B"
  end
  if isOfficeName(name) then
    return "B"
  end
  if hasPrefix(name, { "hood", "kitchen" }) or
      hasName(name, { "stoolBar", "stoolBarSquare", "toaster" }) then
    return "C"
  end
  if hasPrefix(name, { "bathroom" }) or
      hasName(name, { "bathtub", "shower", "showerRound", "toilet", "toiletSquare" }) then
    return "E"
  end
  if hasPrefix(name, {
        "bench",
        "bookcase",
        "cabinetTelevision",
        "chair",
        "lamp",
        "lounge",
        "plant",
        "rug",
        "sideTable",
        "speaker",
        "table",
        "television",
      }) or hasName(name, {
        "books",
        "ceilingFan",
        "paneling",
        "pottedPlant",
        "radio",
      }) then
    return "D"
  end
  return nil
end

local function minRowForEntry(entry)
  if entry.category == "B" and isOfficeName(entry.name) then
    return 8
  end
  return 0
end

local function maxRowForEntry(entry)
  if entry.category == "B" and not isOfficeName(entry.name) then
    return 7
  end
  return SHEET_ROWS - 1
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

local function metadataColor(metadata, name)
  if metadata.manual == true or
      tostring(name):match("^wall") or
      tostring(name):match("^rug") or
      tostring(name):match("^floor") then
    return MANUAL_COLOR
  end
  if metadata.placeholder == true or tostring(name):match("^manual_placeholder_") then
    return PLACEHOLDER_COLOR
  end
  return AUTO_COLOR
end

local function sliceColor(slice, metadata, name)
  local defaultColor = metadataColor(metadata, name)
  if defaultColor ~= AUTO_COLOR then
    return defaultColor
  end
  local color = slice.color
  if color and color.alpha and color.alpha > 0 then
    return {
      r = color.red,
      g = color.green,
      b = color.blue,
      a = color.alpha,
    }
  end
  return metadataColor(metadata, name)
end

local function sortedSlices(sprite)
  local entries = {}
  for _, slice in ipairs(sprite.slices) do
    local bounds = slice.bounds
    local data = decodeSliceData(slice)
    table.insert(entries, {
      slice = slice,
      data = data,
      name = tostring(slice.name or ""),
      sortIndex = tonumber(data.index),
      x = bounds.x,
      y = bounds.y,
    })
  end
  table.sort(entries, function(left, right)
    if (left.sortIndex ~= nil) ~= (right.sortIndex ~= nil) then
      return left.sortIndex ~= nil
    end
    if left.sortIndex ~= nil and left.sortIndex ~= right.sortIndex then
      return left.sortIndex < right.sortIndex
    end
    if left.y ~= right.y then
      return left.y < right.y
    end
    if left.x ~= right.x then
      return left.x < right.x
    end
    return left.name < right.name
  end)
  return entries
end

local function round(value)
  return math.floor(value + 0.5)
end

local function gridCellsFor(bounds)
  local gridW = round(bounds.width / TILE_SIZE)
  local gridH = round(bounds.height / TILE_SIZE)
  if gridW <= 0 or gridH <= 0 or
      gridW * TILE_SIZE ~= bounds.width or
      gridH * TILE_SIZE ~= bounds.height then
    error(
      "Slice size is not aligned to " .. TILE_SIZE .. "px: " ..
      tostring(bounds.width) .. "x" .. tostring(bounds.height)
    )
  end
  if gridW > SHEET_COLUMNS or gridH > SHEET_ROWS then
    error(
      "Slice is larger than one RPG Maker-style sheet: " ..
      tostring(bounds.width) .. "x" .. tostring(bounds.height)
    )
  end
  return gridW, gridH
end

local function occupancyKey(x, y)
  return tostring(x) .. "," .. tostring(y)
end

local function canPlace(occupied, x, y, gridW, gridH)
  for dy = 0, gridH - 1 do
    for dx = 0, gridW - 1 do
      if occupied[occupancyKey(x + dx, y + dy)] then
        return false
      end
    end
  end
  return true
end

local function occupy(occupied, x, y, gridW, gridH)
  for dy = 0, gridH - 1 do
    for dx = 0, gridW - 1 do
      occupied[occupancyKey(x + dx, y + dy)] = true
    end
  end
end

local function placeEntries(entries, reserveFirstTile)
  local occupied = {}
  if reserveFirstTile then
    occupy(occupied, 0, 0, 1, 1)
  end

  for _, entry in ipairs(entries) do
    local placed = false
    local minRow = minRowForEntry(entry)
    local maxStartRow = maxRowForEntry(entry) - entry.gridH + 1
    for y = minRow, maxStartRow do
      for x = 0, SHEET_COLUMNS - entry.gridW do
        if canPlace(occupied, x, y, entry.gridW, entry.gridH) then
          entry.targetX = x * TILE_SIZE
          entry.targetY = y * TILE_SIZE
          occupy(occupied, x, y, entry.gridW, entry.gridH)
          placed = true
          break
        end
      end
      if placed then
        break
      end
    end
    if not placed then
      error(
        "No room for slice '" .. entry.name .. "' on sheet " ..
        tostring(entry.category)
      )
    end
  end
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

local function clearSlices(sprite)
  for index = #sprite.slices, 1, -1 do
    sprite:deleteSlice(sprite.slices[index])
  end
end

local function setRpgMakerGrid(sprite)
  pcall(function()
    sprite.gridBounds = Rectangle(0, 0, TILE_SIZE, TILE_SIZE)
  end)
end

local function setSliceColor(slice, color)
  pcall(function()
    slice.color = Color(color)
  end)
end

local function openOrCreate(path)
  local sprite = app.open(path)
  if sprite then
    return sprite
  end
  sprite = Sprite(SHEET_COLUMNS * TILE_SIZE, SHEET_ROWS * TILE_SIZE, ColorMode.RGB)
  sprite:saveAs(path)
  return sprite
end

local function fileExists(path)
  local file = io.open(path, "rb")
  if file then
    file:close()
    return true
  end
  return false
end

local function openIfExists(path)
  if not fileExists(path) then
    return nil
  end
  return app.open(path)
end

local function collectFromSprite(sprite, fallbackCategory, entries, names)
  local cel = firstCel(sprite)
  cel.position = Point(0, 0)
  for _, sliceEntry in ipairs(sortedSlices(sprite)) do
    local bounds = sliceEntry.slice.bounds
    local name = sliceEntry.name
    if names[name] then
      error("Duplicate slice name '" .. name .. "' across category sheets.")
    end
    names[name] = true
    local gridW, gridH = gridCellsFor(bounds)
    local crop = Image(cel.image, Rectangle(
      bounds.x,
      bounds.y,
      bounds.width,
      bounds.height
    ))
    table.insert(entries, {
      originalCategory = fallbackCategory,
      category = categoryForName(name),
      name = name,
      data = sliceEntry.slice.data,
      color = sliceColor(sliceEntry.slice, sliceEntry.data, name),
      sourceX = bounds.x,
      sourceY = bounds.y,
      sourceW = bounds.width,
      sourceH = bounds.height,
      gridW = gridW,
      gridH = gridH,
      image = crop,
    })
  end
end

local function writeEntries(sprite, entries, useOriginalPositions)
  local cel = firstCel(sprite)
  cel.position = Point(0, 0)
  cel.image:clear()
  clearSlices(sprite)
  setRpgMakerGrid(sprite)

  for _, entry in ipairs(entries) do
    local x = useOriginalPositions and entry.sourceX or entry.targetX
    local y = useOriginalPositions and entry.sourceY or entry.targetY
    cel.image:drawImage(entry.image, Point(x, y))
    local slice = sprite:newSlice(Rectangle(x, y, entry.sourceW, entry.sourceH))
    slice.name = entry.name
    if entry.data and entry.data ~= "" then
      slice.data = entry.data
    else
      slice.data = json.encode({
        tool = TOOL_MARKER,
        file = entry.name .. ".png",
      })
    end
    setSliceColor(slice, entry.color)
  end
end

local sourcePath = scriptParam("source", "interior_furniture.aseprite")
local targetPaths = {
  B = scriptParam("target-b", "interior_furniture_B.aseprite"),
  C = scriptParam("target-c", "interior_furniture_C.aseprite"),
  D = scriptParam("target-d", "interior_furniture_D.aseprite"),
  E = scriptParam("target-e", "interior_furniture_E.aseprite"),
  F = scriptParam("target-f", "interior_furniture_F.aseprite"),
}

local source = app.open(sourcePath)
if not source then
  error("Could not open " .. sourcePath)
end

local targets = {}
for _, category in ipairs(OUTPUT_CATEGORY_ORDER) do
  targets[category] = openOrCreate(targetPaths[category])
end

local allEntries = {}
local seenNames = {}
collectFromSprite(source, nil, allEntries, seenNames)
for _, category in ipairs(INPUT_CATEGORY_ORDER) do
  local target = targets[category] or openIfExists(targetPaths[category])
  if target then
    collectFromSprite(target, category, allEntries, seenNames)
    if not targets[category] then
      target:close()
    end
  end
end

local generalEntries = {}
local grouped = { B = {}, C = {}, D = {}, E = {} }
for _, entry in ipairs(allEntries) do
  if entry.category then
    table.insert(grouped[entry.category], entry)
  else
    table.insert(generalEntries, entry)
  end
end

for _, category in ipairs(OUTPUT_CATEGORY_ORDER) do
  placeEntries(grouped[category], category == "B")
end

writeEntries(source, generalEntries, true)
source:saveAs(sourcePath)
source:close()

for _, category in ipairs(OUTPUT_CATEGORY_ORDER) do
  local target = targets[category]
  target:resize(SHEET_COLUMNS * TILE_SIZE, SHEET_ROWS * TILE_SIZE)
  writeEntries(target, grouped[category], false)
  target:saveAs(targetPaths[category])
  target:close()
  io.stdout:write(
    "Wrote " .. tostring(#grouped[category]) .. " slice(s) to " ..
    targetPaths[category] .. "\n"
  )
end

io.stdout:write(
  "Wrote " .. tostring(#generalEntries) .. " remaining slice(s) to " ..
  sourcePath .. "\n"
)
