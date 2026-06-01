local LEGACY_TOOL_MARKER = "pixel-car-renderer:furniture-metadata:v1"

local AUTO_COLOR = { r = 64, g = 169, b = 255, a = 255 }
local MANUAL_COLOR = { r = 0, g = 230, b = 118, a = 255 }
local PLACEHOLDER_COLOR = { r = 255, g = 176, b = 0, a = 255 }
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

local function normalizeAlignment(alignment)
  if alignment == nil or alignment == "" then
    return nil
  end
  if VALID_ALIGNMENTS[alignment] then
    return alignment
  end
  return nil
end

local function parsePositiveNumber(value, label)
  local number = tonumber(value)
  if number == nil or number <= 0 then
    error("Invalid " .. label .. ": " .. tostring(value))
  end
  return number
end

local function parseBoolean(value, default)
  if value == nil then
    return default
  end
  if type(value) == "boolean" then
    return value
  end
  local normalized = tostring(value):lower()
  if normalized == "1" or normalized == "true" or
      normalized == "yes" or normalized == "on" then
    return true
  end
  if normalized == "0" or normalized == "false" or
      normalized == "no" or normalized == "off" then
    return false
  end
  error("Invalid boolean: " .. tostring(value))
end

local function isManual(slice)
  local metadata = decodeSliceData(slice)
  if metadata.manual ~= nil then
    return metadata.manual == true
  end
  local name = tostring(slice.name or "")
  return
    name:match("^wall") ~= nil or
    name:match("^rug") ~= nil or
    name:match("^floor") ~= nil
end

local function isPlaceholder(slice, metadata)
  if metadata.placeholder ~= nil then
    return metadata.placeholder == true
  end
  return tostring(slice.name or ""):match("^manual_placeholder_") ~= nil
end

local function setSliceColor(slice, metadata)
  if not Color then
    return
  end
  local color = AUTO_COLOR
  if metadata.manual == true then
    color = MANUAL_COLOR
  elseif isPlaceholder(slice, metadata) then
    color = PLACEHOLDER_COLOR
  end
  pcall(function()
    slice.color = Color(color)
  end)
end

local function setManual(slice, manual)
  local metadata = decodeSliceData(slice)
  metadata.tool = metadata.tool or LEGACY_TOOL_MARKER
  if type(metadata.file) ~= "string" or metadata.file == "" then
    metadata.file = defaultFileName(slice)
  end
  if metadata.placeholder == nil then
    metadata.placeholder = tostring(slice.name or ""):match("^manual_placeholder_") ~= nil
  end
  metadata.alignment = normalizeAlignment(metadata.alignment)
  metadata.manual = manual == true
  slice.data = json.encode(metadata)
  setSliceColor(slice, metadata)
end

local function setRenderWidth(slice, width, keepProportions)
  local metadata = decodeSliceData(slice)
  metadata.tool = metadata.tool or LEGACY_TOOL_MARKER
  if type(metadata.file) ~= "string" or metadata.file == "" then
    metadata.file = defaultFileName(slice)
  end
  if metadata.placeholder == nil then
    metadata.placeholder = tostring(slice.name or ""):match("^manual_placeholder_") ~= nil
  end
  metadata.alignment = normalizeAlignment(metadata.alignment)
  metadata.width = width
  metadata.keepProportions = keepProportions == true
  slice.data = json.encode(metadata)
  setSliceColor(slice, metadata)
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

local function manualStats(slices)
  local anyManual = false
  local allManual = #slices > 0
  for _, slice in ipairs(slices) do
    local manual = isManual(slice)
    anyManual = anyManual or manual
    allManual = allManual and manual
  end
  return anyManual, allManual
end

local function applyManual(slices, manual)
  app.transaction(function()
    for _, slice in ipairs(slices) do
      setManual(slice, manual)
    end
  end)
  app.refresh()
end

