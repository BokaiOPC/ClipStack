# -*- coding: utf-8 -*-
"""生成 ClipStack 的提示音：复制开.wav（上行=开启）/ 复制关.wav（下行=关闭）"""
import math
import os
import struct
import wave

SR = 44100  # 采样率
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def tone(dur, freq, vol=0.5, decay=3.0):
    """单音：正弦+八度泛音，快起音+指数衰减，避免爆音。"""
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        env = min(1.0, i / (SR * 0.008)) * math.exp(-decay * t / dur)
        s = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
        out.append(vol * env * s / 1.25)
    return out


def save(name, samples):
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(x * 32767))))
            for x in samples))
    print("已生成", path, "(%.2f 秒)" % (len(samples) / SR))


# C5 E5 G5 上行琶音 —— 明亮、开启感
on = []
for f in (523.25, 659.25, 783.99):
    on += tone(0.11, f, vol=0.5)
on += tone(0.06, 0, vol=0.0)  # 尾部静音
save("复制开.wav", on)

# G5 E5 C5 下行 —— 柔和、关闭感
off = []
for f in (783.99, 659.25, 523.25):
    off += tone(0.13, f, vol=0.38, decay=2.2)
save("复制关.wav", off)
