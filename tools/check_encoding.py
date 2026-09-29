"""编码与中文一致性检查（提交前跑；阶段 0 交付物 N9）

检查四件事：
  1. BOM         —— 文件是否被写成 UTF-8 with BOM（幂等性问题，且是历史事故的指纹）
  2. UTF-8 解码  —— 文件是否被存成了 GBK/ANSI（会让整个文件读不出来）
  3. 二次编码乱码 —— 中文被「UTF-8→GBK 读、再 UTF-8 写」污染的行
  4. 中文比较字面量 —— `==` / `!=` / `in` 参与逻辑判断的中文字符串（P0-1 那类 bug）
                      这一项是**提示**不是错误，用于人工核对「两侧是否来自同一来源」

用法：
  python tools/check_encoding.py            # 检查仓库内所有 .py
  python tools/check_encoding.py --all      # 连 .md/.json/.bat 一起检查
  python tools/check_encoding.py main.py    # 只检查指定文件

退出码：发现 1/2/3 类问题返回 1，否则 0。（可直接用于提交前钩子）
"""
from __future__ import annotations

import sys
from pathlib import Path

BOMS = {
    b"\xef\xbb\xbf": "UTF-8 with BOM",
    b"\xff\xfe\x00\x00": "UTF-32 LE BOM",
    b"\x00\x00\xfe\xff": "UTF-32 BE BOM",
    b"\xff\xfe": "UTF-16 LE BOM",
    b"\xfe\xff": "UTF-16 BE BOM",
}

CYRILLIC_ISH = ("\u4e00", "\u9fff")  # CJK 统一表意文字区间

# 本项目 v2.2.1~v2.2.9 实际出现过的乱码字（人工核对过，已剔除 块/定 等真实汉字——
# 它们曾在我的第一次扫描里造成误报）。用「疑似」级别报告，供人工确认。
# 严格还原（restore）判据对含 € 等 GBK 单字节字符的行会失效，这类行靠本表兜底。
SUSPICIOUS_CHARS = set(
    "鍔犺浇鎺ㄩ佽褰瀛樻渶杩戜娆洖娴嬬粨鏋鏆磋穼閬櫓鎻愰鍑洪敊涓诲惊鐜嚭閿"
    "涔板叆鍗栧嚭鎴愪粨鍏ㄩ儴姝㈢泩鎹熷埌浣犺缃殑鍒拱绛夊洖璋冭傛湜鏄庣‘淇"
    "彿浠婃棩澶定澶ц穼瓒嬪娍涓婃定涓嬭穼瓒呭崠瓒呬拱鏈杩戝洖娴嬭鎸囨爣鏁板€煎"
    "垽鏂敮鍘嬪姏绂诲帇鍔涜祫閲戞祦鍚戝ぇ鎴峰姣斿彿鎸佷粨寤鸿绌轰粨缁撹鏄庢樉"
    "娴佸叆鍑哄ぉ瓒呭競鍨冮噺鐜伴樁鐩堜环鎹熶环鏂俊鍙峰搧鐗岃矾馃鎵撳垎"
)


def is_cjk(ch: str) -> bool:
    return CYRILLIC_ISH[0] <= ch <= CYRILLIC_ISH[1]


def runs_of_non_ascii(line: str) -> list[str]:
    """把一行切成若干「连续非 ASCII 字符」片段。"""
    runs, buf = [], []
    for ch in line:
        if ord(ch) > 127:
            buf.append(ch)
        else:
            if buf:
                runs.append("".join(buf))
                buf = []
    if buf:
        runs.append("".join(buf))
    return runs


def restore(candidate: str) -> str | None:
    """尝试把「伪中文」还原：GBK 字节 -> UTF-8 解码。用 strict 模式以保证精度。

    真实中文经 GBK 编码后按 UTF-8 解码几乎必然抛错；而二次编码产生的乱码
    本身就是真实中文的 UTF-8 字节，所以能严格还原。这就是判据。
    """
    try:
        return candidate.encode("gbk", "strict").decode("utf-8", "strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None


def check_file(path: Path, all_types: bool) -> tuple[list[str], list[str], list[str], list[str]]:
    """返回 (错误, 严格可还原的乱码行, 中文比较行, 疑似乱码行)"""
    errors: list[str] = []
    mojibake: list[str] = []
    cjk_compare: list[str] = []
    suspicious: list[str] = []

    raw = path.read_bytes()
    for bom, name in BOMS.items():
        if raw.startswith(bom):
            errors.append(f"含 {name}（应存为无 BOM 的 UTF-8）")
            break
    else:
        if path.suffix == ".csv":
            pass  # CSV 允许 BOM（给 Excel 认中文用）

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        errors.append(f"不是合法 UTF-8（偏移 {e.start}: {e.reason}）—— 可能被存成了 GBK/ANSI")
        return errors, mojibake, cjk_compare, suspicious

    for i, line in enumerate(text.split("\n"), 1):
        flagged = False
        for run in runs_of_non_ascii(line):
            if sum(1 for c in run if is_cjk(c)) < 2:
                continue
            fixed = restore(run)
            if fixed and sum(1 for c in fixed if is_cjk(c)) >= 2:
                mojibake.append(f"L{i}: {run[:26]}…  =>  应为「{fixed[:26]}」")
                flagged = True
                break
        if not flagged:
            hits = [c for c in line if c in SUSPICIOUS_CHARS]
            if len(hits) >= 2:
                suspicious.append(f"L{i}: 命中乱码字 {''.join(hits[:8])}  ← {line.strip()[:60]}")
        if any(op in line for op in ("==", "!=")) or " in " in line:
            for q in ('"', "'"):
                parts = line.split(q)
                for j in range(1, len(parts), 2):
                    if any(is_cjk(c) for c in parts[j]):
                        cjk_compare.append(f"L{i}: {line.strip()[:88]}")
                        break
    return errors, mojibake, cjk_compare, suspicious


def main(argv: list[str]) -> int:
    all_types = "--all" in argv
    targets = [a for a in argv[1:] if not a.startswith("--")]
    root = Path(__file__).resolve().parent.parent
    if targets:
        files = [Path(t) for t in targets]
    else:
        globs = ["*.py"] + (["*.md", "*.json", "*.bat"] if all_types else [])
        files = sorted({p for g in globs for p in root.glob(g)})

    failed = False
    for p in files:
        errors, mojibake, cjk_compare, suspicious = check_file(p, all_types)
        if not (errors or mojibake or cjk_compare or suspicious):
            continue
        print(f"\n{'=' * 78}\n{p.relative_to(root) if str(p).startswith(str(root)) else p}")
        if errors:
            failed = True
            for e in errors:
                print(f"  [错误] {e}")
        if mojibake:
            failed = True
            print(f"  [错误] 二次编码乱码（严格可还原）{len(mojibake)} 行：")
            for m in mojibake:
                print(f"         {m}")
        if suspicious:
            failed = True
            print(f"  [错误] 疑似乱码 {len(suspicious)} 行（含 GBK 单字节字符，无法严格还原，需人工确认）：")
            for s in suspicious:
                print(f"         {s}")
        if cjk_compare:
            print(f"  [提示] 参与逻辑判断的中文字面量 {len(cjk_compare)} 行（请人工核对两侧来源一致）：")
            for c in cjk_compare:
                print(f"         {c}")

    print(f"\n{'-' * 78}")
    if failed:
        print("结果：发现编码问题 —— 请修复后再提交")
        return 1
    print("结果：未发现编码问题 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
