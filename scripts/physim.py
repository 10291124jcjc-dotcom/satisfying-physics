#!/usr/bin/env python3
"""
physim.py  解压物理模拟视频（纯代码，不用任何图片、视频、音频素材）

玩法（齿轮变球）：没有重力，小球在圆圈里飘、弹。圆心一个齿轮，两条半圆弯臂挂在齿轮上，
一条顺时针、一条逆时针转，时而拼成 S、时而合成一个圈。小球碰到齿轮就变成好几个
「当前颜色」的新球（颜色每几秒换一种），所以最新的颜色总是从中间一团团长出来，把旧颜色挤到边上。
球数按「前面慢、后面爆发」的曲线涨，装满后新颜色继续往外推；到点圆圈撑破，球先铺满全屏，
再四散飞出屏幕，最后齿轮里冒出一团新颜色。碰撞声由每一次碰撞实时合成。

用法：
  python physim.py preset.json -o out.mp4             # 正式渲染（默认 1080x1920、30fps）
  python physim.py preset.json -o test.mp4 --preview  # 半分辨率，快速看效果
依赖：numpy、scipy、opencv-python、ffmpeg（命令行）
"""
import argparse, json, math, os, subprocess, time, wave
import numpy as np
import cv2
from scipy.spatial import cKDTree

DEFAULT = {
    "width": 1080, "height": 1920, "fps": 30, "duration": 46, "seed": 3,
    "background": "#000000",
    "container": {"cx": 540, "cy": 960, "r": 440, "color": "#F2F2F2", "width": 3},
    "ball": {"r": 15.0, "restitution": 0.85, "wall_restitution": 1.0, "max_speed": 900,
             "start": 1, "start_speed": 260},
    "gravity": 0.0,
    "spinner": {"omega": [1.25, -0.85], "arm_radius": 135, "arm_span_deg": 185, "arm_width": 17,
                "arm_color": "#8E9198", "rivets": True,
                "gear_r": 34, "gear_teeth": 12, "gear_color": "#C9CCD2"},
    "multiply": {"on": "gear", "into": 2, "cooldown": 0.5, "speed": 150, "remove_parent": True,
                 "color": "time", "color_every": 3.0,
                 "curve": {"t1": 12.0, "n1": 20, "t_full": 28.0}, "max_into": 14,
                 "glow": True},
    "palette": ["#2AA8FF", "#FFE21A", "#9B2DF2", "#35F06A", "#FF2E3A", "#2F63FF",
                "#B4EE1E", "#FF2BD6", "#2EF2C4", "#FF7A1A"],
    "burst": {"full_at": 700, "at_count": 100000, "at_time": 41.0, "tail": 4.5, "push": 320,
              "fill": 2400, "hold": 2.0, "final_blob": 200},
    "hud": {"counter": False, "y": 330, "scale": 3.2, "color": "#FFFFFF"},
    "audio": {"on": True, "click_gain": 1.0, "pop_gain": 0.6, "lufs": -14},
    "substeps": 5,
}


def merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def bgr(h):
    h = h.lstrip('#')
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


def ball_sprite(color, r, ss=4):
    """有光泽的小球：漫反射 + 高光 + 暗边，返回 (BGR, alpha) 两个 float 数组"""
    R = r * ss
    n = int(math.ceil(2 * r + 2)) * ss
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    c = n / 2
    dx, dy = (xx - c) / R, (yy - c) / R
    d2 = dx * dx + dy * dy
    inside = d2 <= 1
    nz = np.sqrt(np.clip(1 - d2, 0, 1))
    L = np.array([-0.45, -0.55, 0.70]); L /= np.linalg.norm(L)
    diff = np.clip(dx * L[0] + dy * L[1] + nz * L[2], 0, 1)
    hvec = L + np.array([0, 0, 1.0]); hvec /= np.linalg.norm(hvec)
    spec = np.clip(dx * hvec[0] + dy * hvec[1] + nz * hvec[2], 0, 1) ** 36
    base = np.array(color, np.float32)[None, None, :]
    shade = 0.30 + 0.78 * diff[..., None]
    col = base * shade + 255 * (0.9 * spec[..., None])
    rim = np.clip((np.sqrt(d2) - 0.86) / 0.14, 0, 1)[..., None]
    col = col * (1 - 0.55 * rim)
    col = np.clip(col, 0, 255)
    a = inside.astype(np.float32)
    m = n // ss
    col = cv2.resize(col, (m, m), interpolation=cv2.INTER_AREA)
    a = cv2.resize(a, (m, m), interpolation=cv2.INTER_AREA)
    return col.astype(np.float32), a[..., None].astype(np.float32)


