"""生成 Copyama 应用图标（多尺寸 .ico）。

风格与托盘图标一致：白色圆角底板 + 深色剪贴板线条图案。
"""

from PIL import Image, ImageDraw, ImageFont
import os


def make_icon(size: int) -> Image.Image:
    """生成指定尺寸的图标。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 白色圆角底板
    radius = int(size * 0.22)
    padding = int(size * 0.08)
    draw.rounded_rectangle(
        [padding, padding, size - padding, size - padding],
        radius=radius,
        fill=(255, 255, 255, 255),
    )

    # 剪贴板图案（两个重叠的矩形 + 夹子）
    # 颜色：深灰，和主题的 line_strong 一致
    color = (30, 30, 30, 255)
    lw = max(2, int(size * 0.06))  # 线宽

    # 下方纸片
    paper_w = int(size * 0.42)
    paper_h = int(size * 0.5)
    paper_left = int(size * 0.28)
    paper_top = int(size * 0.35)
    draw.rounded_rectangle(
        [paper_left, paper_top, paper_left + paper_w, paper_top + paper_h],
        radius=max(2, int(size * 0.04)),
        outline=color,
        width=lw,
    )

    # 上方纸片（偏移一点，营造叠放感）
    top_w = int(size * 0.42)
    top_h = int(size * 0.38)
    top_left = int(size * 0.22)
    top_top = int(size * 0.22)
    draw.rounded_rectangle(
        [top_left, top_top, top_left + top_w, top_top + top_h],
        radius=max(2, int(size * 0.04)),
        fill=(255, 255, 255, 255),
        outline=color,
        width=lw,
    )

    # 夹子（顶部小矩形）
    clip_w = int(size * 0.18)
    clip_h = int(size * 0.08)
    clip_left = top_left + int(top_w * 0.15)
    clip_top = top_top - int(clip_h * 0.4)
    draw.rounded_rectangle(
        [clip_left, clip_top, clip_left + clip_w, clip_top + clip_h],
        radius=max(1, int(size * 0.02)),
        fill=color,
    )

    # 上方纸片上的横线（模拟文字行）
    line_color = (120, 120, 120, 255)
    line_l = top_left + int(top_w * 0.15)
    line_r = top_left + int(top_w * 0.85)
    line_y1 = top_top + int(top_h * 0.32)
    line_y2 = top_top + int(top_h * 0.52)
    line_y3 = top_top + int(top_h * 0.72)
    line_w = max(1, int(size * 0.025))
    draw.rounded_rectangle(
        [line_l, line_y1, line_r, line_y1 + line_w],
        radius=line_w // 2,
        fill=line_color,
    )
    draw.rounded_rectangle(
        [line_l, line_y2, line_r - int(top_w * 0.15), line_y2 + line_w],
        radius=line_w // 2,
        fill=line_color,
    )
    draw.rounded_rectangle(
        [line_l, line_y3, line_r - int(top_w * 0.3), line_y3 + line_w],
        radius=line_w // 2,
        fill=line_color,
    )

    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icons = [make_icon(s) for s in sizes]

    out_dir = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "app.ico")

    # 保存为多尺寸 ICO
    icons[0].save(
        out_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=icons[1:],
    )
    print(f"图标已生成：{out_path}（包含 {len(sizes)} 个尺寸）")


if __name__ == "__main__":
    main()
