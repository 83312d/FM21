#!/usr/bin/env liquidsoap

settings.init.allow_root := true

redis_host = "redis"
icecast_host = "icecast"
icecast_port = 8000
icecast_password = environment.get("ICECAST_SOURCE_PASSWORD") ?? "fm21dev"

cities_yaml = "/broadcast/liquidsoap/cities.yaml"
dequeue_script = "/broadcast/liquidsoap/dequeue.sh"
music_glob = "/data/music/static/bed-*.mp3"
crossfade_sec = 2.0
poll_retry_sec = 1.0
http_probe_timeout_sec = 4.0

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

def is_http_uri(uri) =
  string.match(pattern="^https?://", uri)
end

# Yandex signed URLs often reject HEAD; play directly and rely on decoder fallback.
def probe_http_uri(uri) =
  uri
end

def parse_dequeue_line(line) =
  # Tab-separated — Yandex URLs may contain '|' in signed paths.
  parts = string.split(separator="\t", line)
  uri = list.nth(default="", parts, 0)
  type_ = list.nth(default="MUSIC", parts, 1)
  title = list.nth(default="", parts, 2)
  artist = list.nth(default="", parts, 3)
  duration = list.nth(default="0", parts, 4)
  part = list.nth(default="main", parts, 5)
  {uri=uri, type_=type_, title=title, artist=artist, duration=duration, part=part}
end

def escape_meta_value(s) =
  string.replace(pattern="\"", fun (_) -> "'", s)
end

def dequeue_queue_lines(city_tag) =
  process.read.lines("#{dequeue_script} #{city_tag} #{redis_host}")
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

def annotated_request(row) =
  type_ = row.type_
  title = escape_meta_value(row.title)
  artist = escape_meta_value(row.artist)
  duration = row.duration
  part = row.part
  uri = row.uri
  request.create(
    "annotate:fm21_type=\"#{type_}\",title=\"#{title}\",artist=\"#{artist}\",duration=\"#{duration}\",fm21_part=\"#{part}\":#{uri}"
  )
end

def row_to_request(row) =
  playable = probe_http_uri(row.uri)
  if playable == "" then
    annotated_request({
      uri=next_bed_uri(),
      type_="MUSIC",
      title="FM21 Bed",
      artist="",
      duration="8",
      part="filler"
    })
  else
    annotated_request({
      uri=playable,
      type_=row.type_,
      title=row.title,
      artist=row.artist,
      duration=row.duration,
      part=row.part
    })
  end
end

def build_next_requests(city_tag) =
  lines = dequeue_queue_lines(city_tag)
  if list.length(lines) == 0 then
    [
      annotated_request({
        uri=next_bed_uri(),
        type_="MUSIC",
        title="FM21 Bed",
        artist="",
        duration="8",
        part="filler"
      })
    ]
  else
    list.map(row_to_request, list.map(parse_dequeue_line, lines))
  end
end

def make_next_request(city_tag) =
  fun () -> build_next_requests(city_tag)
end

def tag_metadata(city_tag, m) =
  part = m["fm21_part"] ?? "main"
  if part == "main" or part == "filler" or part == "stinger" then
    ignore(update_now_playing(city_tag, m))
  end
end

# NEWS_PAIR stinger→main is one block (FG6): no crossfade between parts.
# request.dynamic.list batches all lines from one dequeue.sh call before the
# next poll — AE2 no-interrupt holds for the full pair.
def default_block_crossfade(a, b) =
  add(
    normalize=false,
    [
      fade.in(duration=crossfade_sec, type="sin", b.source),
      fade.out(duration=crossfade_sec, type="sin", a.source)
    ]
  )
end

def block_transition(a, b) =
  a_type = a.metadata["fm21_type"] ?? ""
  b_type = b.metadata["fm21_type"] ?? ""
  a_part = a.metadata["fm21_part"] ?? ""
  b_part = b.metadata["fm21_part"] ?? ""
  if
    a_type == "NEWS_PAIR"
  and
    b_type == "NEWS_PAIR"
  and
    a_part == "stinger"
  and
    b_part == "main"
  then
    sequence([a.source, b.source])
  else
    default_block_crossfade(a, b)
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
      dynamic,
      fun (m) -> tag_metadata(city_tag, m)
    )
  mksafe(cross(duration=crossfade_sec, block_transition, tagged))
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
