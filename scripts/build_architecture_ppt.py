#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build an editable PowerPoint of the QuadMix modularization architecture."""

import json
import os
import sys
from pathlib import Path

EDSDK_DIR = "C:/Users/Win 11 Pro/.workbuddy/plugins/cache/workbuddy-builtin/skill-tencent-local-office-edit/0.0.1"
sys.path.insert(0, EDSDK_DIR)
import edsdk  # noqa: E402

OUT_PATH = "D:/HW/Auto-Mixture-Tool/docs/QuadMix-工具化重构模块框架图.tmp.pptx"

# Slide size: 16:9 in points (13.333" x 7.5")
W, H = 960, 540

# Layout constants
MARGIN = 10
TITLE_Y = 10
SUBTITLE_Y = 48
CONTENT_Y = 82
LEFT_SIDEBAR_X = MARGIN
LEFT_SIDEBAR_W = 90
MAIN_X = LEFT_SIDEBAR_X + LEFT_SIDEBAR_W + 10
MAIN_W = 730
RIGHT_X = MAIN_X + MAIN_W + 12
RIGHT_W = W - RIGHT_X - MARGIN

# Colors (hex without #)
C_TITLE_BG = "1E3A8A"
C_TITLE_TEXT = "FFFFFF"
C_LAYER2 = "DBEAFE"
C_LAYER3 = "D1FAE5"
C_LAYER4 = "E0F2FE"
C_LAYER5 = "EFF6FF"
C_LAYER6 = "DCFCE7"
C_LAYER7 = "F3E8FF"
C_LAYER8 = "FEF3C7"
C_LAYER9 = "FEE2E2"
C_BORDER = "1E40AF"
C_DARK_TEXT = "1E293B"
C_LIGHT_TEXT = "FFFFFF"
C_INNER_BG = "FFFFFF"


def rpc(tool_name: str, **arguments):
    """Call an editor_sdk tool by name and return its parsed result."""
    result = edsdk._rpc("tools/call", {"name": tool_name, "arguments": arguments})
    texts = [c.get("text", "") for c in (result.get("content") or [])
             if isinstance(c, dict) and c.get("type") == "text"]
    payload = "\n".join(texts)
    try:
        return json.loads(payload) if payload else result
    except json.JSONDecodeError:
        return payload if payload else result


def _extract_field(text: str, key: str) -> str:
    for part in str(text).replace(",", " ").split():
        if part.startswith(f"{key}="):
            return part.split("=", 1)[1]
    return ""


def create_presentation():
    result = rpc("create_slide")
    file_path = _extract_field(result, "file_path")
    if not file_path:
        raise RuntimeError(f"Could not parse file_path from create_slide result: {result!r}")
    # open_file fully materialises the editor session; create_slide alone leaves
    # the presentation in a "created but not open" state for some edit tools.
    rpc("open_file", file_path=file_path, file_type="slide")
    import time
    time.sleep(0.3)
    pool = rpc("get_pool_status")
    basename = Path(file_path).stem
    editable_id = None
    for ed in pool.get("open_editors", []):
        if ed.get("file_id", "").startswith(basename) and not ed.get("file_path"):
            editable_id = ed["file_id"]
            break
    if not editable_id:
        # Fallback: the file_path entry itself may also work in some builds
        editable_id = file_path
    file_id = editable_id
    rpc("slide_set_slide_size", file_id=file_id, aspect_ratio=2)
    rpc(
        "slide_set_page_properties",
        file_id=file_id,
        page_index=0,
        fill_type="solid",
        fill_color="F8FAFC",
    )
    return file_id


def add_title_slide(file_id: str):
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=0,
        x=20,
        y=TITLE_Y,
        w=W - 40,
        h=40,
        text="QuadMix 工具化重构模块框架图",
        font_name="Microsoft YaHei",
        font_size=32,
        font_color=C_TITLE_BG,
    )
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=0,
        x=20,
        y=SUBTITLE_Y,
        w=W - 40,
        h=24,
        text="面向数据配比算法、训练验证与集群调度的可插拔平台",
        font_name="Microsoft YaHei",
        font_size=15,
        font_color="64748B",
    )


