#!/usr/bin/env liquidsoap
#
# FM21 broadcast — one Icecast mount per city (Broadcast Semantics §2, §9).
#
# Redis consumption (ADR-001 Appendix A — poll-based, U4 spike):
#   - request.dynamic.list calls redis-cli on each block boundary.
#   - retry_delay = 1.0 s (≤ 2 s poll cap; empty queue → static bed within 5 s dead-air limit).
#   - Key: fm21:queue:{cityTag} (list; LPUSH head, RPOP tail in Phase 1).
#   - Phase 1: only AD items; tail RPOP is sufficient until mixed-type Phase 2.
#   - Phase 2+: replace dequeue_queue_item with priority scan (LRANGE + LREM) per §4.
#
# Filler: rotate data/music/static/bed-*.mp3 when Redis returns nothing.
# Crossfade: 2 s between blocks.
# Metadata: HSET fm21:current:{cityTag} on track start (metadata service U8).

settings.init.hide_on_start := true

redis_host = "redis"
icecast_host = "icecast"
icecast_port = 8000
# Must match broadcast/icecast/icecast.xml source-password (env ICECAST_SOURCE_PASSWORD).
icecast_password = environment.get("ICECAST_SOURCE_PASSWORD") ?? "fm21dev"

cities_yaml = "/broadcast/liquidsoap/cities.yaml"
music_glob = "/data/music/static/bed-*.mp3"

crossfade_sec = 2.0
poll_retry_sec = 1.0

# --- helpers ----------------------------------------------------------------

def load_city_tags() =
  process.read.lines(
    "grep -E '^[[:space:]]+- tag:' #{cities_yaml} | sed 's/.*tag: //' | tr -d '\"'"
  )
end

bed_files = ref([])
bed_index = ref(0)

def refresh_bed_files() =
  files =
    process.read.lines("ls -1 #{music_glob} 2>/dev/null | sort")
  bed_files := files
end

refresh_bed_files()

def next_bed_uri() =
  files = bed_files()
  n = list.length(files)
  if n == 0 then
    log("fm21.filler warning: no bed files in #{music_glob}; using silence")
    "silence://"
  else
    i = bed_index()
    bed_index := (i + 1) mod n
    list.nth(files, i)
  end
end

# RPOP tail item; extract uri + type from queue JSON. Empty uri => use filler.
def dequeue_queue_item(city_tag) =
  cmd =
    "sh -c 'ITEM=$(redis-cli -h #{redis_host} RPOP fm21:queue:#{city_tag} 2>/dev/null || true); " ^
    "if [ -n \"$ITEM\" ]; then " ^
    "URI=$(echo \"$ITEM\" | sed -n \"s/.*\\\"uri\\\"[[:space:]]*:[[:space:]]*\\\"\\([^\\\"]*\\)\\\".*/\\1/p\"); " ^
    "TYPE=$(echo \"$ITEM\" | sed -n \"s/.*\\\"type\\\"[[:space:]]*:[[:space:]]*\\\"\\([^\\\"]*\\)\\\".*/\\1/p\"); " ^
    "TITLE=$(echo \"$ITEM\" | sed -n \"s/.*\\\"title\\\"[[:space:]]*:[[:space:]]*\\\"\\([^\\\"]*\\)\\\".*/\\1/p\"); " ^
    "echo \"$URI|$TYPE|$TITLE\"; fi'"
  line = list.hd(default="", process.read.lines(cmd))
  if line == "" then
    ("", "", "")
  else
    parts = string.split(separator="|", line)
    uri = list.nth(default="", parts, 0)
    type_ = list.nth(default="AD", parts, 1)
    title = list.nth(default="Voice ad", parts, 2)
    (uri, type_, title)
  end
end

def update_now_playing(city_tag, m) =
  title = m["title"] ?? ""
  artist = m["artist"] ?? ""
  type_ = m["fm21_type"] ?? "MUSIC"
  started = string(time())
  ignore(
    process.run(
      "redis-cli -h #{redis_host} HMSET fm21:current:#{city_tag} " ^
      "type #{type_} title #{title} artist #{artist} started_at #{started}"
    )
  )
end

# --- per-city pipeline ------------------------------------------------------

def annotated_request(uri, type_, title) =
  request.create(
    'annotate:fm21_type="#{type_}",title="#{title}":#{uri}'
  )
end

def make_next_request(city_tag) =
  fun () ->
    (uri, type_, title) = dequeue_queue_item(city_tag)
    req =
      if uri != "" then
        log("fm21.queue #{city_tag}: #{type_} #{uri}")
        annotated_request(uri, type_, title)
      else
        bed = next_bed_uri()
        log("fm21.filler #{city_tag}: #{bed}")
        annotated_request(bed, "MUSIC", "FM21 Bed")
      end
    [req]
  end
end

def make_city_stream(city_tag) =
  dynamic =
    request.dynamic.list(
      id="fm21-#{city_tag}",
      retry_delay=poll_retry_sec,
      make_next_request(city_tag)
    )
  tagged =
    source.on_metadata(
      fun (m) ->
        update_now_playing(city_tag, m)
        m
      end,
      dynamic
    )
  mksafe(crossfade(duration=crossfade_sec, tagged))
end

def mount_city(city_tag) =
  stream = make_city_stream(city_tag)
  output.icecast(
    %mp3(bitrate=128, samplerate=44100, stereo=true),
    host=icecast_host,
    port=icecast_port,
    password=icecast_password,
    mount="/#{city_tag}",
    name="FM21 #{city_tag}",
    description="FM21 city stream — #{city_tag}",
    genre="Radio",
    stream
  )
end

city_tags = load_city_tags()
log("fm21.boot cities=#{string.concat(separator=', ', city_tags)}")
list.iter(mount_city, city_tags)
