# 解压物理模拟视频 · Satisfying Physics

[中文](#中文) · [English](#english)

https://github.com/user-attachments/assets/08556da7-03e0-4452-b9a4-7d23c0d080c3

用这个 Skill 从零算出来的一条：45 秒，物理、画面、碰撞声全是代码算的，没用任何图片、视频、音频素材。视频文件：[`assets/demo.mp4`](assets/demo.mp4)

---

## 中文

没有重力，小球在圆圈里飘。圆心一个齿轮挂着两条弯臂，一顺一逆地转；小球碰到齿轮就变成好几个新颜色的球，新颜色一团团从中间长出来，把旧颜色挤到边上。装满后圆圈撑破，球铺满全屏再四散飞走。碰撞声跟着球数从稀到密。

这类视频在 IG、TikTok 上单条几百万到几千万播放。这个仓库是一个 **Claude Skill**：装进 Claude Code 后说「做一条解压小球视频」，它从零算出一条同款。

- **纯代码**：物理、画面、声音全在本机算，不用拍、不用 AI 视频模型、不用任何图片和音频素材
- **快**：一条 45 秒 1080x1920 的视频，普通电脑跑一分钟左右
- **能改**：颜色、球数、球大小、转速、弯臂形状、变球规则、计数器、声音，都在一个 json 里

### 装

把这个仓库的链接丢给 Claude Code（或 Codex），说「帮我装成 Skill」。

需要 Python 3.10+、`pip install numpy scipy opencv-python`，以及命令行能用的 `ffmpeg`。

### 用

在 Claude Code 里说「做一条解压小球视频，40 秒，颜色用粉蓝色系」。或者自己跑：

```
python scripts/physim.py presets/gear-multiply.json -o 预览.mp4 --preview   # 半分辨率，二三十秒
python scripts/physim.py presets/gear-multiply.json -o 成片.mp4             # 1080x1920 正片
```

参数说明见 [`SKILL.md`](SKILL.md)。

### 许可

代码 MIT。玩法参考了 IG / TikTok 上的物理解压号（比如 NexusBox Lab），代码是从零写的，不含对方任何素材。

## English

Zero gravity, balls drifting inside a circle. A gear at the centre carries two curved arms turning in opposite directions; every ball that touches the gear turns into several balls of the current colour, so each new colour grows out from the middle and pushes the old ones aside. When the circle is full it bursts, the balls flood the screen and then scatter. Collision sounds are synthesized per impact and get denser as the balls multiply.

The demo above was generated from scratch by this skill. Everything is computed locally from code: physics (numpy + scipy), drawing (OpenCV), audio (numpy), muxed with ffmpeg. No footage, no video model, no assets. A 45-second 1080x1920 short renders in about a minute.

Install: give this repo's URL to Claude Code and ask it to install it as a skill. Requires Python 3.10+, `numpy scipy opencv-python`, and `ffmpeg`.

```
python scripts/physim.py presets/gear-multiply.json -o out.mp4 --preview
python scripts/physim.py presets/gear-multiply.json -o out.mp4
```

License: MIT.