def add_sidebar(file_id: str):
    # Background rounded rect for the data-flow sidebar
    rpc(
        "slide_add_shape",
        file_id=file_id,
        page_index=0,
        x=LEFT_SIDEBAR_X,
        y=CONTENT_Y,
        w=LEFT_SIDEBAR_W,
        h=H - CONTENT_Y - MARGIN,
        shape_type="roundRect",
        fill_color="EFF6FF",
        border_color=C_BORDER,
        border_width=1,
    )
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=0,
        x=LEFT_SIDEBAR_X,
        y=CONTENT_Y + 6,
        w=LEFT_SIDEBAR_W,
        h=24,
        text="数据流说明",
        font_name="Microsoft YaHei",
        font_size=12,
        font_color=C_TITLE_BG,
    )
    steps = [
        "① 上传数据集",
        "② 数据校验",
        "③ 统一数据接口",
        "④ 配比算法选择",
        "⑤ 训练",
        "⑥ 验证",
        "⑦ 结果分析",
    ]
    step_h = 52
    start_y = CONTENT_Y + 36
    for i, step in enumerate(steps):
        y = start_y + i * step_h
        rpc(
            "slide_add_shape",
            file_id=file_id,
            page_index=0,
            x=LEFT_SIDEBAR_X + 10,
            y=y,
            w=LEFT_SIDEBAR_W - 20,
            h=34,
            shape_type="roundRect",
            fill_color=C_TITLE_BG if i == 0 else "FFFFFF",
            border_color=C_BORDER,
            border_width=1,
        )
        rpc(
            "slide_add_text",
            file_id=file_id,
            page_index=0,
            x=LEFT_SIDEBAR_X + 10,
            y=y + 8,
            w=LEFT_SIDEBAR_W - 20,
            h=18,
            text=step,
            font_name="Microsoft YaHei",
            font_size=10,
            font_color=C_LIGHT_TEXT if i == 0 else C_DARK_TEXT,
        )


def add_layer(file_id: str, index: int, y: float, h: float, number: str, title: str,
              components: list, fill_color: str, inner_bg: str = C_INNER_BG,
              title_text_color: str = C_DARK_TEXT):
    """Add one numbered layer with component boxes."""
    # Layer background
    rpc(
        "slide_add_shape",
        file_id=file_id,
        page_index=0,
        x=MAIN_X,
        y=y,
        w=MAIN_W,
        h=h,
        shape_type="roundRect",
        fill_color=fill_color,
        border_color=C_BORDER,
        border_width=1,
    )
    # Number badge
    badge_size = 22
    rpc(
        "slide_add_shape",
        file_id=file_id,
        page_index=0,
        x=MAIN_X + 8,
        y=y + (h - badge_size) / 2,
        w=badge_size,
        h=badge_size,
        shape_type="roundRect",
        fill_color=C_TITLE_BG,
        border_color=C_TITLE_BG,
        border_width=1,
    )
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=0,
        x=MAIN_X + 8,
        y=y + (h - badge_size) / 2 + 3,
        w=badge_size,
        h=16,
        text=number,
        font_name="Microsoft YaHei",
        font_size=12,
        font_color=C_LIGHT_TEXT,
    )
    # Layer title
    title_w = 100
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=0,
        x=MAIN_X + 34,
        y=y + (h - 20) / 2,
        w=title_w,
        h=20,
        text=title,
        font_name="Microsoft YaHei",
        font_size=11,
        font_color=title_text_color,
    )
    # Component boxes
    if components:
        comp_x0 = MAIN_X + 34 + title_w + 10
        comp_w = (MAIN_X + MAIN_W - 10 - comp_x0 - 6 * (len(components) - 1)) / max(len(components), 1)
        comp_h = h - 12
        comp_y = y + 6
        for j, comp in enumerate(components):
            cx = comp_x0 + j * (comp_w + 6)
            rpc(
                "slide_add_shape",
                file_id=file_id,
                page_index=0,
                x=cx,
                y=comp_y,
                w=comp_w,
                h=comp_h,
                shape_type="roundRect",
                fill_color=inner_bg,
                border_color="94A3B8",
                border_width=0.75,
            )
            rpc(
                "slide_add_text",
                file_id=file_id,
                page_index=0,
                x=cx + 3,
                y=comp_y + (comp_h - 16) / 2,
                w=comp_w - 6,
                h=16,
                text=comp,
                font_name="Microsoft YaHei",
                font_size=9,
                font_color=C_DARK_TEXT,
            )


