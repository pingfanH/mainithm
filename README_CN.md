# mainithm

> 欢迎加入 QQ 群 229380808 进行讨论。

maimai simai 谱面与 CHUNITHM UGC / SUS 谱面的双向转换器。

- **simai → UGC**（默认）：将 maimai 的 `maidata.txt` 转换为 CHUNITHM 的 Umiguri（UGC）谱面
- **simai → SUS**：转换为 Sliding Universal Score（SUS）谱面
- **UGC → simai**：将 CHUNITHM UGC 谱面转换回 maimai simai

## 依赖

- Python 3.9+
- 无需第三方库（仅使用标准库）

## 使用方法

### simai → UGC / SUS

```bash
# 单个谱面集 -> .ugc
python simai_to_sus.py maidata.txt

# 批量转换：递归扫描目录下所有 maidata.txt
python simai_to_sus.py songs_dir

# 指定输出目录
python simai_to_sus.py maidata.txt -o out_dir

# 输出 SUS 格式
python simai_to_sus.py maidata.txt --format sus
```

对每个 `&inote_N` 谱面会生成一个 `.ugc` / `.sus` 文件，并附带 `@TITLE`、`@ARTIST`、`@DESIGN`、`@DIFF`、`@LEVEL`、`@SONGID`、`@BGM`、`@JACKET` 等头信息。`@BGM` / `@JACKET` 指向 `maidata.txt` 旁边的音频（`track.*`、`bgm.mp3` 等）和封面（`bg.*`、`jacket.*` 等），转换时会复制到输出目录。

#### CLI 选项

| 选项 | 说明 |
| --- | --- |
| `input` | `maidata.txt` 文件或要扫描的目录 |
| `-o, --output` | 输出目录（默认与谱面同目录） |
| `--format` | 输出格式：`ugc`（默认）或 `sus` |
| `--songid` | 覆盖生成的 `#SONGID` |
| `--no-songid` | 完全不生成 / 输出 `#SONGID` |
| `--skip-random-id` | 生成 `#SONGID` 但不加随机后缀（仅 base id） |
| `--touch-multi-height` | 每个 touch 渲染为多个不同高度的 AIR-CRUSH（仅 UGC） |
| `--title-prefix STR` | 在乐曲名前添加字符串 |
| `--title-suffix STR` | 在乐曲名后添加字符串 |

示例：

```bash
python simai_to_sus.py maidata.txt --no-songid --title-prefix "[TAG] " --title-suffix " DX"
python simai_to_sus.py maidata.txt --touch-multi-height
python simai_to_sus.py maidata.txt --songid FXQARNHD
```

### UGC → simai

```bash
python ugc_to_simai.py input.ugc [-o output.txt]
```

将单个 `.ugc` 文件转换为 simai 文本（默认输出为 `input_simai.txt`）。

## 音符类型映射

### simai → UGC

| simai | UGC |
| --- | --- |
| tap | `t`（TAP） |
| ex tap（`x` / `b` 修饰符） | `x`（ExTAP） |
| hold | `h`（HOLD） |
| slide | 星星头 `t` + `H`（AIR-HOLD），随后为可保持的地面 `s`（SLIDE） |
| touch（C/B/E/A/D） | `C`（AIR-CRUSH，"purple air"）。单个 touch 为紫色；同拍多押分配不同颜色 |
| touch hold | 开头 `t` + `H`（AIR-HOLD），结尾 `C`（AIR-CRUSH） |

`--touch-multi-height` 开启后，每个 touch 以基础高度 H 及其相邻档位（H-1 / H / H+1，C2S 1..5，越界自动裁剪）生成多个不同高度的 AIR-CRUSH，每个都带各自的踩音。

### simai → SUS

| simai | SUS |
| --- | --- |
| tap | `1x`（tap） |
| hold | `2xy`（hold） |
| slide | `4xy`（slide 2） |
| touch（C/B/E/A/D） | `5x`（directional） |

### UGC → simai

| UGC | simai | 备注 |
| --- | --- | --- |
| `t` tap / `x` ExTAP / `h` hold | `1`-`8` tap / hold | lane → 按键 |
| `s` slide / `S` air-slide | `1-8` 直线 slide | 曲线形状近似 |
| `a` air | touch region（`A`-`E`） | 按方向 / 高度映射 |
| `H` air-hold | touch hold | |
| `C` crush | touch region | |
| `d` mine | `f`（fake tap） | 无 maimai 对应物，近似 |
| `f` flick | `b`（break tap） | 近似 |
| `c` click | tap | |

> 注意：CHUNITHM 中无 maimai 直接对应的音符（air / crush / mine / flick 等）使用"最接近"的 simai 表示，属尽力而为的近似转换。

## 难度映射

`&inote_N`（maimai）→ `@DIFF`（CHUNITHM）：

| inote | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| @DIFF | 0 | 1 | 2 | 2 | 3 | 5 | 6 |

## 时序 / 轨道模型

- simai 小节 `0.0` 对应谱面第一个节拍。
- UGC / SUS 使用 `ticks_per_beat = 480`、4/4 小节，即一个小节 1920 ticks。
- maimai 的 8 个按键位于 16 轨环形网格上，每 45° 一个按键：按键 `position`（0..7）映射到轨道 `2 * position`，中间的奇数轨留给滑条曲线控制点。
- 每轨音符宽 2 格（`NOTE_WIDTH = 2`）。

## 目录结构

```
maiconvert/
├── cli.py             # 命令行接口与歌曲文件发现
├── model.py           # 音符模型与共享常量/辅助函数
├── simai.py           # simai（maidata.txt）解析器
├── ugc.py             # CHUNITHM UGC writer
├── sus.py             # SUS writer
├── ugc_parser.py      # UGC 解析器（UGC → simai 方向）
└── simai_writer.py    # simai writer（UGC → simai 方向）
simai_to_sus.py        # simai → UGC / SUS 入口
ugc_to_simai.py        # UGC → simai 入口
```

## 已知限制

- break / EX / 星星视觉变体在 SUS 转换中会坍缩为普通 tap。
- 复杂滑条形状（`p/q/pp/qq/s/z/w`）在 SUS 中近似为折线；直线 `-`、弧线 `^<>`、`V`/`v` 为精确转换。
- UGC → simai 方向对 air / crush / mine / flick 等音符为近似映射。

## 格式参考

- simai：https://w.atwiki.jp/simai/
- UGC（Umiguri）：https://umgr.inonote.jp/en/
- SUS：https://gist.github.com/kb10uy/c171c175ba913dc40a73c6ce69da9859
