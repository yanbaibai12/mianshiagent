import json
import re
from typing import Any


def extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出中安全提取 JSON"""
    text = text.strip()

    # 移除 markdown 代码块标记
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 {} 或 [] 包裹的内容
    match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 输出中提取有效 JSON: {text[:200]}")


def safe_get(data: dict, key: str, default: Any = None) -> Any:
    """安全获取字典值"""
    return data.get(key, default)
