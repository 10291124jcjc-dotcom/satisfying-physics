---
name: satisfying-physics
description: 解压物理模拟视频：没有重力，小球在圆圈里飘；圆心一个齿轮挂着两条弯臂一顺一逆地转，小球碰到齿轮就变成好几个新颜色的球，新颜色一团团从中间长出来，装满后圆圈撑破、球铺满全屏再四散飞走，碰撞声从稀到密。全部用代码模拟和渲染，不用拍、不用 AI 视频模型、不用任何图片和音频素材，一条 45 秒竖屏视频电脑跑一分钟左右。用户说「做一条解压小球视频」「物理模拟视频」「像 NexusBox Lab 那样的号」「satisfying physics」「齿轮变球」「小球越变越多」，或者要改颜色、球数、时长、转速、配声时使用，哪怕没提 Skill 名字。Make oddly-satisfying physics simulation shorts (a gear multiplies balls until the container bursts) entirely from code, with collision sounds.
---

# 解压物理模拟视频

一条 45 秒的竖屏视频，节奏照着 IG 上几千万播放的物理解压号来：

1. 开头只有一个球，飘向中间的齿轮。
2. 球碰到齿轮就变成好几个新球，新球统一用「当前颜色」，每 3 秒换一种。前 12 秒只有 20 来个球。
3. 后面越变越快，28 秒左右装满（约 700 个球）。装满后新颜色继续从中间一团团往外推，旧颜色被挤到边上。
4. 41 秒圆圈撑破，球先铺满全屏，再四散飞出屏幕，最后齿轮里冒出一大团新颜色。
5. 两条弯臂挂在齿轮上，一条顺时针、一条逆时针，时而拼成 S、时而合成一个圈。
6. 声音是每一次碰撞实时合成的「哒哒」声，开头稀、越到后面越密，撑破时一声闷响。

全部在本机用代码算：物理自己写（numpy + scipy），画面用 OpenCV 贴图（球带高光和暗边），声音用 numpy 合成，ffmpeg 合成 mp4。不联网、不用素材、不用视频模型。

## 0. 先说清楚

- 用中文和用户说话。
- 需要：Python 3.10+，`pip install numpy scipy opencv-python`，命令行能用 `ffmpeg`。第一次用先检查这三样，缺什么告诉用户装什么，用户同意后再装。
- 脚本：`scripts/physim.py`；参数：`presets/*.json`（只写想改的项，其余用脚本开头 `DEFAULT` 里的值）。
- 别人号里的视频只用来参考玩法，不拿来剪、不去水印。我们的视频从零算出来。

## 1. 问清楚要什么（用户说「你定」就全用默认）

| 项 | 默认 | 改哪里 |
| --- | --- | --- |
| 总时长 | 约 45 秒（41 秒撑破 + 4.5 秒结尾） | `burst.at_time`、`burst.tail` |
| 涨球节奏 | 12 秒 20 个，28 秒装满 | `multiply.curve`：`t1`、`n1`、`t_full` |
| 装满几个 | 700 | `burst.full_at`；球改大改小要跟着改，约等于 0.9 ×（圆半径 ÷ 球半径）² |
| 球大小 | 15（1080 宽下的像素半径） | `ball.r` |
| 颜色 | 10 种亮色，每 3 秒换一种 | `palette`、`multiply.color_every`；`multiply.color` 改成 `next` 就是「新球用碰它那个球的下一种颜色」 |
| 弯臂转速 | 一条 1.25、一条 -0.85（弧度 / 秒） | `spinner.omega` |
| 弯臂形状 | 半径 135、弧长 185 度 | `spinner.arm_radius`、`arm_span_deg` |
| 撑破后 | 铺满全屏 2400 个球，停 2 秒再飞走 | `burst.fill`、`burst.hold` |
| 重力 | 0（球在圈里飘） | `gravity`，想要球往下掉就给 300 左右 |
| 计数器 | 关 | `hud.counter` |
| 声音 | 开，-14 LUFS | `audio.on`、`audio.click_gain`、`audio.pop_gain` |

## 2. 先出预览，再出正片

1. 复制一份 `presets/gear-multiply.json`，改成用户要的参数。
2. 预览（半分辨率，二三十秒出结果）：
   `python scripts/physim.py 我的.json -o 预览.mp4 --preview`
   终端每 5 秒打印一次球数，看曲线对不对：5 秒个位数、20 秒一百多、28 到 30 秒到 `full_at`。
3. 抽帧检查：`ffmpeg -i 预览.mp4 -vf "fps=1/4,scale=200:-1,tile=6x2" -frames:v 1 抽帧.jpg`。看三样：装满后是不是一大块一大块的颜色、41 秒有没有撑破铺满全屏、结尾有没有一团新颜色。
4. 正片（1080x1920、30fps，约一分钟）：
   `python scripts/physim.py 我的.json -o 成片.mp4`
   同目录会多一张 `成片_cover.jpg`（撑破前球最满的那一帧），当封面用。
5. 查声音：`ffmpeg -i 成片.mp4 -vn -af ebur128 -f null -` 最后一行 I 应该在 -14 附近；开头稀、后面密。

## 3. 交付

- 成片 mp4、封面 jpg 的路径。
- 发布文案（IG / TikTok）：一句话标题 + 3 到 5 个标签，比如 `The gear turns, the balls multiply #satisfying #oddlysatisfying #physics #asmr`。
- 想做系列：每条只改一两样（换色板、球改小装满 2000 个、弯臂转快一倍），标题写成「这次 2000 个」「转快一倍会怎样」。

## 4. 常见问题

- 涨得太慢或太快：改 `multiply.curve`。它决定每次碰齿轮变几个（落后于曲线就多变，最多 `max_into` 个）。
- 装满后颜色混成彩点：`ball.restitution` 调低一点（0.85 → 0.75），球弹得少，色块更整。
- 球穿过弯臂：`substeps` 从 5 调到 8。
- 渲染慢：主要花在贴球上。先用 `--preview` 调好，再出一次正片。
- 中文路径存封面失败：脚本已经用 imencode 写文件；如果改脚本，别用 `cv2.imwrite` 写中文路径。
