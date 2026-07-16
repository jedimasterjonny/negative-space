# negative-space

Turns a Google Photos Takeout on a Synology NAS into a chronological, deduplicated,
metadata-clean library at `<takeout>-organised`, named `Year/MM - Month/YYYY-MM-DD HH-MM-SS.ext`
(plain sort == chronological).

**Design axiom:** the takeout is ~800 GB on an NFS mount; moving bytes over the wire is the
bottleneck. So all heavy I/O runs *on the NAS* over SSH — only the manifest and progress cross
the network. Read-only planning runs on the dev host over NFS (reuses the tested 3.13 code); the
destructive apply runs on the NAS.

## Pipeline

`extract` → pair + classify → resolve date/GPS → plan (dedupe) → `apply` (rewrite + move, on the NAS)

## Use

```sh
uv sync --locked
just check                                        # ruff + ty + pytest @ 100% branch cov
negative-space extract  /nfs/…/takeout            # untar .tgz on the NAS, live progress
negative-space organise /nfs/…/takeout            # dry run: audit report, no writes
negative-space organise --apply /nfs/…/takeout    # destructive; confirm prompt, --log <file>
```

`organise --apply` is idempotent/resumable (just re-run it) and tees every op to `--log`.

## Modules — `src/negative_space/`

| module | responsibility |
|---|---|
| `nas.py` | parse `/proc/mounts`, map NFS↔NAS paths, `ssh_argv` / `check_ssh` / `resolve_remote` |
| `archives.py`, `extract.py` | discover + untar `.tgz` on the NAS |
| `pairing.py` | media↔sidecar, motion-photo + `-edited` detection, content-aware classification |
| `exif.py` | `content_extension` (magic bytes, image+video), `read_capture` (Pillow EXIF / pure-Python mvhd) |
| `metadata.py` | resolve date+GPS: sidecar `photoTakenTime` → `-edited` inheritance → EXIF/mvhd fallback |
| `organise.py` | pure planner: dated folder + collision-free names; undated/non-rewritable → `unsorted/` |
| `plan.py` | concurrent NFS walk, `build_plan` (dedupe), `summarize` |
| `apply.py` | lower plan → JSON manifest; ship + run the executor over SSH, tee log, parse results |
| `_apply_executor.py` | **standalone, py3.8-compatible** executor, shipped to and run on the NAS |
| `cli.py` | typer app (`extract`, `organise`) |

## Matching algorithm — `pair_directory`, per folder

Runs over one album/year folder's raw file list. Sidecar names are *generated forward from the
media name*, never parsed back — the media name is the only part Takeout always preserves.

1. **Classify** each file → image / video / other. By extension; a missing, unknown, or mangled
   extension (anything but `.json`) falls back to a magic-byte content sniff.
2. **Sidecar** — for each media file, generate candidates and take the first that exists in the
   folder and isn't already claimed:
   - `f"{name}.supplemental-metadata.json"`, then truncated to 51 chars by cutting from the right
     (keep the trailing `.json`) — so `.supplemental-metadata`, and even the media extension, can
     be partly or wholly lost, but the media name survives.
   - numbered duplicate `photo(N).ext`: the base name's sidecar with `(N)` re-inserted *after*
     truncation → `photo.ext.supplemental-metadata(N).json` (the `(N)` belongs to the `(N)` media).
3. **Motion photo** — a video is the droppable half of a motion photo if its stem, or its whole
   name, equals an image stem in the folder: `MVIMG_x.MP4`↔`MVIMG_x.jpg`, or the still-named-after-
   the-video layout `PXL_x.MP`↔`PXL_x.MP.jpg`.
4. **Edited copy** — a media file `…-edited.ext` (or a length-truncated `-edi`/`-ed`/`-e`, but only
   where the full `-edited` would have overflowed 51 chars) with no sidecar of its own inherits the
   metadata of its original `….ext`, if that original is present in the folder.

Then resolve each keeper's date+GPS in order: its own sidecar `photoTakenTime` (UTC unix ts) →
the inherited original's sidecar → embedded EXIF / mvhd → undated (`unsorted/`). This forward
model took sidecar coverage from ~89% (reverse-regex) to 99.98%.

## Non-obvious decisions

- **The executor is py3.8-safe and import-free.** The NAS runs Python 3.8; the executor is shipped
  over SSH and run there. Everything else targets 3.13. Tested on 3.13 (it's a strict subset).
- **All times are naive UTC.** `photoTakenTime` is a UTC unix ts; EXIF is naive local. Unified to
  naive-UTC so they're comparable; filenames, mtime, and `DateTimeOriginal` are all UTC.
- **exiftool recipe:** `-all= -tagsFromFile @ -ICC_Profile -Orientation -Make -Model
  -DateTimeOriginal=… -GPS…` — strip everything, restore those four, write date+GPS. Verified
  lossless (decoded-pixel hash identical, JPEG and HEIC).
- **Batched rewrite, resumable without a journal.** Per-file `perl exiftool` is ~0.5 s/photo
  (~15 h for 103k). Instead: hardlink each photo under its *true* extension into a scratch dir,
  rewrite the whole chunk in one `exiftool -@ argfile -overwrite_original_in_place` (inode
  preserved, so the real source is edited in place), then move it out only once rewritten. A photo
  not yet moved is still in the input tree, so a re-scan reprocesses it — no journal. ~18× faster.
- **Classify by content, not extension.** Takeout mislabels JPEGs as `.HEIC`, drops extensions,
  mangles them (`.MP~2`), and stamps exotic `ftyp` major brands. `content_extension` sniffs magic
  bytes — images *and* video, including the ftyp compatible-brand list — and the pairing/scan fall
  back to it. Sidecars are never sniffed.
- **Dedupe by (name, size), hash-verified before delete.** Takeout copies a photo's bytes into
  every album it's in (~1 in 6). Drops are emitted *before* placements in the manifest so the
  hash-verify runs while both originals still exist.
- **Sidecar names are generated forward, not parsed back.** `<media>.supplemental-metadata.json`
  truncated to 51 chars; a `(N)` duplicate marker is re-appended *after* truncation.
- **Nothing is left behind.** Every input file ends up organised, dropped (motion/duplicate), or in
  `unsorted/` — undated, non-rewritable (BMP), or corrupt/un-rewritable (moved as-is, collision-safe).

## Assumptions

Synology NAS reachable over NFS + passwordless SSH. exiftool is auto-deployed on the NAS (Synology
Perl package + official exiftool). `uv` only (never `pip`); `ty` strict; 100% branch coverage;
network blocked in tests. Settings via pydantic-settings from `.env` (see `.env.example`).
