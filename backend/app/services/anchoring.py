"""标注锚定的版本对齐（PRD §8.3 / §9）：文档重新生成后尽力继承块 ID。"""
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.services.docparser import ParsedBlock, content_hash


@dataclass
class OldSection:
    id: str
    content_hash: str
    text: str  # 归一化文本（excerpt 或全文皆可，用于模糊匹配）


def align_ids(old: list[OldSection], new_blocks: list[ParsedBlock]) -> list[str | None]:
    """返回与 new_blocks 等长的列表：对齐上的位置给旧 id，否则 None。

    两轮单调贪心：先精确哈希，再文本相似度（阈值 0.6）。
    """
    result: list[str | None] = [None] * len(new_blocks)
    used = set()

    # 第一轮：content_hash 精确匹配（保持单调）
    j = 0
    for i, nb in enumerate(new_blocks):
        h = content_hash(nb.text)
        k = j
        while k < len(old):
            if old[k].id not in used and old[k].content_hash == h:
                result[i] = old[k].id
                used.add(old[k].id)
                j = k + 1
                break
            k += 1

    # 第二轮：相似度匹配（同样单调）。短块 ratio 偏低，旧文包含于新文视为强匹配
    j = 0
    for i, nb in enumerate(new_blocks):
        if result[i] is not None:
            continue
        k = j
        while k < len(old):
            if old[k].id in used:
                k += 1
                continue
            if old[k].text and old[k].text in nb.text:
                result[i] = old[k].id
                used.add(old[k].id)
                j = k + 1
                break
            ratio = SequenceMatcher(None, nb.text[:200], old[k].text[:200]).ratio()
            if ratio >= 0.5:
                result[i] = old[k].id
                used.add(old[k].id)
                j = k + 1
                break
            k += 1
    return result
