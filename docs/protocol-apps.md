# More tab apps protocol

Speech to text (`server/asr/`) and image generation (`server/imagegen/`) are independent modules.
All routes below require the normal next-agent `na_auth` cookie, including audio, exports, and image files.
Use same-origin fetch with cookies; reuse the core login UI. There is no app-specific login/password.
All successful JSON routes return HTTP 200, including creation, finish and retry. Numeric timestamps are Unix
seconds (floating point); durations in ASR are seconds, image job `duration_ms` is milliseconds. URLs are
same-origin relative URLs. Secrets are returned in clear to authenticated clients.

HTTP errors use `{"detail":"message"}`; FastAPI field/type errors use `{"detail":[...]}`.
Every route can return 401 for missing/invalid authentication and 422 for malformed typed input.
Resource routes return 404 for absent IDs. Route-specific errors are listed below.
Jobs and recordings survive closing the page or disconnecting from the event feed.

## ASR settings and storage

Config: `data/config/asr.toml`, registered as `asr` with the core raw config editor
(`GET/PUT /api/config/raw?file=asr`). Form changes and valid raw config reloads affect subsequent work.

```toml
api_base = "https://api.openai.com/v1"
api_key = ""
model = "whisper-1"
language = ""
prompt = ""
chunk_sec = 15
retranscribe_on_finish = false
```

| Key | Type/default | Meaning / limits |
|---|---|---|
| api_base | string, above | HTTP(S) API root, including `/v1` if needed; whitespace/trailing slash stripped. |
| api_key | string, `""` | Bearer token. Empty clears it; never masked in responses. |
| model | string, `"whisper-1"` | Upstream transcription model; empty passes through for provider default. |
| language | string, `""` | Language hint (e.g. `zh`, `en`); empty omits it upstream. |
| prompt | string, `""` | Vocabulary/context hint; combined with previous recognized segment tail (200 chars), final 800 chars sent. |
| chunk_sec | integer, 15 | 5..60 inclusive; client WAV chunk interval. Full-file splitting targets 60 seconds independently. |
| retranscribe_on_finish | boolean, false | Re-recognize complete live recording after final audio assembly. Deferred (`live:false`) recordings always do this. |

| Method | Path | Request | Response example / errors |
|---|---|---|---|
| GET | `/api/asr/settings` | None | `{"api_base":"https://api.openai.com/v1","api_key":"","model":"whisper-1","language":"","prompt":"","chunk_sec":15,"retranscribe_on_finish":false}` |
| PATCH | `/api/asr/settings` | JSON partial config fields above; null fields ignored. Optional `clear_key:boolean=false` also clears key. | Full settings object, as GET. Omitted fields retained. 422 invalid URL or chunk interval. |
| POST | `/api/asr/settings/test` | None; tests saved settings | `{"ok":true,"detail":"Connected, 1 models","models":["whisper-1"]}`. Missing key/network/non-200 produces HTTP 200 with `ok:false`, descriptive `detail`, `models:[]`. Model list sorted, capped at 100. |

The upstream client calls `POST {api_base}/audio/transcriptions` as multipart (`file`, `model`,
`response_format=json`, optional `language`, `prompt`). All transcriptions share a one-request semaphore;
network errors and 5xx are retried once, other HTTP failures become segment errors immediately.
Each attempt times out after 120 seconds. Settings test calls `GET {api_base}/models` with a 15-second timeout.
HTTP clients honor proxy environment variables via httpx defaults.

Each recording lives in `data/asr/recordings/<id>/`: `meta.json`, live `chunks/<seq>.wav`, uploaded
`original.<extension>`, assembled playback `audio.m4a`. Temporary PCM/slice files are removed after processing.
No existing asr-web data or credentials are imported.

## ASR objects

Full public Recording example (GET detail and every recording mutation except chunk/retry/delete):

```json
{
  "id": "20261106-120000-a1b2",
  "title": "Meeting",
  "source": "record",
  "created_at": 1793966400.0,
  "duration": 15.0,
  "status": "done",
  "error": null,
  "size": 123456,
  "segments": [
    {"seq": 0, "start": 0.0, "end": 15.0, "text": "Hello", "status": "ok"}
  ],
  "text": "Hello",
  "edited": false,
  "starred": false,
  "progress": null
}
```