def add_layers(file_id: str):
    layers = [
        ("1", "用户接口层", ["CLI", "API", "YAML配置", "Web/服务接口"], C_LAYER2),
        ("2", "实验编排与调度层", ["Pipeline Manager", "任务编排", "日志与检查点", "高性能集群任务提交"], C_LAYER2),
        ("3", "数据检测与验证层", ["上传数据集校验", "格式校验·可替换", "列类型检查", "标签检查", "编码检查", "重复文件", "质量/重复率"], C_LAYER3),
        ("4", "配置管理层", ["dataset config", "algorithm config", "training config", "evaluation config"], C_LAYER4),
        ("5", "统一数据抽象层", ["Dataset Loader", "Dataset Schema", "Dataset Metadata", "Dataset Statistics"], C_LAYER5),
        ("6", "数据配比算法插件层", ["QuadMix插件", "Random插件", "Manual Ratio插件", "其他算法插件"], C_LAYER6),
        ("7", "训练与验证插件层", ["NanoChat Trainer", "Trainer/Evaluator\nInterface", "STEM Eval", "自定义Eval"], C_LAYER7),
        ("8", "分布式执行与集群层", ["高性能集群API", "Slurm", "Kubernetes", "GPU/NPU资源调度", "远程训练任务"], C_LAYER8),
        ("9", "结果分析与实验管理层", ["loss曲线", "STEM分数", "多样性分析", "质量分布", "消融对比", "实验报告"], C_LAYER9),
    ]
    heights = [34, 34, 54, 34, 34, 54, 54, 34, 54]
    gap = 6
    y = CONTENT_Y
    for (num, title, comps, color), h in zip(layers, heights):
        add_layer(file_id, 0, y, h, num, title, comps, color)
        y += h + gap
    return y


