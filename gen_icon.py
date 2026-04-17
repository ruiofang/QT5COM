#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成程序 Logo：
    app.png  (256x256)  -- 通用 / Linux
    app.ico             -- Windows（若安装了 Pillow）
用法:
    python3 gen_icon.py
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (QImage, QPainter, QColor, QLinearGradient, QPen,
                         QBrush, QFont, QPainterPath, QPolygonF)
from PyQt5.QtWidgets import QApplication


def draw_logo(size: int = 256) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing |
                     QPainter.SmoothPixmapTransform)

    # ---- 背景：圆角渐变方块 ----
    rect = QRectF(8, 8, size - 16, size - 16)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#1f6feb"))
    grad.setColorAt(1.0, QColor("#0d3b78"))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor(0, 0, 0, 40), 2))
    p.drawRoundedRect(rect, 40, 40)

    # ---- 波形（代表串口通讯） ----
    pen = QPen(QColor("#9ad0ff"), size * 0.05)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    baseline = size * 0.72
    step = (size - 60) / 6
    x = 30
    y = baseline
    path.moveTo(x, y)
    levels = [0, -1, -1, 1, 1, 0, 0]  # 高低电平
    amp = size * 0.09
    for i, lv in enumerate(levels[1:], start=1):
        nx = x + step
        ny = baseline + lv * amp
        # 垂直过渡
        if ny != y:
            path.lineTo(x, ny)
        path.lineTo(nx, ny)
        x, y = nx, ny
    p.drawPath(path)

    # ---- 文字 "COM" ----
    p.setPen(QColor("white"))
    font = QFont("Arial Black", int(size * 0.22), QFont.Black)
    if not font.exactMatch():
        font = QFont("Arial", int(size * 0.22), QFont.Black)
    p.setFont(font)
    text_rect = QRectF(0, size * 0.18, size, size * 0.38)
    p.drawText(text_rect, Qt.AlignCenter, "COM")

    # ---- 小圆点装饰 ----
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#9ad0ff"))
    r = size * 0.018
    for cx in (size * 0.22, size * 0.5, size * 0.78):
        p.drawEllipse(QPointF(cx, size * 0.85), r, r)

    p.end()
    return img


def save_ico(png_path: Path, ico_path: Path) -> bool:
    try:
        from PIL import Image
    except ImportError:
        print("提示: 未安装 Pillow，跳过 .ico 生成。`pip install pillow` 可生成 Windows 图标。")
        return False
    im = Image.open(png_path)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im.save(ico_path, format="ICO", sizes=sizes)
    return True


def main():
    app = QApplication(sys.argv)  # noqa: F841  Qt 绘图必需
    png = HERE / "app.png"
    ico = HERE / "app.ico"
    img = draw_logo(256)
    img.save(str(png), "PNG")
    print(f"✔ 生成 {png}")
    if save_ico(png, ico):
        print(f"✔ 生成 {ico}")


if __name__ == "__main__":
    main()