| Recording field | Type | Meaning |
|---|---|---|
| id | string | Opaque server-generated ID. |
| title | string | Trimmed title, at most 200 characters; default `Recording MM-DD HH:mm` for live creation. |
| source | `"record"` or `"upload"` | Microphone chunks or uploaded file. |
| created_at | number | Creation timestamp. |
| duration | number | Maximum chunk end during recording; decoded audio duration after processing. |
| status | `recording`, `processing`, `done`, `error` | Collecting chunks; assembling/transcribing; completed; pipeline failed/all pieces failed. |
| error | string or null | Recording-level failure. Individual segments may fail even when recording status is done. |
| size | integer | Bytes of saved playback M4A after assembly; raw bytes just after upload, zero before audio is available. |
| segments | Segment[] | Sorted ascending by seq. Replacement of an existing seq never duplicates it. |
| text | string | Resolved transcript: explicit edit if present, otherwise nonempty segment texts joined with newline. |
| edited | boolean | Whether an explicit transcript edit is stored (even an empty string). |
| starred | boolean | User bookmark; default false. |
| progress | `{done:integer,total:integer}` or null | Full transcription piece progress. Null before split planning and after completion/failure. |
| live | boolean, optional | `false` when created with deferred recognition; omission means true. |

Internal `pending` is never exposed. On disk `text:null` means derive from segments; public `text` is always
resolved to a string. `done` does not guarantee every segment succeeded: any successful or silent piece allows
the full pipeline to complete. Inspect segment statuses for retry UI.

Segment example:

```json
{"seq":2,"start":30.0,"end":45.0,"text":"","status":"error","error":"HTTP 401: boom"}
```

`seq` is the integer chunk/piece order, `start/end` are seconds from recording start, rounded to three decimals.
`text` is recognized text (trimmed upstream result) or `""`. `status` is `ok|error`; `error` is optional and present
on failure. Silent 16-bit PCM chunks are `ok` with empty text and cause no upstream call.

List entries are RecordingSummary objects, omitting segments/text/edited/live and adding `preview` (first 120
characters of resolved text):

```json
[{"id":"20261106-120000-a1b2","title":"Meeting","source":"record","created_at":1793966400.0,
  "duration":15.0,"status":"done","size":123456,"starred":false,"error":null,"progress":null,"preview":"Hello"}]
```

## ASR routes

In this table `R` means a full Recording JSON object illustrated above, and `S` means Segment JSON illustrated
above. Empty arrays are returned when listing has no matches. Query strings must be URL encoded.

| Method | Path | Query / body fields | Response / errors |
|---|---|---|---|
| GET | `/api/asr/recordings` | `q:string=""` | `[RecordingSummary]`, example above; newest ID first. Trimmed, case-insensitive substring search across title or resolved text. No pagination. |
| POST | `/api/asr/recordings` | JSON `{title?:string|null, live?:boolean=true}` | R, initially `status:"recording",segments:[],text:"",edited:false,size:0,progress:null`. Blank title selects default; max 200 chars. |
| POST | `/api/asr/recordings/upload` | Raw bytes, **not multipart**. Query `filename:string="audio"`, `title:string=""`. | R with `source:"upload",status:"processing"`; returns after body is saved, before recognition finishes. Title defaults to filename stem or `Upload`; max 200 chars. 400 empty body; 413 above **500 MiB** (524288000 bytes), partial directory removed. |
| GET | `/api/asr/recordings/{rid}` | Path `rid:string` | R. 404 invalid/absent recording. |
| POST | `/api/asr/recordings/{rid}/chunks` | Raw WAV bytes. Required query `seq:integer` (0..100000), `start:number`, `end:number` in seconds. | S, e.g. `{"seq":0,"start":0.0,"end":15.0,"text":"Hello","status":"ok"}`. Waits for live recognition. 400 wrong source, bad seq, empty body; 413 above **20 MiB** (20971520 bytes). Recognition failure is HTTP 200 S with `status:"error"`. |
| POST | `/api/asr/recordings/{rid}/finish` | JSON `{duration?:number|null}` | R immediately with `status:"processing"`; truthy duration updates known length, then asynchronous finalization starts. 400 for upload source. No chunks produces recording-level error asynchronously. |
| POST | `/api/asr/recordings/{rid}/retranscribe` | No body | R with `status:"processing",edited:false`; full audio is split/recognized again. 409 if audio is unavailable or status is recording/processing. Clears edited transcript; segments replaced after planning. |
| POST | `/api/asr/recordings/{rid}/segments/{seq}/retry` | Path `seq:integer`; no body | Replacement S. Uses saved live chunk, otherwise slices playback M4A over segment start/end. 404 absent segment; 409 audio not ready; 500 ffmpeg slicing failure. Recognition failure is HTTP 200 error S. Successful retry can recover error recording to done if saved playback exists. |
| PATCH | `/api/asr/recordings/{rid}` | JSON `{title?:string|null,text?:string|null,reset_text?:boolean=false,starred?:boolean|null}` | R. Blank/null title leaves it; nonblank trimmed/truncated to 200 chars. `text:null` or `reset_text:true` restores derived text; reset wins. Omitted text keeps edits. Text equal to current joined segments removes redundant edit. `text:""` stores explicit blank edit unless joined text is already blank. Null starred leaves it. |
| DELETE | `/api/asr/recordings/{rid}` | No body | `{"ok":true}`. Cancels/awaits background work and removes recording under its lock; deleted work cannot recreate metadata. |
| GET | `/api/asr/recordings/{rid}/audio` | Optional HTTP `Range` header | M4A bytes, `Content-Type: audio/mp4`, private max-age 3600. 404 until available. `Range: bytes=0-9` → 206, ten bytes and `Content-Range`; malformed/unsatisfiable range → 400/416 (Starlette). |
| GET | `/api/asr/recordings/{rid}/export` | `fmt:string="txt"`, `txt|srt` | Streamed UTF-8 `text/plain`. 400 other format. TXT honors edits; otherwise one nonempty segment per line. SRT always uses nonempty original segments, numbered from 1, timestamps `HH:MM:SS,mmm`. |

