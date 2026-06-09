#!/usr/bin/env liquidsoap

settings.init.allow_root := true

redis_host = "redis"
icecast_host = "icecast"
icecast_port = 8000
icecast_password = environment.get("ICECAST_SOURCE_PASSWORD") ?? "fm21dev"

cities_yaml = "/broadcast/liquidsoap/cities.yaml"
music_glob = "/data/music/static/bed-*.mp3"
crossfade_sec = 2.0
poll_retry_sec = 1.0

def load_city_tags() =
  process.read.lines(
    "grep -E '^[[:space:]]+- tag:' #{cities_yaml} | sed 's/.*tag: //' | tr -d '\"'"
  )
end

bed_files = ref([])
bed_index = ref(0)

def refresh_bed_files() =
  files = process.read.lines("ls -1 #{music_glob} 2>/dev/null | sort")
  bed_files := files
end

refresh_bed_files()

def next_bed_uri() =
  files = bed_files()
  n = list.length(files)
  if n == 0 then
    "silence:"
  else
    i = bed_index()
    bed_index := (i + 1) mod n
    list.nth(files, i)
  end
end

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
    ["", "", ""]
  else
    string.split(separator="|", line)
  end
end

def update_now_playing(city_tag, m) =
  title = m["title"] ?? ""
  artist = m["artist"] ?? ""
  type_ = m["fm21_type"] ?? "MUSIC"
  duration = m["duration"] ?? "8"
  started = string(time())
  ignore(
    process.run(
      process.quote.command(
        "redis-cli",
        args=["-h", redis_host, "HMSET", "fm21:current:#{city_tag}", "type", type_, "title", title, "artist", artist, "started_at", started, "duration_sec", duration]
      )
    )
  )
end

def annotated_request(uri, type_, title) =
  request.create('annotate:fm21_type="#{type_}",title="#{title}":#{uri}')
end

def build_next_requests(city_tag) =
  parts = dequeue_queue_item(city_tag)
  uri = list.nth(default="", parts, 0)
  type_ = list.nth(default="AD", parts, 1)
  title = list.nth(default="Voice ad", parts, 2)
  if uri != "" then
    [annotated_request(uri, type_, title)]
  else
    [annotated_request(next_bed_uri(), "MUSIC", "FM21 Bed")]
  end
end

def make_next_request(city_tag) =
  fun () -> build_next_requests(city_tag)
end

def tag_metadata(city_tag, m) =
  ignore(update_now_playing(city_tag, m))
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
      dynamic,
      fun (m) -> tag_metadata(city_tag, m)
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
    description="FM21 #{city_tag}",
    genre="Radio",
    stream
  )
end

city_tags = load_city_tags()
list.iter(mount_city, city_tags)