def add_right_annotations(file_id: str, layers_bottom: float):
    # Vertical flow arrows between key layers
    arrows = [
        (MAIN_X + MAIN_W / 2, CONTENT_Y + 34 + 3, MAIN_X + MAIN_W / 2, CONTENT_Y + 34 + 6),  # 1->2
        (MAIN_X + MAIN_W / 2, CONTENT_Y + 34 + 6 + 34, MAIN_X + MAIN_W / 2, CONTENT_Y + 34 + 6 + 34 + 6),  # 2->3
    ]
    # Draw a few representative arrows
    rpc(
        "slide_add_line_shapes",
        file_id=file_id,
        page_index=0,
        lines=[
            {"x1": MAIN_X + MAIN_W / 2, "y1": CONTENT_Y + 34 + 3, "x2": MAIN_X + MAIN_W / 2, "y2": CONTENT_Y + 34 + 6, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
            {"x1": MAIN_X + MAIN_W / 2, "y1": CONTENT_Y + 34 + 6 + 34, "x2": MAIN_X + MAIN_W / 2, "y2": CONTENT_Y + 34 + 6 + 34 + 6, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
            {"x1": MAIN_X + MAIN_W / 2, "y1": CONTENT_Y + 34 + 6 + 34 + 6 + 54, "x2": MAIN_X + MAIN_W / 2, "y2": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
            {"x1": MAIN_X + MAIN_W / 2, "y1": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34, "x2": MAIN_X + MAIN_W / 2, "y2": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
            {"x1": MAIN_X + MAIN_W / 2, "y1": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6 + 34, "x2": MAIN_X + MAIN_W / 2, "y2": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6 + 34 + 6, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
            {"x1": MAIN_X + MAIN_W / 2, "y1": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6 + 34 + 6 + 54, "x2": MAIN_X + MAIN_W / 2, "y2": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6 + 34 + 6 + 54 + 6, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
            {"x1": MAIN_X + MAIN_W / 2, "y1": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6 + 34 + 6 + 54 + 6 + 54, "x2": MAIN_X + MAIN_W / 2, "y2": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6 + 34 + 6 + 54 + 6 + 54 + 6, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
            {"x1": MAIN_X + MAIN_W / 2, "y1": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6 + 34 + 6 + 54 + 6 + 54 + 6 + 34, "x2": MAIN_X + MAIN_W / 2, "y2": CONTENT_Y + 34 + 6 + 34 + 6 + 54 + 6 + 34 + 6 + 34 + 6 + 54 + 6 + 54 + 6 + 34 + 6, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
        ],
    )

    # Right-side callouts
    callouts = [
        ("先校验，\n再运行", "保障数据质量\n降低运行风险", "FEF3C7", "92400E"),
        ("算法模块\n可替换", "遵循统一接口\n轻松扩展新算法", "DCFCE7", "166534"),
        ("验证方法\n可切换", "评测插件化\n按需选择最佳方案", "F3E8FF", "6B21A8"),
    ]
    callout_h = 80
    gap_y = 20
    total_h = len(callouts) * callout_h + (len(callouts) - 1) * gap_y
    start_y = CONTENT_Y + 60
    for i, (title, desc, bg, text_c) in enumerate(callouts):
        y = start_y + i * (callout_h + gap_y)
        rpc(
            "slide_add_shape",
            file_id=file_id,
            page_index=0,
            x=RIGHT_X,
            y=y,
            w=RIGHT_W,
            h=callout_h,
            shape_type="roundRect",
            fill_color=bg,
            border_color=text_c,
            border_width=1.5,
        )
        rpc(
            "slide_add_text",
            file_id=file_id,
            page_index=0,
            x=RIGHT_X + 6,
            y=y + 8,
            w=RIGHT_W - 12,
            h=22,
            text=title,
            font_name="Microsoft YaHei",
            font_size=12,
            font_color=text_c,
        )
        rpc(
            "slide_add_text",
            file_id=file_id,
            page_index=0,
            x=RIGHT_X + 6,
            y=y + 32,
            w=RIGHT_W - 12,
            h=44,
            text=desc,
            font_name="Microsoft YaHei",
            font_size=9,
            font_color=text_c,
        )

    # Legend
    legend_y = H - MARGIN - 32
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=0,
        x=RIGHT_X,
        y=legend_y,
        w=RIGHT_W,
        h=14,
        text="图例 — 数据流/控制流",
        font_name="Microsoft YaHei",
        font_size=9,
        font_color="64748B",
    )
    rpc(
        "slide_add_line_shapes",
        file_id=file_id,
        page_index=0,
        lines=[
            {"x1": RIGHT_X + 90, "y1": legend_y + 10, "x2": RIGHT_X + 120, "y2": legend_y + 10, "line_type": "arrow", "line_color": C_BORDER, "line_width": 1.5},
            {"x1": RIGHT_X + 90, "y1": legend_y + 22, "x2": RIGHT_X + 120, "y2": legend_y + 22, "line_type": "solid", "line_color": "94A3B8", "line_width": 1.5, "border_dash": "dash"},
        ],
    )
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=0,
        x=RIGHT_X + 124,
        y=legend_y + 2,
        w=80,
        h=14,
        text="实线 = 数据流",
        font_name="Microsoft YaHei",
        font_size=8,
        font_color="64748B",
    )
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=0,
        x=RIGHT_X + 124,
        y=legend_y + 16,
        w=80,
        h=14,
        text="虚线 = 依赖关系",
        font_name="Microsoft YaHei",
        font_size=8,
        font_color="64748B",
    )


def add_reference_slide(file_id: str, image_path: str):
    rpc("slide_duplicate_slide", file_id=file_id, page_indexes=[0])
    rpc(
        "slide_set_page_properties",
        file_id=file_id,
        page_index=1,
        fill_type="solid",
        fill_color="FFFFFF",
    )
    rpc(
        "slide_add_text",
        file_id=file_id,
        page_index=1,
        x=20,
        y=10,
        w=W - 40,
        h=30,
        text="原始架构图参考",
        font_name="Microsoft YaHei",
        font_size=24,
        font_color=C_TITLE_BG,
    )
    rpc(
        "slide_add_image",
        file_id=file_id,
        page_index=1,
        x=80,
        y=50,
        w=W - 160,
        h=H - 70,
        image=image_path,
    )


def main():
    Path(OUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    file_id = create_presentation()
    add_title_slide(file_id)
    add_sidebar(file_id)
    layers_bottom = add_layers(file_id)
    add_right_annotations(file_id, layers_bottom)

    image_path = "C:/Users/Win 11 Pro/.workbuddy/clipboard-images/clipboard-2026-08-17T06-25-17-234Z-637b140c.jpg"
    if Path(image_path).exists():
        add_reference_slide(file_id, image_path)

    rpc("save_file", file_id=file_id, file_path=OUT_PATH)
    print(f"Saved editable architecture PPT to: {OUT_PATH}")


if __name__ == "__main__":
    main()