Example TXT body: `Hello\n`. Example SRT body:

```text
1
00:00:00,000 --> 00:00:15,000
Hello

```

Both export formats use `Content-Disposition: attachment; filename="export.txt";
filename*=UTF-8''Meeting.txt` (or `.srt`). Use the UTF-8 filename when downloading; forbidden filename characters
`\ / : * ? " < > |` and CR/LF are replaced with underscores. Non-ASCII titles are percent encoded.

## Live recording client sequence

1. Load settings. On the user's record tap, request mono microphone audio and start AudioContext (inside the
   gesture for iOS). Capture PCM, resample to 16 kHz mono, encode signed 16-bit WAV with a header per chunk.
   Use `chunk_sec` seconds per chunk; do not send MediaRecorder container fragments.
2. `POST /api/asr/recordings` with `{"title":"Meeting","live":true}`; retain the returned id. `live:false`
   stores chunks without recognizing until finish; the rest of the sequence is identical.
3. Upload chunks serially with increasing `seq` starting at zero and seconds from capture start, e.g.
   `POST /api/asr/recordings/<id>/chunks?seq=0&start=0&end=15`, WAV raw body. Include silent chunks so saved
   audio timing stays correct. The response is the segment to display, including any recognition error.
   Uploading the same seq replaces its saved segment. Keep a queue so all chunks finish before finalizing.
4. Stop capture, flush the final short WAV chunk, and await the entire upload queue. Then
   `POST /api/asr/recordings/<id>/finish` with `{"duration":31.2}`. The response is processing. Assembly uses
   chunk seq order; player audio becomes available when assembly completes. If configured, full recognition
   replaces live segment text/boundaries; otherwise live results are retained and status becomes done.
5. Refresh detail on `asr_changed` events or poll GET detail every two seconds while recording/processing.
   Events only invalidate; fetch the object. Stop polling on done/error. Show recording/segment errors and offer
   retry/retranscribe. Disconnecting the event feed does not cancel the recording's server work.

## Upload progress and restart behavior

Send the file directly with `fetch` or XHR to upload, passing `filename` in the query string. To show browser →
server byte progress, use XHR upload progress (`loaded/total`); the API streams directly to disk and returns the
recording id only after receipt. The response `size` is the received raw byte count. There is no server byte-progress
field or upload-progress event during receipt.

After receipt, status is processing. During conversion/silence planning `progress` is null: show an indeterminate
indicator. Then `progress:{done:0,total:N}` appears; each attempted piece (including silent/error pieces) increments
done. Progress measures attempted pieces, not successes or bytes. When finished/failed it becomes null; use status
and segment errors for the outcome. Every persisted pipeline update emits `asr_changed`.

At startup processing uploads and `pending:full` recordings resume full transcription; other processing recordings
resume live finalization. Recordings left recording for **more than six hours** are finalized; younger ones remain
recording. Per-recording locks serialize metadata updates and deletion. Upstream transcription is globally serial.

## Image settings and storage

Config `data/config/imagegen.toml`, raw-editor name `imagegen`. Valid config reloads affect subsequent jobs.

```toml
api_base = "https://api.openai.com/v1"
api_key = ""
models = ["gpt-image-2"]
default_model = "gpt-image-2"
reference_mode = "generations"
timeout = 300
```

