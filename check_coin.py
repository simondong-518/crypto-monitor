"""单币快查（P1-7：直接复用 check_all_alerts 的同一份自检代码，不再各算一套）。

    <python> check_coin.py SUI_USDT

历史问题：原版自己复制了一份打分逻辑，并且用「1.5 倍平均量」而 main.py 用「1.2 倍」，
两个脚本对同一件事给出不同答案。
"""
import sys

from check_all_alerts import show
from config import LS_HISTORY_FILE
from ls_percentile import LSPercentile

if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else "SUI_USDT"
    show(pair, LSPercentile(LS_HISTORY_FILE))
