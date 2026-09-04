# mainithm

**English** | [简体中文](README_CN.md)

> 欢迎加入 QQ 群 229380808 进行讨论。

Bidirectional chart converter between maimai simai charts and CHUNITHM UGC / SUS charts.

- **simai → UGC** (default): convert maimai `maidata.txt` into CHUNITHM Umiguri (UGC) charts
- **simai → SUS**: convert into Sliding Universal Score (SUS) charts
- **UGC → simai**: convert CHUNITHM UGC charts back into maimai simai

## Requirements

- Python 3.9+
- No third-party packages (standard library only)

## Usage

### simai → UGC / SUS

```bash
# Single chart set -> .ugc
python simai_to_sus.py maidata.txt

# Batch convert: recursively scan a directory for maidata.txt files
python simai_to_sus.py songs_dir

# Specify the output directory
python simai_to_sus.py maidata.txt -o out_dir

# Emit SUS instead
python simai_to_sus.py maidata.txt --format sus
```

For each `&inote_N` chart one `.ugc` / `.sus` file is generated with `@TITLE`, `@ARTIST`, `@DESIGN`, `@DIFF`, `@LEVEL`, `@SONGID`, `@BGM` and `@JACKET` header metadata. `@BGM` / `@JACKET` point to the audio (`track.*`, `bgm.mp3`, ...) and cover image (`bg.*`, `jacket.*`, ...) found next to the maidata.txt; the assets are copied into the output directory during conversion.

#### CLI options

| Option | Description |
| --- | --- |
| `input` | A `maidata.txt` file or a directory to scan |
| `-o, --output` | Output directory (default: alongside the chart) |
| `--format` | Output format: `ugc` (default) or `sus` |
| `--songid` | Override the generated `#SONGID` |
| `--no-songid` | Do not generate / emit a `#SONGID` at all |
| `--skip-random-id` | Generate `#SONGID` without the random suffix (base id only) |
| `--touch-multi-height` | Render each touch as multiple AIR-CRUSHes at different heights (UGC only) |
| `--title-prefix STR` | Prepend a string to the song title |
| `--title-suffix STR` | Append a string to the song title |

Examples:

```bash
python simai_to_sus.py maidata.txt --no-songid --title-prefix "[TAG] " --title-suffix " DX"
python simai_to_sus.py maidata.txt --touch-multi-height
python simai_to_sus.py maidata.txt --songid FXQARNHD
```

### UGC → simai

```bash
python ugc_to_simai.py input.ugc [-o output.txt]
```

Converts a single `.ugc` file into simai text (default output: `input_simai.txt`).

## Note type mapping

### simai → UGC

| simai | UGC |
| --- | --- |
| tap | `t` (TAP) |
| ex tap (`x` / `b` modifier) | `x` (ExTAP) |
| hold | `h` (HOLD) |
| slide | star head `t` + `H` (AIR-HOLD), then a holdable ground `s` (SLIDE) |
| touch (C/B/E/A/D) | `C` (AIR-CRUSH, the "purple air"). A single touch is purple; simultaneous touches get distinct colors |
| touch hold | `t` + `H` (AIR-HOLD) at the start, `C` (AIR-CRUSH) at the end |

With `--touch-multi-height`, each touch is rendered as multiple AIR-CRUSHes at the base height and its neighbours (H-1 / H / H+1, C2S 1..5, clamped automatically), each with its own 踩音.

### simai → SUS

| simai | SUS |
| --- | --- |
| tap | `1x` (tap) |
| hold | `2xy` (hold) |
| slide | `4xy` (slide 2) |
| touch (C/B/E/A/D) | `5x` (directional) |

### UGC → simai

| UGC | simai | Notes |
| --- | --- | --- |
| `t` tap / `x` ExTAP / `h` hold | `1`-`8` tap / hold | lane → button |
| `s` slide / `S` air-slide | straight `1-8` slide | curves approximated |
| `a` air | touch region (`A`-`E`) | mapped by direction / height |
| `H` air-hold | touch hold | |
| `C` crush | touch region | |
| `d` mine | `f` (fake tap) | no maimai equivalent, approximation |
| `f` flick | `b` (break tap) | approximation |
| `c` click | tap | |

> Note: CHUNITHM notes without a direct maimai equivalent (air / crush / mine / flick, etc.) are mapped to the closest simai representation — a best-effort approximation.

## Difficulty mapping

`&inote_N` (maimai) → `@DIFF` (CHUNITHM):

| inote | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| @DIFF | 0 | 1 | 2 | 2 | 3 | 5 | 6 |

## Timing / lane model

- simai measure `0.0` is the first beat of the chart.
- UGC / SUS use `ticks_per_beat = 480` and 4/4 bars, i.e. one bar == 1920 ticks.
- maimai's 8 buttons sit on a 16-lane circular grid, one button every 45°: button `position` (0..7) maps to lane `2 * position`; the odd lanes in between are free for slide curve control points.
- Each note is two lanes wide (`NOTE_WIDTH = 2`).

## Directory layout

```
maiconvert/
├── cli.py             # Command-line interface and song file discovery
├── model.py           # Note models and shared constants/helpers
├── simai.py           # simai (maidata.txt) parser
├── ugc.py             # CHUNITHM UGC writer
├── sus.py             # SUS writer
├── ugc_parser.py      # UGC parser (UGC → simai direction)
└── simai_writer.py    # simai writer (UGC → simai direction)
simai_to_sus.py        # simai → UGC / SUS entry point
ugc_to_simai.py        # UGC → simai entry point
```

## Known limitations

- break / EX / star visual variants collapse into ordinary taps in the SUS conversion.
- Complex slide shapes (`p/q/pp/qq/s/z/w`) are approximated as polylines in SUS; straight `-`, arc `^<>`, and `V`/`v` slides are exact.
- The UGC → simai direction approximates air / crush / mine / flick notes.

## Format references

- simai: https://w.atwiki.jp/simai/
- UGC (Umiguri): https://umgr.inonote.jp/en/
- SUS: https://gist.github.com/kb10uy/c171c175ba913dc40a73c6ce69da9859