class Sim:
    def __init__(self, cfg, scale=1.0):
        self.c = cfg
        self.s = s = scale
        self.rng = np.random.default_rng(cfg["seed"])
        self.W, self.H = int(cfg["width"] * s), int(cfg["height"] * s)
        C = cfg["container"]
        self.cc = np.array([C["cx"] * s, C["cy"] * s], float)
        self.R = C["r"] * s
        B = cfg["ball"]
        self.r = B["r"] * s
        sp = cfg["spinner"]
        self.omega = sp["omega"] if isinstance(sp["omega"], list) else [sp["omega"], -sp["omega"]]
        self.phi = [0.0, math.pi * 0.62]
        self.arm_a = sp["arm_radius"] * s
        self.arm_span = math.radians(sp["arm_span_deg"])
        self.arm_w = sp["arm_width"] * s
        self.gear_r = sp["gear_r"] * s
        self.gear_ang = 0.0
        self.palette = [bgr(h) for h in cfg["palette"]]
        self.p = np.zeros((0, 2)); self.v = np.zeros((0, 2))
        self.gen = np.zeros(0, np.int32); self.born = np.zeros(0)
        self.t = 0.0
        self.burst_t = None
        self.events = []      # (t, kind, mags)  kind 0=碰撞 1=变球 2=破开
        self.glows = []       # (t0, 颜色序号)
        self.shards = None
        self.sprites = [ball_sprite(c, self.r) for c in self.palette]
        # 开场：一个球朝齿轮那边飞
        n = B["start"]
        ang = self.rng.uniform(0, 2 * math.pi, n)
        pos = self.cc + np.stack([np.cos(ang), np.sin(ang)], 1) * self.R * 0.62
        vel = (self.cc - pos) / np.linalg.norm(self.cc - pos, axis=1)[:, None]
        vel = vel * B["start_speed"] * s
        self.add(pos, vel, np.zeros(n, np.int32), born=-10.0)

    def add(self, pos, vel, gen, born=None):
        self.p = np.vstack([self.p, pos]); self.v = np.vstack([self.v, vel])
        self.gen = np.concatenate([self.gen, gen])
        self.born = np.concatenate([self.born, np.full(len(pos), self.t if born is None else born)])

    def keep(self, mask):
        self.p, self.v, self.gen, self.born = self.p[mask], self.v[mask], self.gen[mask], self.born[mask]

    def arms(self, K=20):
        """两条半圆弯臂，一头挂在齿轮上；sign 让两条弯的方向相反，转到同一角度时合成一个圈"""
        out = []
        for k, sign in ((0, 1), (1, -1)):
            ph = self.phi[k]
            u = np.array([math.cos(ph), math.sin(ph)])
            ac = self.cc + u * self.arm_a
            phis = ph + math.pi + sign * np.linspace(0, self.arm_span, K + 1)
            out.append(ac + self.arm_a * np.stack([np.cos(phis), np.sin(phis)], 1))
        return out

    def step(self, dt):
        B, M = self.c["ball"], self.c["multiply"]
        for k in range(2):
            self.phi[k] += self.omega[k] * dt
        self.gear_ang += (self.omega[0] - self.omega[1]) * 0.5 * dt
        now = self.t
        if len(self.p) == 0:
            self.t += dt; return
        p, v, r = self.p, self.v, self.r
        if self.c["gravity"]:
            v[:, 1] += self.c["gravity"] * self.s * dt
        v *= 0.99985
        sp = np.linalg.norm(v, axis=1); ms = B["max_speed"] * self.s
        fast = sp > ms
        if fast.any():
            v[fast] *= (ms / sp[fast])[:, None]
        p += v * dt
        e = B["restitution"]
        # 球和球
        tree = cKDTree(p)
        pairs = tree.query_pairs(2 * r, output_type='ndarray')
        if len(pairs):
            i, j = pairs[:, 0], pairs[:, 1]
            for it in range(2):
                d = p[j] - p[i]
                dist = np.linalg.norm(d, axis=1)
                bad = dist < 1e-6
                if bad.any():
                    d[bad] = self.rng.normal(0, 1, (bad.sum(), 2)); dist[bad] = np.linalg.norm(d[bad], axis=1)
                n = d / dist[:, None]
                ov = np.clip(2 * r - dist, 0, None)
                corr = n * (ov * 0.5)[:, None]
                np.add.at(p, i, -corr); np.add.at(p, j, corr)
                if it == 0:
                    vn = np.einsum('ij,ij->i', v[j] - v[i], n)
                    m = vn < 0
                    imp = (-(1 + e) * vn * 0.5 * m)[:, None] * n
                    np.add.at(v, i, -imp); np.add.at(v, j, imp)
                    hard = -vn[m] / self.s
                    hard = hard[hard > 30]
                    if len(hard):
                        self.events.append((now, 0, hard))
        # 弯臂（胶囊段）
        segs = self.arms()
        A = np.concatenate([q[:-1] for q in segs]); Bq = np.concatenate([q[1:] for q in segs])
        owner = np.concatenate([np.full(len(q) - 1, k) for k, q in enumerate(segs)])
        near = np.where(np.linalg.norm(p - self.cc, axis=1) < 2 * self.arm_a + self.arm_w + r)[0]
        if len(near):
            q = p[near]
            AB = Bq - A
            tt = np.clip(np.einsum('nsk,sk->ns', q[:, None, :] - A[None], AB) / np.einsum('sk,sk->s', AB, AB)[None], 0, 1)
            cl = A[None] + tt[..., None] * AB[None]
            diff = q[:, None, :] - cl
            dist = np.linalg.norm(diff, axis=2)
            k = dist.argmin(1); dmin = dist[np.arange(len(q)), k]
            lim = r + self.arm_w / 2
            hit = dmin < lim
            if hit.any():
                idx = near[hit]
                dd = diff[np.arange(len(q)), k][hit]; dm = np.maximum(dmin[hit], 1e-6)
                n = dd / dm[:, None]
                p[idx] += n * (lim - dm)[:, None]
                rel = p[idx] - self.cc
                om = np.array(self.omega)[owner[k[hit]]]
                vo = om[:, None] * np.stack([-rel[:, 1], rel[:, 0]], 1)
                vr = v[idx] - vo
                vn = np.einsum('ij,ij->i', vr, n)
                m = vn < 0
                v[idx] -= ((1 + e) * vn * m)[:, None] * n
                if m.any():
                    self.events.append((now, 0, (-vn[m]) / self.s))
        # 齿轮
        rel = p - self.cc
        dist = np.linalg.norm(rel, axis=1)
        glim = self.gear_r + r
        g = np.where(dist < glim)[0]
        if len(g):
            n = rel[g] / np.maximum(dist[g], 1e-6)[:, None]
            p[g] = self.cc + n * glim
            vn = np.einsum('ij,ij->i', v[g], n)
            m = vn < 0
            v[g] -= (2 * vn * m)[:, None] * n
        # 圆圈；破开后先用屏幕四边挡一下（球铺满全屏），之后撤掉，球飞出屏幕
        Bc = self.c["burst"]
        holding = self.burst_t is not None and now < self.burst_t + Bc["hold"]
        if holding:
            for ax, lo, hi in ((0, r, self.W - r), (1, r, self.H - r)):
                a_ = p[:, ax] < lo; b_ = p[:, ax] > hi
                p[a_, ax] = lo; p[b_, ax] = hi
                v[a_, ax] = np.abs(v[a_, ax]); v[b_, ax] = -np.abs(v[b_, ax])
            if len(p) < Bc["fill"]:   # 撑破后继续复制，一秒多铺满整屏
                m_ = min(Bc["fill"] - len(p), max(1, int((Bc["fill"] - Bc["full_at"]) / (Bc["hold"] * 0.8 * self.c["fps"] * self.c["substeps"]))))
                src = self.rng.integers(0, len(p), m_)
                off = self.rng.normal(0, 0.6 * r, (m_, 2))
                self.add(p[src] + off, v[src] + self.rng.normal(0, 40 * self.s, (m_, 2)), self.gen[src].copy())
                p, v = self.p, self.v
        elif self.burst_t is not None and not getattr(self, "released", False):
            self.released = True
            rel = p - self.cc
            d = np.maximum(np.linalg.norm(rel, axis=1), 1e-6)
            v += rel / d[:, None] * Bc["push"] * self.s * 1.4
            self.blob_left = Bc["final_blob"]
            self.blob_gen = 2 + int(now / self.c["multiply"]["color_every"])
        if self.burst_t is not None and getattr(self, "released", False) and getattr(self, "blob_left", 0) > 0:
            m_ = min(2, self.blob_left)   # 最后从齿轮里冒出一大团同一种颜色的新球
            ang = self.rng.uniform(0, 2 * math.pi, m_)
            n1 = np.stack([np.cos(ang), np.sin(ang)], 1)
            self.add(self.cc + n1 * (self.gear_r + r * 1.2), n1 * 45 * self.s, np.full(m_, self.blob_gen, np.int32))
            self.blob_left -= m_
            p, v = self.p, self.v
        if self.burst_t is None:
            rel = p - self.cc
            dist = np.linalg.norm(rel, axis=1)
            o = np.where(dist > self.R - r)[0]
            if len(o):
                n = rel[o] / dist[o][:, None]
                p[o] = self.cc + n * (self.R - r)
                vn = np.einsum('ij,ij->i', v[o], n)
                m = vn > 0
                v[o] -= ((1 + B["wall_restitution"]) * vn * m)[:, None] * n
                if m.any():
                    self.events.append((now, 0, vn[m] / self.s))
        # 碰到齿轮就变成几个下一种颜色的球
        if len(g):
            ok = g[(now - self.born[g]) > M["cooldown"]]
            if len(ok):
                ok = ok[:6]
                # 按「慢慢开始、后面爆发」的指数曲线控制变出几个：落后于曲线就一次多变几个
                cv_ = M.get("curve")
                if cv_ and self.burst_t is None:
                    full = self.c["burst"]["full_at"]
                    b_ = math.log(full / cv_["n1"]) / (cv_["t_full"] - cv_["t1"])
                    target = cv_["n1"] * math.exp(b_ * (now - cv_["t1"]))
                    per = int(np.clip((target - len(p)) / len(ok), M["into"], M["max_into"]))
                else:
                    per = M["into"]
                par = np.repeat(ok, per)
                base = np.arctan2(p[par, 1] - self.cc[1], p[par, 0] - self.cc[0])
                ang = base + self.rng.uniform(-1.1, 1.1, len(par))
                n = np.stack([np.cos(ang), np.sin(ang)], 1)
                pos = self.cc + n * (glim + self.rng.uniform(0.2, 1.4, len(par))[:, None] * r)
                vel = n * M["speed"] * self.s * self.rng.uniform(0.7, 1.2, len(par))[:, None]
                if M.get("color") == "time":   # 新球统一用「当前颜色」，每 color_every 秒换一种
                    gen = np.full(len(par), 1 + int(now / M["color_every"]), np.int32)
                else:                          # 新球用碰它那个球的下一种颜色
                    gen = self.gen[par] + 1
                for gg in np.unique(gen):
                    self.glows.append((now, int(gg % len(self.palette))))
                self.events.append((now, 1, np.full(len(ok), 1.0)))
                if M["remove_parent"]:
                    mask = np.ones(len(p), bool); mask[ok] = False
                    self.keep(mask)
                else:
                    self.born[ok] = now
                # 装满以后：每多一个新球，就从最老的颜色里挑一个最靠边的拿掉，颜色一轮轮往外推
                full = self.c["burst"]["full_at"]
                excess = len(self.p) + len(pos) - full
                if self.burst_t is None and excess > 0:
                    d = np.linalg.norm(self.p - self.cc, axis=1)
                    score = self.born * 1e3 - d
                    rm = np.argsort(score)[:excess]
                    mask = np.ones(len(self.p), bool); mask[rm] = False
                    self.keep(mask)
                self.add(pos, vel, gen)
        if self.burst_t is not None and getattr(self, "released", False):
            far = np.linalg.norm(self.p - self.cc, axis=1) > max(self.W, self.H)
            if far.any():
                self.keep(~far)
        self.t += dt

    def maybe_events(self):
        Bc = self.c["burst"]
        if self.burst_t is None and (len(self.p) >= Bc["at_count"] or self.t >= Bc["at_time"]):
            self.burst_t = self.t
            self.events.append((self.t, 2, np.array([1.0])))
            ang = np.linspace(0, 2 * math.pi, 41)
            self.shards = [(ang[i], ang[i + 1], self.rng.uniform(300, 700) * self.s) for i in range(40)]
            rel = self.p - self.cc
            d = np.maximum(np.linalg.norm(rel, axis=1), 1e-6)
            self.v += rel / d[:, None] * Bc["push"] * self.s * 0.5

    # ---------- 画 ----------
    def draw(self, img):
        c, s = self.c, self.s
        sh = 4; F = 1 << sh
        H, W = img.shape[:2]
        # 球（按颜色分批贴图）
        imgf = img.astype(np.float32)
        for k in range(len(self.palette)):
            idx = np.where(self.gen % len(self.palette) == k)[0]
            if not len(idx):
                continue
            spr, al = self.sprites[k]
            m = spr.shape[0]; half = m / 2
            for (x, y) in self.p[idx]:
                x0 = int(round(x - half)); y0 = int(round(y - half))
                x1, y1 = x0 + m, y0 + m
                if x1 <= 0 or y1 <= 0 or x0 >= W or y0 >= H:
                    continue
                sx0, sy0 = max(0, -x0), max(0, -y0)
                sx1, sy1 = m - max(0, x1 - W), m - max(0, y1 - H)
                roi = imgf[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
                a = al[sy0:sy1, sx0:sx1]
                roi[:] = roi * (1 - a) + spr[sy0:sy1, sx0:sx1] * a
        img[:] = np.clip(imgf, 0, 255).astype(np.uint8)
        cx, cy = self.cc
        # 变球时齿轮周围一圈光
        if c["multiply"]["glow"] and self.glows:
            self.glows = [g for g in self.glows if self.t - g[0] < 0.45]
            if self.glows:
                ov = img.copy()
                for t0, ci in self.glows[-4:]:
                    k = (self.t - t0) / 0.45
                    rr = self.gear_r + (20 + 70 * k) * s
                    cv2.circle(ov, (int(cx * F), int(cy * F)), int(rr * F), self.palette[ci],
                               max(2, int((12 * (1 - k) + 3) * s)), cv2.LINE_AA, sh)
                cv2.addWeighted(ov, 0.45, img, 0.55, 0, img)
        # 圆圈 / 碎片
        C = c["container"]; ccol = bgr(C["color"]); cw = max(1, int(round(C["width"] * s)))
        if self.burst_t is None:
            cv2.circle(img, (int(cx * F), int(cy * F)), int(self.R * F), ccol, cw, cv2.LINE_AA, sh)
        else:
            dt = self.t - self.burst_t
            for a0, a1, spd in self.shards:
                mid = (a0 + a1) / 2
                off = np.array([math.cos(mid), math.sin(mid)]) * spd * dt
                aa = np.linspace(a0, a1, 5)
                pts = np.stack([cx + self.R * np.cos(aa), cy + self.R * np.sin(aa)], 1) + off
                cv2.polylines(img, [(pts * F).astype(np.int32)], False, ccol, cw, cv2.LINE_AA, sh)
        # 弯臂：深色描边 + 金属灰 + 一道亮边 + 铆钉
        sp = c["spinner"]; acol = bgr(sp["arm_color"]); aw = max(3, int(round(self.arm_w)))
        dark = tuple(int(ch * 0.45) for ch in acol); hi = tuple(min(255, int(ch * 1.3)) for ch in acol)
        for pts in self.arms(40):
            ip = (pts * F).astype(np.int32)
            cv2.polylines(img, [ip], False, dark, aw + max(2, int(4 * s)), cv2.LINE_AA, sh)
            cv2.polylines(img, [ip], False, acol, aw, cv2.LINE_AA, sh)
            cv2.polylines(img, [(ip + np.array([0, -int(aw * 0.18 * F)])).astype(np.int32)], False, hi,
                          max(1, aw // 5), cv2.LINE_AA, sh)
            for end in (ip[0], ip[-1]):
                cv2.circle(img, (int(end[0]), int(end[1])), int(aw / 2 * F), acol, -1, cv2.LINE_AA, sh)
            if sp["rivets"]:
                for q in ip[2:-1:4]:
                    cv2.circle(img, (int(q[0]), int(q[1])), int(max(1.5, 2.2 * s) * F), dark, -1, cv2.LINE_AA, sh)
        # 齿轮
        gcol = bgr(sp["gear_color"]); T = sp["gear_teeth"]; gr = self.gear_r
        pts = []
        for i in range(T * 2):
            a0 = self.gear_ang + i * math.pi / T
            rr = gr * (1.0 if i % 2 == 0 else 0.80)
            for da in (-0.42, 0.42):
                a = a0 + da * math.pi / T
                pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        poly = (np.array(pts) * F).astype(np.int32)
        cv2.fillPoly(img, [poly], gcol, cv2.LINE_AA, sh)
        cv2.polylines(img, [poly], True, tuple(int(ch * 0.55) for ch in gcol), max(1, int(2 * s)), cv2.LINE_AA, sh)
        cv2.circle(img, (int(cx * F), int(cy * F)), int(gr * 0.55 * F), tuple(int(ch * 0.8) for ch in gcol), max(1, int(3 * s)), cv2.LINE_AA, sh)
        cv2.circle(img, (int(cx * F), int(cy * F)), int(gr * 0.28 * F), (60, 60, 64), -1, cv2.LINE_AA, sh)
        cv2.circle(img, (int(cx * F), int(cy * F)), int(gr * 0.12 * F), (150, 150, 155), -1, cv2.LINE_AA, sh)
        Hd = c["hud"]
        if Hd["counter"]:
            txt = f"{len(self.p):,}"
            sc = Hd["scale"] * s; th = max(2, int(round(5 * s)))
            (tw, tht), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_DUPLEX, sc, th)
            cv2.putText(img, txt, (int(self.W / 2 - tw / 2), int(Hd["y"] * s)), cv2.FONT_HERSHEY_DUPLEX, sc, bgr(Hd["color"]), th, cv2.LINE_AA)


# ---------- 声音 ----------
SR = 44100

def make_bank(rng):
    clicks, pops = [], []
    for k in range(24):
        f = rng.uniform(1300, 3800); L = int(SR * rng.uniform(0.014, 0.032))
        t = np.arange(L) / SR
        env = np.exp(-t / rng.uniform(0.003, 0.009))
        x = np.sin(2 * np.pi * f * t) * env + rng.normal(0, 0.22, L) * np.exp(-t / 0.0015)
        clicks.append(x / np.abs(x).max())
    for k in range(8):
        L = int(SR * 0.09); t = np.arange(L) / SR
        f = rng.uniform(420, 760) * (1 + 0.6 * t / t[-1])
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.025)
        pops.append(x / np.abs(x).max())
    L = int(SR * 1.4); t = np.arange(L) / SR
    boom = (rng.normal(0, 1, L) * np.exp(-t / 0.3) * 0.6 + np.sin(2 * np.pi * 52 * t) * np.exp(-t / 0.4))
    return clicks, pops, boom / np.abs(boom).max()


def render_audio(events, duration, cfg, seed, path, track=None):
    """track: [(t, 球数)]，让声音跟着球数从稀到密"""
    rng = np.random.default_rng(seed + 1)
    if track:
        tt = np.array([a for a, b in track]); nn = np.array([b for a, b in track], float)
        env = lambda t: 0.2 + 0.8 * (np.interp(t, tt, nn) / max(1.0, nn.max())) ** 0.7
    else:
        env = lambda t: 1.0
    clicks, pops, boom = make_bank(rng)
    N = int(SR * duration) + SR
    out = np.zeros(N)
    A = cfg["audio"]
    bucket = 1 / 240
    bins = {}
    for t, kind, mags in events:
        if kind == 0:
            if not len(mags):
                continue
            b = int(t / bucket)
            e, n = bins.get(b, (0.0, 0))
            bins[b] = (e + float(np.sum(np.minimum(mags, 1500) ** 2)), n + len(mags))
        elif kind == 1:
            x = pops[rng.integers(len(pops))]; i = int(t * SR) + int(rng.integers(0, 200))
            out[i:i + len(x)] += x[:max(0, N - i)] * 0.16 * A["pop_gain"]
        else:
            i = int(t * SR); out[i:i + len(boom)] += boom[:max(0, N - i)] * 0.9
    for b, (e, n) in bins.items():
        if n == 0:
            continue
        tb = b * bucket
        k = max(1, int(round(min(n, 5) * env(tb))))
        amp = math.sqrt(e / n) / 1500
        for _ in range(k):
            x = clicks[rng.integers(len(clicks))]
            i = int(tb * SR) + int(rng.integers(0, int(bucket * SR)))
            g = (0.06 + 0.5 * amp) * rng.uniform(0.6, 1.0) * A["click_gain"] * env(tb)
            out[i:i + len(x)] += x[:max(0, N - i)] * g
    out = out[:int(SR * duration)]
    out = np.tanh(out * 1.2)
    out /= max(1e-6, np.abs(out).max()) / 0.9
    pcm = (np.stack([out, out], 1) * 32767).astype(np.int16)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('preset'); ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--preview', action='store_true', help='半分辨率，快速看效果')
    ap.add_argument('--seconds', type=float, default=None, help='只渲前几秒')
    a = ap.parse_args()
    cfg = merge(DEFAULT, json.load(open(a.preset, encoding='utf-8')))
    scale = 0.5 if a.preview else 1.0
    dur = min(a.seconds, cfg["duration"]) if a.seconds else cfg["duration"]
    sim = Sim(cfg, scale)
    fps = cfg["fps"]; sub = cfg["substeps"]; dt = 1 / (fps * sub)
    out = os.path.abspath(a.out); base = os.path.splitext(out)[0]
    tmpv = base + '.silent.mp4'; tmpa = base + '.wav'
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{sim.W}x{sim.H}',
           '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', tmpv]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    bg = np.zeros((sim.H, sim.W, 3), np.uint8); bg[:] = bgr(cfg["background"])
    nf = int(dur * fps); t0 = time.time(); track = []; cover = None; best = -1
    for f in range(nf):
        if sim.burst_t is not None and sim.t > sim.burst_t + cfg["burst"]["tail"]:
            dur = sim.t
            break
        sim.maybe_events()
        for _ in range(sub):
            sim.step(dt)
        img = bg.copy(); sim.draw(img)
        ff.stdin.write(img.tobytes())
        track.append((sim.t, len(sim.p)))
        if sim.burst_t is None and len(sim.p) >= best:
            best = len(sim.p); cover = img
        if f == 0 or (f + 1) % (fps * 5) == 0:
            print(f'  {sim.t:5.1f}s  球数 {len(sim.p):5d}  已用 {time.time() - t0:5.1f}s', flush=True)
    ff.stdin.close(); ff.wait()
    ok_, buf = cv2.imencode('.jpg', cover, [cv2.IMWRITE_JPEG_QUALITY, 92])  # imwrite 不认中文路径
    open(base + '_cover.jpg', 'wb').write(buf.tobytes())
    if cfg["audio"]["on"]:
        render_audio(sim.events, dur, cfg, cfg["seed"], tmpa, track)
        L = cfg["audio"]["lufs"]
        # 两遍 loudnorm（linear），只整体调音量，保留「从稀到密」的起伏
        r = subprocess.run(['ffmpeg', '-hide_banner', '-i', tmpa, '-af', f'loudnorm=I={L}:TP=-1.5:LRA=20:print_format=json',
                            '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8', errors='ignore')
        js = json.loads(r.stderr[r.stderr.rfind('{'):r.stderr.rfind('}') + 1])
        af = (f"loudnorm=I={L}:TP=-1.5:LRA=20:measured_I={js['input_i']}:measured_TP={js['input_tp']}:"
              f"measured_LRA={js['input_lra']}:measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true")
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmpv, '-i', tmpa, '-c:v', 'copy', '-af', af,
                        '-c:a', 'aac', '-b:a', '192k', '-shortest', out], check=True)
        os.remove(tmpv); os.remove(tmpa)
    else:
        os.replace(tmpv, out)
    print(f'完成：{out}（{dur:.0f} 秒，最后 {len(sim.p)} 个球，用时 {time.time() - t0:.0f} 秒）')


if __name__ == '__main__':
    main()
