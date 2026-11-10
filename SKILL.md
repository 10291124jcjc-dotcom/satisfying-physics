---
name: satisfying-physics
description: 解压物理模拟视频：圆圈里一个齿轮带着两条弯臂转，小球碰到就多一个，越变越多，装满后炸开倾泻而下，碰撞声从稀到密。全部用代码模拟和渲染，不用拍、不用 AI 视频模型、不用任何图片和音频素材，一条 30 到 45 秒的竖屏视频电脑跑半分钟左右。用户说「做一条解压小球视频」「物理模拟视频」「像 NexusBox Lab 那样的号」「satisfying physics」「齿轮变球」「小球越变越多」，或者要改颜色、球数、时长、转速、配声时使用，哪怕没提 Skill 名字。Make oddly-satisfying physics simulation shorts (gear multiplies balls until the container bursts) entirely from code, with collision sounds.
---

# 解压物理模拟视频

圆圈容器 + 中间一个转动的齿轮和两条弯臂。小球碰到齿轮或弯臂就多出一个，越变越多；装满（默认 2500 个）就把圆圈撑破，小球倾泻到屏幕底部。声音是每一次碰撞实时合成的「哒哒」声，球越多越密。顶上一个球数计数器。

全部在本机用代码算：物理是自己写的（numpy + scipy），画面用 OpenCV 画，声音用 numpy 合成，最后 ffmpeg 合成 mp4。不联网、不用素材、不用视频模型。

## 0. 先说清楚

- 用中文和用户说话。
- 需要：Python 3.10+，`pip install numpy scipy opencv-python`，命令行能用 `ffmpeg`。第一次用先检查这三样，缺什么告诉用户装什么，用户同意后再装。
- 脚本：`scripts/physim.py`；参数：`presets/*.json`（只写想改的项，其余用脚本里的默认值）。
- 别人号里的视频只用来参考玩法，不拿来剪、不去水印。我们的视频从零算出来。

## 1. 问清楚要什么（用户说「你定」就全用默认）

| 项 | 默认 | 说明 |
| --- | --- | --- |
| 时长 | 装满后再放 6 秒，一般 35 到 40 秒 | `burst.at_count` 越大越久 |
| 球数上限 | 2500 | 装满就炸开；`ball.max` 要比它大一点 |
| 球大小 | 8（1080 宽下的像素半径） | 球改大，`burst.at_count` 要相应改小，不然装不满就到时间了 |
| 颜色 | 10 种亮色，每 3.2 秒换一种 | `waves.palette` 换色板；`multiply.color` 用 `cycle`（按时间换色，一段一段的色块）或 `inherit`（新球跟碰它的球同色） |
| 转速 | 1.5 弧度 / 秒 | `spinner.omega`，负数反着转 |
| 弯臂 | 半径 120、弧长 210 度 | `spinner.arm_radius`、`arm_span_deg` |
| 变球规则 | 碰到齿轮或弯臂都变 | `multiply.on`：`spinner`（齿轮 + 弯臂）或 `gear`（只有齿轮，变得慢很多） |
| 计数器 | 开 | `hud.counter` |
| 声音 | 开，-14 LUFS | `audio.on`、`audio.click_gain` |

## 2. 先出预览，再出正片

1. 复制一份 `presets/gear-multiply.json`，改成用户要的参数。
2. 预览（半分辨率，十几秒出结果）：
   `python scripts/physim.py 我的.json -o 预览.mp4 --preview`
   终端每 5 秒打印一次球数。目标：25 到 35 秒之间装满。装得太慢就把 `multiply.cooldown` 调小（0.5 → 0.4）或 `max_per_step` 调大；太快就反过来。
3. 抽帧检查：`ffmpeg -i 预览.mp4 -vf "fps=1/4,scale=200:-1,tile=6x2" -frames:v 1 抽帧.jpg`，看颜色是不是一段一段的、炸开那一下有没有、计数器有没有被挡。
4. 正片（1080x1920、30fps，约半分钟）：
   `python scripts/physim.py 我的.json -o 成片.mp4`
   同目录会多一张 `成片_cover.jpg`（炸开前最后一帧，球最满的时候），当封面用。
5. 查声音：`ffmpeg -i 成片.mp4 -vn -af ebur128 -f null -` 最后一行 I 应该在 -14 附近；声音应该是开头稀、越到后面越密。

## 3. 交付

- 成片 mp4、封面 jpg 的路径。
- 发布文案（IG / TikTok）：一句话标题 + 3 到 5 个标签，比如 `The gear turns, the balls multiply #satisfying #oddlysatisfying #physics #asmr`。
- 想做系列：每条只改一两样（换色板、球数翻倍、齿轮反转），标题写成「这次 5000 个」「反着转会怎样」。

## 4. 常见问题

- 装不满就到 40 秒了：球太大或 `cooldown` 太长。先看预览打印的球数。
- 画面一团乱、颜色全混在一起：`multiply.color` 改成 `cycle`，`cycle` 秒数调长一点（4 到 5 秒），色块会更整。
- 球穿过弯臂：`substeps` 从 6 调到 8。
- 中文路径存封面失败：脚本已经用 imencode 写文件，不会有这个问题；如果改脚本，别用 `cv2.imwrite` 写中文路径。
