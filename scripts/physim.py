#!/usr/bin/env python3
"""
physim.py  解压物理模拟视频（纯代码，不用任何图片、视频、音频素材）

圆形容器里一个转动的齿轮带着两条弯臂搅动小球；小球碰到齿轮就多出一个，
越变越多，装满后容器破开、小球倾泻而下。碰撞声由每一次碰撞实时合成。

用法：
  python physim.py preset.json -o out.mp4            # 正式渲染（默认 1080x1920、30fps）
  python physim.py preset.json -o test.mp4 --preview # 半分辨率、只渲前 12 秒，几十秒出结果
依赖：numpy、scipy、opencv-python、ffmpeg（命令行）
"""
import argparse, json, math, os, subprocess, sys, time, wave
import numpy as np
import cv2
from scipy.spatial import cKDTree

DEFAULT = {
    "width": 1080, "height": 1920, "fps": 30, "duration": 45, "seed": 7,
    "background": "#000000",
    "container": {"cx": 540, "cy": 940, "r": 440, "color": "#E6E6E6", "width": 3},
    "ball": {"r": 8.0, "restitution": 0.5, "max": 2600, "shine": True},
    "gravity": 700.0,
    "spinner": {"omega": 1.5, "arm_radius": 120, "arm_span_deg": 210, "arm_width": 14,
                "arm_color": "#9A9A9A", "gear_r": 24, "gear_teeth": 10, "gear_color": "#D0D0D0"},
    "multiply": {"on": "gear", "cooldown": 0.5, "max_per_step": 3, "speed": 380, "mutate": 0.0, "balance": False, "color": "inherit", "cycle": 3.5},
    "waves": {"every": 2.6, "count": 6, "until": 26, "first": 0.3,
              "palette": ["#B6E31F", "#8E44FF", "#2EE6D6", "#FF3B3B", "#FFD21F",
                          "#2F6BFF", "#FF3BD4", "#FF7A1A", "#2BD96B", "#FF6FA8"]},
    "burst": {"at_count": 2500, "at_time": 40.0, "tail": 6.0},
    "hud": {"counter": True, "y": 330, "scale": 3.2, "color": "#FFFFFF"},
    "audio": {"on": True, "click_gain": 1.0, "pop_gain": 0.5, "lufs": -14},
    "substeps": 6,
}


def merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def bgr(h):
    h = h.lstrip('#')
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