local function applyRenderWidth(slices, width, keepProportions)
  app.transaction(function()
    for _, slice in ipairs(slices) do
      setRenderWidth(slice, width, keepProportions)
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

local manualAction = rawget(_G, "FURNITURE_SLICE_MANUAL_ACTION")
_G.FURNITURE_SLICE_MANUAL_ACTION = nil
if manualAction ~= nil then
  local slices = targetedSlices(sprite)
  if #slices == 0 then
    failNoSlices()
    return
  end
  local manual = manualAction == true
  applyManual(slices, manual)
  local savePath = scriptParam("save", nil)
  if savePath then
    sprite:saveAs(savePath)
  end
  local label = manual and "manual" or "automatic"
  notify("Marked " .. #slices .. " slice(s) " .. label)
  io.stdout:write("Marked " .. #slices .. " slice(s) " .. label .. "\n")
  return
end

local widthAction = rawget(_G, "FURNITURE_SLICE_WIDTH_ACTION")
_G.FURNITURE_SLICE_WIDTH_ACTION = nil
if widthAction ~= nil then
  local slices = targetedSlices(sprite)
  if #slices == 0 then
    failNoSlices()
    return
  end
  local width = parsePositiveNumber(widthAction.width, "width")
  local keepProportions = parseBoolean(widthAction.keepProportions, true)
  applyRenderWidth(slices, width, keepProportions)
  local savePath = scriptParam("save", nil)
  if savePath then
    sprite:saveAs(savePath)
  end
  notify("Set width=" .. tostring(width) .. " on " .. #slices .. " slice(s)")
  io.stdout:write(
    "Set width=" .. tostring(width) ..
    ", keepProportions=" .. tostring(keepProportions) ..
    " on " .. #slices .. " slice(s)\n"
  )
  return
end

local manualParam = scriptParam("manual", nil)
if manualParam then
  local slices = targetedSlices(sprite)
  if #slices == 0 then
    failNoSlices()
    return
  end
  local manual = manualParam == "1" or manualParam == "true" or manualParam == "yes"
  applyManual(slices, manual)
  local savePath = scriptParam("save", nil)
  if savePath then
    sprite:saveAs(savePath)
  end
  io.stdout:write("Set manual=" .. tostring(manual) .. " on " .. #slices .. " slice(s)\n")
  return
end

local widthParam = scriptParam("width", nil)
if widthParam then
  local slices = targetedSlices(sprite)
  if #slices == 0 then
    failNoSlices()
    return
  end
  local width = parsePositiveNumber(widthParam, "width")
  local keepProportions = parseBoolean(scriptParam("keepProportions", nil), true)
  applyRenderWidth(slices, width, keepProportions)
  local savePath = scriptParam("save", nil)
  if savePath then
    sprite:saveAs(savePath)
  end
  io.stdout:write(
    "Set width=" .. tostring(width) ..
    ", keepProportions=" .. tostring(keepProportions) ..
    " on " .. #slices .. " slice(s)\n"
  )
  return
end

local slices = targetedSlices(sprite)
if #slices == 0 then
  failNoSlices()
  return
end

local anyManual, allManual = manualStats(slices)
local stateText = "Selected slices: " .. #slices
if anyManual and not allManual then
  stateText = stateText .. " (mixed manual state)"
end

local dialog = Dialog{ title = "Furniture Slice Metadata" }
dialog:label{ text = stateText }
dialog:check{
  id = "manual",
  text = "Manual",
  selected = allManual,
}
dialog:button{
  id = "apply",
  text = "Apply",
  onclick = function()
    applyManual(slices, dialog.data.manual)
    notify("Updated " .. #slices .. " slice(s)")
  end,
}
dialog:button{
  id = "toggle",
  text = "Toggle",
  onclick = function()
    applyManual(slices, not allManual)
    dialog:close()
    notify("Toggled manual on " .. #slices .. " slice(s)")
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
