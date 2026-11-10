# 解压物理模拟视频 · Satisfying Physics

[中文](#中文) · [English](#english)

## 中文

圆圈里一个齿轮带着两条弯臂转，小球碰到就多一个，越变越多，装满 2500 个后把圆圈撑破、倾泻而下。碰撞声跟着球数从稀到密。

这类视频在 IG、TikTok 上单条几百万到几千万播放。这个仓库是一个 **Claude Skill**：装进 Claude Code 后说「做一条解压小球视频」，它从零算出一条同款。

- **纯代码**：物理、画面、声音全在本机算，不用拍、不用 AI 视频模型、不用任何图片和音频素材
- **快**：一条 38 秒 1080x1920 的视频，普通电脑跑半分钟左右
- **能改**：颜色、球数、球大小、转速、弯臂形状、变球规则、计数器、声音，都在一个 json 里

### 装

把这个仓库的链接丢给 Claude Code（或 Codex），说「帮我装成 Skill」。

需要 Python 3.10+、`pip install numpy scipy opencv-python`，以及命令行能用的 `ffmpeg`。

### 用

在 Claude Code 里说「做一条解压小球视频，40 秒，颜色用粉蓝色系」。或者自己跑：

```
python scripts/physim.py presets/gear-multiply.json -o 预览.mp4 --preview   # 半分辨率，十几秒
python scripts/physim.py presets/gear-multiply.json -o 成片.mp4             # 1080x1920 正片
```

参数说明见 [`SKILL.md`](SKILL.md)。

### 许可

代码 MIT。玩法参考了 IG / TikTok 上的物理解压号（比如 NexusBox Lab），代码是从零写的，不含对方任何素材。

## English

A gear with two curved arms spins inside a circle. Every ball that touches it spawns another one, until 2,500 balls burst the container and pour out. Collision sounds are synthesized per impact and get denser as the balls multiply.

Everything is computed locally from code: physics (numpy + scipy), drawing (OpenCV), audio (numpy), muxed with ffmpeg. No footage, no video model, no assets. A 38-second 1080x1920 short renders in about half a minute.

Install: give this repo's URL to Claude Code and ask it to install it as a skill. Requires Python 3.10+, `numpy scipy opencv-python`, and `ffmpeg`.

```
python scripts/physim.py presets/gear-multiply.json -o out.mp4 --preview
python scripts/physim.py presets/gear-multiply.json -o out.mp4
```

License: MIT.
