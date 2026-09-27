import re
with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
# 修所有f-string里变量前面缺{的
c = re.sub(r'([^\{])take_profit\}', r'\1{take_profit}', c)
c = re.sub(r'([^\{])stop_loss\}', r'\1{stop_loss}', c)
c = re.sub(r'([^\{])b_score\}', r'\1{b_score}', c)
c = re.sub(r'([^\{])s_score\}', r'\1{s_score}', c)
c = re.sub(r'([^\{])space\}', r'\1{space}', c)
c = re.sub(r'([^\{])flow_judge\}', r'\1{flow_judge}', c)
c = re.sub(r'([^\{])daily_judge\}', r'\1{daily_judge}', c)
c = re.sub(r'([^\{])pos\}', r'\1{pos}', c)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print("批量修完了")
