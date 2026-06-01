local TOOL_MARKER = "pixel-car-renderer:furniture-metadata:v1"
local AUTO_COLOR = { r = 64, g = 169, b = 255, a = 255 }
local MANUAL_COLOR = { r = 0, g = 230, b = 118, a = 255 }
local PLACEHOLDER_COLOR = { r = 255, g = 176, b = 0, a = 255 }

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

local function metadataFor(entry)
  local metadata = {
    tool = TOOL_MARKER,
    index = tonumber(entry.index) or 0,
    file = entry.file,
  }
  if entry.manual == true then
    metadata.manual = true
  end
  if entry.placeholder == true then
    metadata.placeholder = true
  end
  if entry.alignment ~= nil then
    metadata.alignment = entry.alignment
  end
  if entry.width ~= nil then
    metadata.width = entry.width
  end
  if entry.keepProportions ~= nil then
    metadata.keepProportions = entry.keepProportions
  end
  return metadata
end

local function setSliceColor(slice, metadata)
  if not Color then
    return
  end
  local color = AUTO_COLOR
  if metadata.manual == true then
    color = MANUAL_COLOR
  elseif metadata.placeholder == true then
    color = PLACEHOLDER_COLOR
  end
  pcall(function()
    slice.color = Color(color)
  end)
end

local function clearSlices(sprite)
  for index = #sprite.slices, 1, -1 do
    sprite:deleteSlice(sprite.slices[index])
  end
end

local sourcePath = scriptParam("source", "interior_furniture.aseprite")
local sheetPath = scriptParam("sheet", "output/interior_furniture.png")
local manifestPath = scriptParam("manifest", "output/furniture_manifest.json")
local replacementSheetPath = scriptParam("replacement-sheet", "")
local replacementManifestPath = scriptParam("replacement-manifest", "")
local preserveLayout = scriptParam("preserve-layout", "1") ~= "0"
local tileSize = tonumber(scriptParam("tile-size", "32")) or 32

local function decodeSliceData(slice)
  if slice.data and slice.data ~= "" and json then
    local ok, data = pcall(json.decode, slice.data)
    if ok and data then
      return data
    end
  end
  return {}
end

local function existingSliceEntry(slice)
  local bounds = slice.bounds
  local x = math.floor(bounds.x / tileSize + 0.5) * tileSize
  local y = math.floor(bounds.y / tileSize + 0.5) * tileSize
  local right = math.floor((bounds.x + bounds.width) / tileSize + 0.5) * tileSize
  local bottom = math.floor((bounds.y + bounds.height) / tileSize + 0.5) * tileSize
  return {
    name = slice.name,
    x = x,
    y = y,
    w = math.max(tileSize, right - x),
    h = math.max(tileSize, bottom - y),
    metadata = decodeSliceData(slice),
  }
end

local function roundUp(value, multiple)
  return math.ceil(value / multiple) * multiple
end

local function rectsOverlap(left, right)
  return left.x < right.x + right.w and
    left.x + left.w > right.x and
    left.y < right.y + right.h and
    left.y + left.h > right.y
end

local function rectIsFree(rect, occupied)
  for _, placed in ipairs(occupied) do
    if rectsOverlap(rect, placed) then
      return false
    end
  end
  return true
end

local function betterPlacement(candidate, currentBest, preferredX, preferredY, canvasWidth, canvasHeight)
  if currentBest == nil then
    return true
  end
  local candidateWidth = math.max(canvasWidth, candidate.x + candidate.w)
  local candidateHeight = math.max(canvasHeight, candidate.y + candidate.h)
  local bestWidth = math.max(canvasWidth, currentBest.x + currentBest.w)
  local bestHeight = math.max(canvasHeight, currentBest.y + currentBest.h)
  local candidateGrowth = candidateWidth * candidateHeight - canvasWidth * canvasHeight
  local bestGrowth = bestWidth * bestHeight - canvasWidth * canvasHeight
  if candidateGrowth ~= bestGrowth then
    return candidateGrowth < bestGrowth
  end
  local candidateDistance = math.abs(candidate.x - preferredX) + math.abs(candidate.y - preferredY)
  local bestDistance = math.abs(currentBest.x - preferredX) + math.abs(currentBest.y - preferredY)
  if candidateDistance ~= bestDistance then
    return candidateDistance < bestDistance
  end
  if candidate.y ~= currentBest.y then
    return candidate.y < currentBest.y
  end
  return candidate.x < currentBest.x
end

local function findFreePlacement(preferredX, preferredY, width, height, occupied, canvasWidth, canvasHeight)
  local searchWidth = roundUp(math.max(canvasWidth, preferredX + width), tileSize) + tileSize * 24
  local searchHeight = roundUp(math.max(canvasHeight, preferredY + height), tileSize) + tileSize * 24
  local best = nil
  for y = 0, searchHeight - height, tileSize do
    for x = 0, searchWidth - width, tileSize do
      local candidate = { x = x, y = y, w = width, h = height }
      if rectIsFree(candidate, occupied) and
          betterPlacement(candidate, best, preferredX, preferredY, canvasWidth, canvasHeight) then
        best = candidate
      end
    end
  end
  if best == nil then
    error("Could not place sprite without overlap.")
  end
  return best.x, best.y
end

local source = app.open(sourcePath)
if not source then
  error("Could not open " .. sourcePath)
