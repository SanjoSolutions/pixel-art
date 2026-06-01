local LEGACY_TOOL_MARKER = "pixel-car-renderer:furniture-metadata:v1"
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

local ALIGNMENT_ROWS = {
  { "none" },
  { "back-left", "back", "back-right" },
  { "left", "center", "right" },
  { "front-left", "front", "front-right" },
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

local function splitNames(text)
  local names = {}
  for name in tostring(text or ""):gmatch("[^,]+") do
    name = name:gsub("^%s+", ""):gsub("%s+$", "")
    if name ~= "" then
      names[name] = true
    end
  end
  return names
end

local function defaultFileName(slice)
  local name = tostring(slice.name or "")
  if name == "" then
    return "manual_placeholder.png"
  end
  return name .. ".png"
end

local function decodeSliceData(slice)
  if slice.data and slice.data ~= "" and json then
    local ok, data = pcall(json.decode, slice.data)
    if ok and data and (data.tool == nil or data.tool == LEGACY_TOOL_MARKER) then
      return {
        tool = data.tool,
        index = tonumber(data.index),
        file = data.file,
        manual = data.manual,
        placeholder = data.placeholder,
        alignment = data.alignment,
        width = data.width,
        keepProportions = data.keepProportions,
      }
    end
  end
  return {
    file = defaultFileName(slice),
    placeholder = tostring(slice.name or ""):match("^manual_placeholder_") ~= nil,
  }
end

local function selectedSlices(sprite)
  if app.range then
    local slices = app.range.slices
    if slices and #slices > 0 then
      return slices
    end
  end
  return {}
end

local function findSlicesByName(sprite, names)
  local slices = {}
  for _, slice in ipairs(sprite.slices) do
    if names[slice.name] then
      table.insert(slices, slice)
    end
  end
  return slices
end

local function targetedSlices(sprite)
  local names = splitNames(scriptParam("slices", ""))
  if next(names) then
    return findSlicesByName(sprite, names)
  end
  return selectedSlices(sprite)
end

local function normalizedAlignment(alignment)
  if alignment == nil or alignment == "" then
    return nil
  end
  if VALID_ALIGNMENTS[alignment] then
    return alignment
  end
  return nil
end

local function sliceAlignment(slice)
  return normalizedAlignment(decodeSliceData(slice).alignment)
end

local function sharedAlignment(slices)
  local current = nil
  local mixed = false
  for _, slice in ipairs(slices) do
    local alignment = sliceAlignment(slice) or "none"
    if current == nil then
      current = alignment
    elseif current ~= alignment then
      mixed = true
    end
  end
  return current or "none", mixed
end

local function setAlignment(slice, alignment)
  if not VALID_ALIGNMENTS[alignment] then
    error("Invalid alignment: " .. tostring(alignment))
  end
  local metadata = decodeSliceData(slice)
  metadata.tool = metadata.tool or LEGACY_TOOL_MARKER
  if metadata.index ~= nil then
    metadata.index = tonumber(metadata.index)
  end
  if type(metadata.file) ~= "string" or metadata.file == "" then
    metadata.file = defaultFileName(slice)
  end
  if metadata.placeholder == nil then
    metadata.placeholder = tostring(slice.name or ""):match("^manual_placeholder_") ~= nil
  end
  metadata.alignment = alignment
  slice.data = json.encode(metadata)
end

local function applyAlignment(slices, alignment)
  app.transaction(function()
    for _, slice in ipairs(slices) do
      setAlignment(slice, alignment)
    end
  end)
  app.refresh()
end

local function notify(message)
  if app.tip then
    pcall(function()
      app.tip(message)
    end)
  end
end

local function openSpriteFromParams()
  local source = scriptParam("source", nil)
  if source then
    return app.open(source)
  end
  return app.sprite or app.activeSprite
end

local function failNoSlices()
  if scriptParam("source", nil) then
    error("No slices selected/found.")
  end
  app.alert("Select one or more slices with the Slice tool, then run this script.")
end

local sprite = openSpriteFromParams()
if not sprite then
  app.alert("Open interior_furniture.aseprite before running this script.")
  return
end
if not json then
  app.alert("Aseprite JSON scripting support is required.")
  return
end

local slices = targetedSlices(sprite)
if #slices == 0 then
  failNoSlices()
  return
end

local alignmentParam = scriptParam("alignment", nil)
if alignmentParam then
  if not VALID_ALIGNMENTS[alignmentParam] then
    error("Invalid alignment: " .. tostring(alignmentParam))
  end
  applyAlignment(slices, alignmentParam)
  local savePath = scriptParam("save", nil)
  if savePath then
    sprite:saveAs(savePath)
  end
  io.stdout:write(
    "Set alignment=" .. alignmentParam .. " on " .. #slices .. " slice(s)\n"
  )
  return
end

local selectedAlignment, mixed = sharedAlignment(slices)
local stateText = "Selected slices: " .. #slices
if mixed then
  stateText = stateText .. " (mixed alignment)"
end

local dialog = Dialog{ title = "Furniture Slice Alignment" }
dialog:label{ text = stateText }
dialog:newrow()

for _, row in ipairs(ALIGNMENT_ROWS) do
  for _, alignment in ipairs(row) do
    local alignmentValue = alignment
    dialog:radio{
      id = "alignment_" .. alignmentValue:gsub("-", "_"),
      text = alignmentValue,
      selected = selectedAlignment == alignmentValue,
      onclick = function()
        selectedAlignment = alignmentValue
      end,
    }
  end
  dialog:newrow()
end

dialog:button{
  id = "apply",
  text = "Apply",
  onclick = function()
    applyAlignment(slices, selectedAlignment)
    notify("Set alignment=" .. selectedAlignment .. " on " .. #slices .. " slice(s)")
    dialog:close()
  end,
}
dialog:button{
  id = "close",
  text = "Close",
  onclick = function()
    dialog:close()
  end,
}
dialog:show{ wait = false }
