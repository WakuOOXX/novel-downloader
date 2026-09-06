# -*- coding: utf-8 -*-
"""多选交互策略(纯逻辑,可脱离 GUI 测试)。

涵盖:单击/多选单击切换、橡皮筋框选命中(与框相交/内含)、模式切换收敛、
记忆恢复容错。所有函数无副作用,便于单测。
"""

MIN_DRAG = 6          # 框选最小拖动阈值(px):低于此视为单击,不触发框选
DOUBLE_MS = 450       # 双击判定间隔(ms)


def normalize_rect(x1, y1, x2, y2):
    """把任意两点规整成 (left, top, right, bottom)。"""
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def rects_intersect(a, b):
    """两矩形 (l,t,r,b) 是否相交(含边界接触)。"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


def rows_in_rect(tree, rect):
    """返回与 rect(视图坐标,l,t,r,b)相交或内含的所有行 id。

    tree 需提供 duck-typing 接口:
      - tree.get_children() -> 行 id 列表
      - tree.bbox(iid) -> (x, y, w, h) 或 None(行不可见)
    只统计可见行——不可见行 bbox 为 None,天然被忽略。
    """
    out = set()
    for iid in tree.get_children():
        b = tree.bbox(iid)
        if not b:
            continue
        if rects_intersect(rect, (b[0], b[1], b[0] + b[2], b[1] + b[3])):
            out.add(iid)
    return out


def apply_click(current, multi, row):
    """单击后的选中集(资源管理器式)。

    - row 为空(点到空白):单选模式清空;多选模式保持不动。
    - 单选模式(或无修饰键单击):无论原来选了什么,只选该行(自动取消其它)。
    - Ctrl+单击(Ctrl 即 multi=True):单击已选中的项 -> 取消;单击未选中项 -> 加入。
    """
    cur = set(current)
    if not row:
        return set() if not multi else cur
    if not multi:
        return {row}
    if row in cur:
        cur.discard(row)
    else:
        cur.add(row)
    return cur


def apply_range(order, anchor, row):
    """Shift+单击:选中 order 中从 anchor 到 row 的连续范围(含两端)。

    行为与资源管理器一致:范围=替换当前选中。order 为行 id 的展示顺序。
    任一端缺失时退回单选该行。
    """
    if not order or not row:
        return {row} if row else set()
    if anchor not in order:
        return {row}
    ia, ir = order.index(anchor), order.index(row)
    lo, hi = min(ia, ir), max(ia, ir)
    return set(order[lo:hi + 1])


def apply_rubber(current, added, append):
    """框选结束:append=True 追加进现有选中;False 则替换为框内结果。"""
    if append:
        return set(current) | set(added)
    return set(added)


def restore_filter(stored_keys, available_keys):
    """记忆恢复容错:只保留当前仍存在的条目;数据项已消失的静默跳过。"""
    avail = set(available_keys)
    return [k for k in stored_keys if k in avail]
