"""PPT Designer — professional slide templates and styling helpers."""

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Predefined professional color themes
THEMES: Dict[str, dict] = {
    "ocean": {
        "name": "深海蓝",
        "bg": "#0B3D5C", "accent": "#1A8FE3", "text": "#FFFFFF",
        "light_bg": "#F0F6FA", "dark_text": "#0B3D5C",
    },
    "sunset": {
        "name": "日落橙",
        "bg": "#2D1B2E", "accent": "#FF6B35", "text": "#FFFFFF",
        "light_bg": "#FFF5F0", "dark_text": "#2D1B2E",
    },
    "forest": {
        "name": "森林绿",
        "bg": "#1B4332", "accent": "#52B788", "text": "#FFFFFF",
        "light_bg": "#F0FAF4", "dark_text": "#1B4332",
    },
    "modern": {
        "name": "现代灰",
        "bg": "#1A1A2E", "accent": "#6C63FF", "text": "#FFFFFF",
        "light_bg": "#F5F5F7", "dark_text": "#1A1A2E",
    },
    "classic": {
        "name": "经典白",
        "bg": "#FFFFFF", "accent": "#2563EB", "text": "#1E293B",
        "light_bg": "#F8FAFC", "dark_text": "#1E293B",
    },
}

# PPT Designer system prompt — {save_dir} is injected at runtime
PPT_DESIGNER_PROMPT = """你是专业 PPT 设计师。你只能通过 python-pptx 生成幻灯片。

你必须按以下流程操作：

1. **[确认: 请确认PPT参数 选项: 1.内容:xxx 2.风格:ocean/sunset/forest/modern/classic 3.页数:10 4.主题色:蓝色]** 
   等待用户回复确认后再继续

2. 收到用户确认后，使用 python-pptx 生成 PPT：
   - Prs = Presentation()，设置 16:9
   - 封面页: 深色背景 + 标题 + 副标题 + 日期
   - 目录页: 列出章节
   - 内容页: 浅色背景 + 标题 + 要点(最多5条) + 页码
   - 结束页: 深色背景 + "谢谢" + 联系方式
   - 统一字体: 标题 28pt bold, 正文 16pt
   - 关键数据用大号字体+主题色高亮
   - **必须保存到桌面目录: {save_dir}**

3. 完成后 → [结果: 成功 PPT已保存到完整路径.pptx] 或 [结果: 失败 原因]

使用的配色方案：
{themes}

禁止：
- 先展示代码再保存，必须直接保存文件
- 使用默认模板的任何占位符内容
- 不要保存到当前项目目录
"""


def format_themes_for_prompt() -> str:
    """Format theme definitions for the worker prompt."""
    lines = []
    for key, t in THEMES.items():
        lines.append(
            f"  {key}({t['name']}): 背景={t['bg']} 强调={t['accent']} 文字={t['text']} "
            f"浅底={t['light_bg']} 深字={t['dark_text']}"
        )
    return "\n".join(lines)


def get_designer_prompt(save_dir: Optional[str] = None) -> str:
    """Return the full PPT designer system prompt with themes and save path.

    Args:
        save_dir: Directory to save generated files. Defaults to Desktop.
    """
    if not save_dir:
        save_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    return PPT_DESIGNER_PROMPT.format(
        themes=format_themes_for_prompt(),
        save_dir=save_dir,
    )