| Key | Type/default | Meaning |
|---|---|---|
| api_base | string, above | HTTP(S) API root; trailing slash stripped. |
| api_key | string, `""` | Bearer key returned in clear; empty clears it. |
| models | string[], `["gpt-image-2"]` | User-managed picker list, trimmed/deduplicated, empty entries removed; not a model allowlist. |
| default_model | string, `"gpt-image-2"` | Used if job model omitted/empty; empty passes through to upstream. |
| reference_mode | `auto|edits|generations`, `generations` | Reference request routing, described below. |
| timeout | integer, 300 | At least 1 second, applied separately to each generation/edit/download request. |

| Method | Path | Request | Response / errors |
|---|---|---|---|
| GET | `/api/imagegen/settings` | None | `{"api_base":"https://api.openai.com/v1","api_key":"","models":["gpt-image-2"],"default_model":"gpt-image-2","reference_mode":"generations","timeout":300}` |
| PATCH | `/api/imagegen/settings` | JSON partial fields above; omitted/null retained, `models` replaces list. | Complete settings object as GET. 422 invalid URL/mode/timeout. |
| POST | `/api/imagegen/settings/models` | None, saved settings | `{"models":["gpt-image-2","other"]}` sorted/deduplicated upstream IDs from GET `{base}/models`. **Does not save** to picker list. 502 upstream/network/invalid models response. |
| POST | `/api/imagegen/settings/test` | None, saved settings | `{"ok":true,"detail":"Connected, 1 models","models":["gpt-image-2"]}`. HTTP 200 `{"ok":false,"detail":"...","models":[]}` on failure. |

Model discovery/testing uses a 15-second timeout. All HTTP requests honor environment proxy settings.
Each job has `data/imagegen/jobs/<id>/job.json`, reference files, optional mask, and output files. Safe generated
names (`reference-1.png`, `mask.png`, `image-1.png`, etc.) avoid collisions between duplicate input filenames.

## Image Job schema

```json
{
  "id":"20261106-120000-ab12cd",
  "prompt":"A tree",
  "params":{"n":1,"size":"1024x1024","quality":"high"},
  "model":"gpt-image-2",
  "references":[{"name":"reference-1.png","url":"/api/imagegen/files/20261106-120000-ab12cd/reference-1.png"}],
  "status":"done",
  "error":null,
  "images":[{"name":"image-1.png","url":"/api/imagegen/files/20261106-120000-ab12cd/image-1.png","width":1024,"height":1024,"bytes":123456}],
  "created_at":1793966400.0,
  "finished_at":1793966402.0,
  "duration_ms":2000,
  "revised_prompt":"A detailed tree"
}
```

| Field | Type | Meaning |
|---|---|---|
| id | string | Opaque job ID. |
| prompt | string | Original nonblank prompt. |
| params | object | Submitted options below (always n, other unset options omitted). |
| model | string | Resolved submitted/default model. |
| references | `{name:string,url:string}[]` | Saved reference images in submitted order; empty for text-only. |
| mask | `{name:string,url:string}`, optional | Saved mask, when supplied; preserved by retry. |
| status | `running|done|error` | Includes waiting for concurrency slot; completed with outputs; failed. |
| error | string or null | Failure detail; null for running/done. |
| images | `{name,url,width,height,bytes}[]` | Outputs on successful completion; initially empty. width/height integer or null if unavailable; bytes integer. Actual count follows upstream response. |
| created_at | number | Job submission timestamp. |
| finished_at | number or null | Completion/failure timestamp, including restart recovery. |
| duration_ms | integer or null | Submission-to-completion elapsed milliseconds, includes waiting for a slot. |
| revised_prompt | string, optional | Upstream revised prompt if provided (last nonempty one if several images return it). |

Image MIME/extension is detected from bytes (PNG/JPEG/WebP/GIF), otherwise requested format or PNG. Dimensions
are read from supported headers; unknown headers yield null. URLs require authentication; do not prepend API keys.

## Image generation request

`POST /api/imagegen/jobs` uses `multipart/form-data`. Let the browser set the boundary; use `FormData`.

| Field | Type/default | Validation / upstream meaning |
|---|---|---|
| prompt | required string | Must contain non-whitespace; forwarded as supplied. |
| model | optional string | Omitted/empty → configured default; arbitrary IDs accepted. |
| size | optional string | `auto` or positive integer `WxH`, e.g. `1024x1024`, `1536x1024`, `1024x1536`, `400x600`. |
| quality | optional string | `auto|low|medium|high`. |
| n | integer, 1 | 1..4 inclusive. |
| background | optional string | `auto|opaque|transparent`. |
| output_format | optional string | `png|jpeg|webp`. |
| output_compression | optional integer | 0..100 inclusive, requires output_format jpeg/webp. |
| moderation | optional string | `auto|low`. |
| images[] | repeated file, 0..8 | PNG/JPEG/WebP/GIF identified by magic bytes (client MIME ignored), at most **20 MiB each**. Order preserved. |
| mask | optional file | Same magic/20 MiB validation; requires at least one reference. No local alpha/dimension/PNG-only restriction. |