class Sim:
    def __init__(self, cfg, scale=1.0):
        self.c = cfg
        self.s = s = scale
        self.rng = np.random.default_rng(cfg["seed"])
        self.W, self.H = int(cfg["width"] * s), int(cfg["height"] * s)
        C = cfg["container"]
        self.cc = np.array([C["cx"] * s, C["cy"] * s])
        self.R = C["r"] * s
        self.r = cfg["ball"]["r"] * s
        self.e = cfg["ball"]["restitution"]
        self.g = cfg["gravity"] * s
        sp = cfg["spinner"]
        self.omega = sp["omega"]
        self.arm_a = sp["arm_radius"] * s
        self.arm_span = math.radians(sp["arm_span_deg"])
        self.arm_w = sp["arm_width"] * s
        self.gear_r = sp["gear_r"] * s
        self.theta = 0.0
        self.palette = [bgr(h) for h in cfg["waves"]["palette"]]
        self.maxn = cfg["ball"]["max"]
        self.p = np.zeros((0, 2)); self.v = np.zeros((0, 2))
        self.col = np.zeros(0, dtype=np.int32); self.last = np.zeros(0)
        self.t = 0.0
        self.burst_t = None
        self.next_wave = cfg["waves"]["first"]
        self.wave_i = 0
        self.events = []      # (t, kind, mag)  kind 0=click 1=pop 2=burst
        self.shards = None

    # ---------- spawning ----------
    def add(self, pos, vel, colidx):
        self.p = np.vstack([self.p, pos]); self.v = np.vstack([self.v, vel])
        self.col = np.concatenate([self.col, colidx]); self.last = np.concatenate([self.last, np.full(len(pos), self.t)])

    def wave(self):
        W = self.c["waves"]
        n = W["count"]
        ci = self.wave_i % len(self.palette); self.wave_i += 1
        ang = self.rng.uniform(-2.4, -0.7)
        base = self.cc + 0.72 * self.R * np.array([math.cos(ang), math.sin(ang)])
        pos = base + self.rng.normal(0, self.r * 1.6, (n, 2))
        vel = self.rng.normal(0, 40 * self.s, (n, 2))
        self.add(pos, vel, np.full(n, ci))

    # ---------- geometry ----------
    def arm_segments(self, K=18):
        segs = []
        for k in range(2):
            ph = self.theta + k * math.pi
            u = np.array([math.cos(ph), math.sin(ph)])
            ac = self.cc + u * self.arm_a
            phis = ph + math.pi + np.linspace(0, self.arm_span, K + 1)
            pts = ac + self.arm_a * np.stack([np.cos(phis), np.sin(phis)], 1)
            segs.append(pts)
        return segs

    # ---------- physics ----------
    def step(self, dt):
        if len(self.p) == 0:
            self.t += dt; self.theta += self.omega * dt; return
        p, v, r, e = self.p, self.v, self.r, self.e
        v[:, 1] += self.g * dt
        v *= 0.9995
        p += v * dt
        self.theta += self.omega * dt
        now = self.t
        # ball-ball
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
                    hard = -vn[m]
                    if len(hard):
                        self.events.append((now, 0, hard[hard > 40 * self.s] / self.s))
        # rotating arms (capsules)
        arm_hit = np.zeros(0, dtype=np.int64)
        segs = self.arm_segments()
        A = np.concatenate([s[:-1] for s in segs]); B = np.concatenate([s[1:] for s in segs])
        near = np.where(np.linalg.norm(p - self.cc, axis=1) < 2 * self.arm_a + self.arm_w + r)[0]
        if len(near):
            q = p[near]
            AB = B - A
            tt = np.clip(np.einsum('nsk,sk->ns', q[:, None, :] - A[None], AB) / np.einsum('sk,sk->s', AB, AB)[None], 0, 1)
            cl = A[None] + tt[..., None] * AB[None]
            diff = q[:, None, :] - cl
            dist = np.linalg.norm(diff, axis=2)
            k = dist.argmin(1); dmin = dist[np.arange(len(q)), k]
            lim = r + self.arm_w / 2
            hit = dmin < lim
            if hit.any():
                idx = near[hit]; arm_hit = idx
                dd = diff[np.arange(len(q)), k][hit]; dm = np.maximum(dmin[hit], 1e-6)
                n = dd / dm[:, None]
                p[idx] += n * (lim - dm)[:, None]
                rel = p[idx] - self.cc
                vo = self.omega * np.stack([-rel[:, 1], rel[:, 0]], 1)
                vr = v[idx] - vo
                vn = np.einsum('ij,ij->i', vr, n)
                m = vn < 0
                v[idx] -= ((1 + e) * vn * m)[:, None] * n
                v[idx] = v[idx] * 0.92 + vo * 0.08
                if m.any():
                    self.events.append((now, 0, (-vn[m]) / self.s))
        # gear
        rel = p - self.cc
        dist = np.linalg.norm(rel, axis=1)
        lim = self.gear_r + r
        g = np.where(dist < lim)[0]
        if len(g):
            n = rel[g] / np.maximum(dist[g], 1e-6)[:, None]
            p[g] = self.cc + n * lim
            vo = self.omega * np.stack([-rel[g, 1], rel[g, 0]], 1)
            vn = np.einsum('ij,ij->i', v[g] - vo, n)
            m = vn < 0
            v[g] -= ((1 + e) * vn * m)[:, None] * n
        # container or screen
        if self.burst_t is None:
            rel = p - self.cc
            dist = np.linalg.norm(rel, axis=1)
            o = np.where(dist > self.R - r)[0]
            if len(o):
                n = rel[o] / dist[o][:, None]
                p[o] = self.cc + n * (self.R - r)
                vn = np.einsum('ij,ij->i', v[o], n)
                m = vn > 0
                v[o] -= ((1 + e) * vn * m)[:, None] * n
                if m.any():
                    self.events.append((now, 0, vn[m] / self.s))
        else:
            for ax, lo, hi in ((0, r, self.W - r), (1, -1e9, self.H - r)):
                a = p[:, ax] < lo; b = p[:, ax] > hi
                p[a, ax] = lo; p[b, ax] = hi
                v[a, ax] = np.abs(v[a, ax]) * e; v[b, ax] = -np.abs(v[b, ax]) * e
        # multiply on gear contact
        M = self.c["multiply"]
        cand = g if M["on"] == "gear" else np.union1d(g, arm_hit)
        if self.burst_t is None and len(cand) and len(p) < self.maxn:
            ok = cand[(now - self.last[cand]) > M["cooldown"]]
            if M.get("balance") and len(ok):
                act = min(self.wave_i, len(self.palette))
                if act > 1:
                    cnt = np.bincount(self.col, minlength=len(self.palette)).astype(float)
                    lim = cnt[:act].mean() * M.get("balance_ratio", 1.3)
                    ok = ok[cnt[self.col[ok]] <= lim]
            if len(ok):
                ok = self.rng.permutation(ok)[:M["max_per_step"]]
                ok = ok[: max(0, self.maxn - len(p))]
                ang = self.rng.uniform(0, 2 * math.pi, len(ok))
                n = np.stack([np.cos(ang), np.sin(ang)], 1)
                pos = p[ok] + n * (2.05 * r)
                vel = v[ok] * 0.5 + n * M["speed"] * self.s
                self.last[ok] = now
                if M.get("color") == "cycle":
                    newc = np.full(len(ok), int(now / M["cycle"]) % len(self.palette))
                else:
                    newc = self.col[ok].copy()
                mut = self.rng.random(len(ok)) < M["mutate"]
                if mut.any():
                    newc[mut] = self.rng.integers(0, len(self.palette), mut.sum())
                self.add(pos, vel, newc)
                self.events.append((now, 1, np.full(len(ok), 1.0)))
        self.t += dt

    def maybe_events(self):
        W = self.c["waves"]
        if self.burst_t is None and self.t >= self.next_wave and self.t <= W["until"]:
            self.wave(); self.next_wave += W["every"]
        B = self.c["burst"]
        if self.burst_t is None and (len(self.p) >= B["at_count"] or self.t >= B["at_time"]):
            self.burst_t = self.t
            self.events.append((self.t, 2, np.array([1.0])))
            ang = np.linspace(0, 2 * math.pi, 37)
            self.shards = [(ang[i], ang[i + 1], self.rng.uniform(250, 600) * self.s) for i in range(36)]
            # 往外推一把，让球冲出来
            rel = self.p - self.cc
            d = np.maximum(np.linalg.norm(rel, axis=1), 1e-6)
            self.v += rel / d[:, None] * 220 * self.s

    # ---------- drawing ----------
    def draw(self, img):
        c, s = self.c, self.s
        sh = 4; F = 1 << sh
        r = self.r
        # balls
        ri = int(round(r * F))
        hl_off = int(round(-0.32 * r * F)); hl_r = int(round(0.38 * r * F))
        shine = c["ball"]["shine"]
        light = [tuple(int(ch + (255 - ch) * 0.6) for ch in col) for col in self.palette]
        P = (self.p * F).astype(np.int64)
        for k in range(len(self.palette)):
            idx = np.where(self.col == k)[0]
            colr = self.palette[k]; lc = light[k]
            for (x, y) in P[idx]:
                cv2.circle(img, (int(x), int(y)), ri, colr, -1, cv2.LINE_AA, sh)
            if shine:
                for (x, y) in P[idx]:
                    cv2.circle(img, (int(x + hl_off), int(y + hl_off)), hl_r, lc, -1, cv2.LINE_AA, sh)
        # container / shards
        C = c["container"]; ccol = bgr(C["color"]); cw = max(1, int(round(C["width"] * s)))
        cx, cy = self.cc
        if self.burst_t is None:
            cv2.circle(img, (int(cx * F), int(cy * F)), int(self.R * F), ccol, cw, cv2.LINE_AA, sh)
        else:
            dt = self.t - self.burst_t
            for a0, a1, sp in self.shards:
                mid = (a0 + a1) / 2
                off = np.array([math.cos(mid), math.sin(mid)]) * sp * dt + np.array([0, 0.5 * self.g * dt * dt])
                aa = np.linspace(a0, a1, 6)
                pts = np.stack([cx + self.R * np.cos(aa), cy + self.R * np.sin(aa)], 1) + off
                cv2.polylines(img, [(pts * F).astype(np.int32)], False, ccol, cw, cv2.LINE_AA, sh)
        # arms + gear (on top)
        sp = c["spinner"]; acol = bgr(sp["arm_color"]); aw = max(2, int(round(self.arm_w)))
        hi = tuple(min(255, int(ch * 1.35)) for ch in acol)
        for pts in self.arm_segments(36):
            ip = (pts * F).astype(np.int32)
            cv2.polylines(img, [ip], False, acol, aw, cv2.LINE_AA, sh)
            cv2.polylines(img, [ip], False, hi, max(1, aw // 4), cv2.LINE_AA, sh)
        gcol = bgr(sp["gear_color"]); T = sp["gear_teeth"]; gr = self.gear_r
        ang = self.theta * 1.0
        pts = []
        for i in range(T * 2):
            a0 = ang + i * math.pi / T
            rr = gr * (1.0 if i % 2 == 0 else 0.78)
            for da in (-0.5, 0.5):
                a = a0 + da * math.pi / T
                pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        cv2.fillPoly(img, [(np.array(pts) * F).astype(np.int32)], gcol, cv2.LINE_AA, sh)
        cv2.circle(img, (int(cx * F), int(cy * F)), int(gr * 0.32 * F), (40, 40, 40), -1, cv2.LINE_AA, sh)
        # HUD
        H = c["hud"]
        if H["counter"]:
            txt = f"{len(self.p):,}"
            sc = H["scale"] * s; th = max(2, int(round(5 * s)))
            (tw, tht), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_DUPLEX, sc, th)
            cv2.putText(img, txt, (int(self.W / 2 - tw / 2), int(H["y"] * s)), cv2.FONT_HERSHEY_DUPLEX, sc, bgr(H["color"]), th, cv2.LINE_AA)


# ---------- audio ----------
SR = 44100

def make_bank(rng):
    clicks, pops = [], []
    for k in range(24):
        f = rng.uniform(1400, 4200); L = int(SR * rng.uniform(0.012, 0.03))
        t = np.arange(L) / SR
        env = np.exp(-t / rng.uniform(0.003, 0.008))
        x = np.sin(2 * np.pi * f * t) * env + rng.normal(0, 0.25, L) * np.exp(-t / 0.0015)
        clicks.append(x / np.abs(x).max())
    for k in range(8):
        L = int(SR * 0.07); t = np.arange(L) / SR
        f = rng.uniform(500, 900) * (1 - 0.35 * t / t[-1])
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.018)
        pops.append(x / np.abs(x).max())
    L = int(SR * 1.2); t = np.arange(L) / SR
    boom = (rng.normal(0, 1, L) * np.exp(-t / 0.25) * 0.6 + np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.35))
    return clicks, pops, boom / np.abs(boom).max()