end
local sheet = app.open(sheetPath)
if not sheet then
  error("Could not open " .. sheetPath)
end
local manifest = json.decode(readFile(manifestPath))
if not manifest or not manifest.sprites then
  error("Manifest has no sprites: " .. manifestPath)
end

local replacementSheet = nil
local replacementByName = {}
if replacementSheetPath ~= "" and replacementManifestPath ~= "" then
  replacementSheet = app.open(replacementSheetPath)
  if not replacementSheet then
    error("Could not open " .. replacementSheetPath)
  end
  local replacementManifest = json.decode(readFile(replacementManifestPath))
  if not replacementManifest or not replacementManifest.sprites then
    error("Replacement manifest has no sprites: " .. replacementManifestPath)
  end
  for _, entry in ipairs(replacementManifest.sprites) do
    replacementByName[entry.name] = entry
  end
end

local existingByName = {}
if preserveLayout then
  for _, slice in ipairs(source.slices) do
    existingByName[slice.name] = existingSliceEntry(slice)
  end
end

local placements = {}
local placementsByName = {}
local pendingPlacements = {}
local occupied = {}
local canvasWidth = preserveLayout and source.width or sheet.width
local canvasHeight = preserveLayout and source.height or sheet.height
for _, entry in ipairs(manifest.sprites) do
  local existing = existingByName[entry.name]
  local x = entry.x
  local y = entry.y
  local width = entry.w
  local height = entry.h
  if preserveLayout and existing == nil then
    table.insert(pendingPlacements, {
      entry = entry,
      existing = existing,
      preferredX = entry.x,
      preferredY = entry.y,
      w = entry.w,
      h = entry.h,
    })
  elseif existing and (entry.w > existing.w or entry.h > existing.h) then
    table.insert(pendingPlacements, {
      entry = entry,
      existing = existing,
      preferredX = existing.x,
      preferredY = existing.y,
      w = entry.w,
      h = entry.h,
    })
  else
    if existing then
      x = existing.x
      y = existing.y
      width = entry.w
      height = entry.h
    end
    local placement = {
      entry = entry,
      existing = existing,
      x = x,
      y = y,
      w = width,
      h = height,
    }
    placementsByName[entry.name] = placement
    table.insert(occupied, { x = x, y = y, w = width, h = height })
    canvasWidth = math.max(canvasWidth, x + width)
    canvasHeight = math.max(canvasHeight, y + height)
  end
end

for _, pending in ipairs(pendingPlacements) do
  local x, y = findFreePlacement(
    pending.preferredX,
    pending.preferredY,
    pending.w,
    pending.h,
    occupied,
    canvasWidth,
    canvasHeight
  )
  local placement = {
    entry = pending.entry,
    existing = pending.existing,
    x = x,
    y = y,
    w = pending.w,
    h = pending.h,
  }
  placementsByName[pending.entry.name] = placement
  table.insert(occupied, { x = x, y = y, w = pending.w, h = pending.h })
  canvasWidth = math.max(canvasWidth, x + pending.w)
  canvasHeight = math.max(canvasHeight, y + pending.h)
end

for _, entry in ipairs(manifest.sprites) do
  table.insert(placements, placementsByName[entry.name])
end

source:resize(canvasWidth, canvasHeight)
local sourceCel = source.cels[1]
local sheetCel = sheet.cels[1]
sourceCel.position = Point(0, 0)
sourceCel.image:clear()

clearSlices(source)
for _, placement in ipairs(placements) do
  local entry = placement.entry
  local cropEntry = entry
  local cropImage = sheetCel.image
  local replacementEntry = replacementByName[entry.name]
  if replacementSheet and replacementEntry and
      entry.manual ~= true and entry.placeholder ~= true and
      replacementEntry.reserved ~= true then
    cropEntry = replacementEntry
    cropImage = replacementSheet.cels[1].image
  end
  local crop = Image(
    cropImage,
    Rectangle(cropEntry.x, cropEntry.y, cropEntry.w, cropEntry.h)
  )
  sourceCel.image:drawImage(crop, Point(placement.x, placement.y))
  local slice = source:newSlice(
    Rectangle(placement.x, placement.y, placement.w, placement.h)
  )
  local metadata = metadataFor(entry)
  if placement.existing then
    metadata.index = tonumber(placement.existing.metadata.index) or metadata.index
    metadata.file = metadata.file or placement.existing.metadata.file
    if placement.existing.metadata.manual ~= nil then
      metadata.manual = placement.existing.metadata.manual
    end
    if placement.existing.metadata.placeholder ~= nil then
      metadata.placeholder = placement.existing.metadata.placeholder
    end
    if metadata.alignment == nil then
      metadata.alignment = placement.existing.metadata.alignment
    end
    if metadata.width == nil then
      metadata.width = placement.existing.metadata.width
    end
    if metadata.keepProportions == nil then
      metadata.keepProportions = placement.existing.metadata.keepProportions
    end
  end
  slice.name = entry.name
  slice.data = json.encode(metadata)
  setSliceColor(slice, metadata)
end

source:saveAs(sourcePath)
if replacementSheet then
  replacementSheet:close()
end
sheet:close()
source:close()
io.stdout:write(
  "Imported " .. #manifest.sprites .. " Aseprite slices to " ..
  sourcePath .. "\n"
)
