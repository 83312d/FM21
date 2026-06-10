-- Priority dequeue for fm21:queue:{cityTag} (Broadcast Semantics §4, U13).
-- LRANGE → highest priority, FIFO within tier (oldest = tail = highest index) → LREM.
-- Returns tab-delimited line(s): uri<TAB>type<TAB>title<TAB>artist<TAB>duration<TAB>part
-- (Tab — Yandex signed URLs may contain '|' in the path.)
-- NEWS_PAIR with meta.stinger_uri returns two lines (stinger then main).

local TYPE_PRIORITY = {
  AD = 100,
  NEWS_PAIR = 80,
  MUSIC_ORDER = 50,
  MUSIC = 10,
}

local function item_priority(item)
  if item.priority ~= nil then
    return tonumber(item.priority) or 0
  end
  if item.type ~= nil and TYPE_PRIORITY[item.type] ~= nil then
    return TYPE_PRIORITY[item.type]
  end
  return 0
end

local FIELD_SEP = string.char(9)

local function escape_field(value)
  if value == nil then
    return ""
  end
  return tostring(value):gsub(FIELD_SEP, " ")
end

local function format_line(uri, item, part)
  local meta = item.meta or {}
  local title = escape_field(meta.title or "")
  local artist = escape_field(meta.artist or "")
  local duration = escape_field(meta.duration_sec or 0)
  local type_ = escape_field(item.type or "MUSIC")
  return escape_field(uri)
    .. FIELD_SEP
    .. type_
    .. FIELD_SEP
    .. title
    .. FIELD_SEP
    .. artist
    .. FIELD_SEP
    .. duration
    .. FIELD_SEP
    .. escape_field(part)
end

local key = KEYS[1]
local items = redis.call("LRANGE", key, 0, -1)
if #items == 0 then
  return nil
end

local best_raw = nil
local best_pri = -1
local best_idx = -1

for i, raw in ipairs(items) do
  local ok, item = pcall(cjson.decode, raw)
  if ok and item ~= nil then
    local pri = item_priority(item)
    local idx = i - 1
    if pri > best_pri or (pri == best_pri and idx > best_idx) then
      best_pri = pri
      best_idx = idx
      best_raw = raw
    end
  end
end

if best_raw == nil then
  return nil
end

redis.call("LREM", key, 1, best_raw)

local ok, item = pcall(cjson.decode, best_raw)
if not ok or item == nil then
  return nil
end

local meta = item.meta or {}
local stinger = meta.stinger_uri
if item.type == "NEWS_PAIR" and stinger ~= nil and stinger ~= "" then
  return {
    format_line(stinger, item, "stinger"),
    format_line(item.uri, item, "main"),
  }
end

return format_line(item.uri, item, "main")