def render_audio(events, duration, cfg, seed, path, track=None):
    """track: [(t, 球数)]，用来让声音跟着球数从稀到密"""
    rng = np.random.default_rng(seed + 1)
    if track:
        tt = np.array([a for a, b in track]); nn = np.array([b for a, b in track], float)
        env = lambda t: 0.18 + 0.82 * (np.interp(t, tt, nn) / max(1.0, nn.max())) ** 0.8
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
            b = int(t / bucket)
            e, n = bins.get(b, (0.0, 0))
            bins[b] = (e + float(np.sum(np.minimum(mags, 1500) ** 2)), n + len(mags))
        elif kind == 1:
            for _ in range(min(len(mags), 2)):
                x = pops[rng.integers(len(pops))]; i = int(t * SR) + rng.integers(0, 200)
                out[i:i + len(x)] += x[:max(0, N - i)] * 0.10 * A["pop_gain"]
        else:
            i = int(t * SR); out[i:i + len(boom)] += boom[:max(0, N - i)] * 0.8
    for b, (e, n) in bins.items():
        if n == 0:
            continue
        tb = b * bucket
        k = max(1, int(round(min(n, 5) * env(tb))))
        amp = math.sqrt(e / n) / 1500
        for _ in range(k):
            x = clicks[rng.integers(len(clicks))]
            i = int(b * bucket * SR) + int(rng.integers(0, int(bucket * SR)))
            g = (0.05 + 0.5 * amp) * rng.uniform(0.6, 1.0) * A["click_gain"] * env(tb)
            out[i:i + len(x)] += x[:max(0, N - i)] * g
    out = out[:int(SR * duration)]
    out = np.tanh(out * 1.2)
    out /= max(1e-6, np.abs(out).max()) / 0.9
    st = np.stack([out, out], 1)
    pcm = (st * 32767).astype(np.int16)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('preset'); ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--preview', action='store_true', help='半分辨率，快速看效果')
    ap.add_argument('--seconds', type=float, default=None, help='只渲前几秒')
    ap.add_argument('--cover-at', type=float, default=None, help='第几秒的画面存成封面（默认爆开前 1 秒）')
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
    nf = int(dur * fps); t0 = time.time(); cover = None; track = []
    for f in range(nf):
        if sim.burst_t is not None and sim.t > sim.burst_t + cfg["burst"]["tail"]:
            dur = sim.t
            break
        sim.maybe_events()
        for _ in range(sub):
            sim.step(dt)
        img = bg.copy(); sim.draw(img)
        track.append((sim.t, len(sim.p)))
        ff.stdin.write(img.tobytes())
        if a.cover_at is not None and cover is None and sim.t >= a.cover_at:
            cover = img.copy()
        if f == 0 or (f + 1) % (fps * 5) == 0:
            print(f'  {sim.t:5.1f}s  球数 {len(sim.p):5d}  已用 {time.time() - t0:5.1f}s', flush=True)
        if a.cover_at is None and sim.burst_t is None:
            last_full = img
    ff.stdin.close(); ff.wait()
    if cover is None:
        cover = last_full
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