Unset optional fields are omitted upstream. `n` defaults to 1 and is sent. No streaming output API.
Validation: 422 field values/reference count/mask without image; 413 oversized reference/mask; 415 unsupported
image magic. Validation happens before creating a job. Invalid audio/image provider requests after creation become
persisted errors rather than synchronous HTTP errors.

Routing matches the CLI:

- Without references, all modes POST JSON to `{base}/images/generations`.
- With references and `generations`, POST JSON to that endpoint. One reference is `image:"data:image/png;base64,..."`;
  multiple references are `image:[data_url,...]`; mask is a data URL. JSON includes all submitted options.
- With `edits`, POST multipart to `{base}/images/edits`: one binary `image` or repeated `image[]`, optional binary
  `mask`; text fields model/prompt and supplied size/quality/background/output_format/n. As in the CLI, edits
  does not forward output_compression/moderation (they remain saved; auto fallback generations will forward them).
- `auto` tries edits, then generations on HTTP failure or missing/empty result data. Invalid JSON and transport/
  timeout errors fail the job without fallback. Explicit modes never fall back.

Results accept `data[].b64_json` or `data[].url` (HTTP(S) download or base64 data URL). Downloads do not include
the API Bearer key. The job becomes done after outputs are saved; no separate client request to the provider is needed.

## Image job routes and lifecycle

`J` below is the full Job object illustrated above.

| Method | Path | Query / body | Response / errors |
|---|---|---|---|
| POST | `/api/imagegen/jobs` | Multipart fields above | J immediately, `status:"running",images:[],error:null,finished_at:null,duration_ms:null`. |
| GET | `/api/imagegen/jobs` | `before:string=""`, `limit:integer=50` clamped 1..200 | `[J]` newest ID first; each item uses the complete Job example above. Empty example: `[]`. Exclusive before cursor: send last returned id for next page; no total/has_more envelope. |
| GET | `/api/imagegen/jobs/{id}` | Path id:string | J, including references/outputs/status/error. 404 absent/invalid ID. |
| DELETE | `/api/imagegen/jobs/{id}` | No body | `{"ok":true}` after cancelling/awaiting active or queued work and deleting all files. 404 absent ID. |
| POST | `/api/imagegen/jobs/{id}/retry` | No body | New J with a new id, same prompt/model/params/references/mask, status running. Original retained. Uses current saved connection/routing settings. 404 absent ID. |
| GET | `/api/imagegen/files/{id}/{name}` | Path strings, names from Job | File bytes with correct MIME and `Content-Disposition: inline; filename="image-1.png"` (actual name). Auth required; 404 unknown job/name, including job.json. |

Client: submit FormData, display returned running job, then refresh GET detail on `imagegen_changed` or poll while
running. Several jobs may be submitted; at most **two** make upstream requests concurrently; waiting jobs still
show running. Done shows image URLs; error shows detail and Retry/Delete actions. Retry creates a separate job.
Delete removes the card; the following GET returns 404. Closing the page does not cancel work.
At server startup every persisted running job becomes error with `error:"Server restarted"` and completion time;
it is not automatically resubmitted. Use Retry explicitly.

## Global events

Subscribe through the existing authenticated `/ws/events` connection (`docs/protocol.md` describes the core
hello/envelope). These payloads are invalidations; they contain no transcript/image bytes and are not a durable
replacement for GET/list. On connect/reconnect fetch current lists/details to cover missed changes.

```json
{"type":"asr_changed","module":"asr","id":"20261106-120000-a1b2"}
{"type":"imagegen_changed","module":"imagegen","id":"20261106-120000-ab12cd","status":"done"}
```

ASR fires after creation, accepted upload, segment replacement/retry, metadata patch, finish/retranscribe status
change, each persisted processing/progress/completion/error update, and deletion. On deletion the object no longer
exists: refresh the list or handle detail 404. It does not fire for every received upload byte.
Image events fire when a job is created (`running`), completes (`done`), fails (`error`, including restart), or is
deleted (`deleted`, event-only status). Retry emits running for the new id. Refresh the affected job/list.
