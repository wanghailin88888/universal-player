"""验证：复读幻觉抑制（实机症状：画面被几十条 "2940, 2940, 2940,…" 刷屏）。"""
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ai_subtitle import Segment, suppress_hallucination  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + detail) if detail else ""))
    if not cond:
        fails.append(name)


def S(t, s, e, prob=-0.5):
    return Segment(start=s, end=e, text=t, prob=prob)


# 1) 实机症状：解码循环吐出大量 "2940, 2940, 2940, …" 重叠段
flood = [S("2940, " * 8, 5.0 + i * 0.4, 6.0 + i * 0.4) for i in range(15)]
out = suppress_hallucination(flood)
print(f"  输入 {len(flood)} 条刷屏幻觉 → 输出 {len(out)} 条")
check("刷屏幻觉被清掉", len(out) <= 2, f"{len(out)} 条")
if out:
    check("残留单条也已被截断", ("2940, " * 3) not in out[0].text, repr(out[0].text[:60]))

# 2) 相邻整条复读（不同时间段重复同一句）只留一条
dup = [S("大家好，今天讲讲期权", 10.0, 12.0), S("大家好，今天讲讲期权", 12.5, 14.5),
       S("大家好，今天讲讲期权", 15.0, 17.0)]
out2 = suppress_hallucination(dup)
check("相邻整条复读只留一条", len(out2) == 1, f"{len(out2)} 条")

# 3) 正常内容必须原样保留
normal = [
    S("大家好，我是丁丁。", 0.0, 2.0),
    S("今天我们看上证指数的走势。", 2.5, 5.5),
    S("2940 这个位置是关键支撑。", 6.0, 9.0),      # 数字单独出现一次，不是复读
    S("好，我们看下一张图。", 9.5, 11.0),
]
out3 = suppress_hallucination(list(normal))
check("正常内容 4 条全保留", len(out3) == 4, f"{len(out3)} 条")
check("正常内容文本不被改写",
      [x.text for x in out3] == [x.text for x in normal],
      str([x.text[:12] for x in out3]))

# 4) 低置信度 + 高度重复 → 丢弃
junk = [S("对对 对对 对对 对对 对对", 20.0, 22.0, prob=-1.8),
        S("接下来讲讲风险控制。", 22.5, 24.0, prob=-0.4)]
out4 = suppress_hallucination(junk)
check("低置信复读被丢", len(out4) == 1 and "风险控制" in out4[0].text, f"{len(out4)} 条")

# 5) faster-whisper 支持 no_repeat_ngram_size（签名过滤后真正生效）
try:
    from faster_whisper import WhisperModel
    sig = inspect.signature(WhisperModel.transcribe)
    check("no_repeat_ngram_size 受支持",
          "no_repeat_ngram_size" in sig.parameters, str(
              "no_repeat_ngram_size" in sig.parameters))
except Exception as e:
    print("  (跳过签名检查)", e)

# 6) 实机症状 B：短语周期性复读（重复的是 2~4 词短语，不是单个词）
#    "…test the product of the product of the product of the product"
eng = S("Today is very good, we always come here to test the "
        "product of the product of the product of the product",
        0.5, 5.0)
out6 = suppress_hallucination([eng], expected_lang="zh")
print(f"  短语复读 + 中文片吐英文 → 剩 {len(out6)} 条: "
      + (out6[0].text[:50] if out6 else "(整条丢弃)"))
check("短语周期性复读被截断/丢弃", len(out6) == 0
      or out6[0].text.lower().count("product") <= 2,
      out6[0].text[:60] if out6 else "dropped")

# 7) 中文片吐整句英文（语言不匹配）→ 丢弃
en_only = [S("And then we will see the market in the next section", 3.0, 6.0),
           S("好，我们接着看大盘。", 6.5, 8.0)]
out7 = suppress_hallucination(en_only, expected_lang="zh")
check("中文片整句英文被丢", len(out7) == 1 and "大盘" in out7[0].text,
      f"{len(out7)} 条")
# 英文片（expected=auto/en）同样的内容不能被误杀
out7b = suppress_hallucination(list(en_only), expected_lang="")
check("英文片不被误杀", len(out7b) == 2, f"{len(out7b)} 条")

# 8) 已知幻觉句整条丢弃
bl = [S("Thank you for watching.", 1.0, 2.0),
      S("大家好，今天讲期权入门。", 2.5, 4.5)]
out8 = suppress_hallucination(bl, expected_lang="zh")
check("已知幻觉句被丢", len(out8) == 1 and "期权入门" in out8[0].text,
      f"{len(out8)} 条")

# 9) 正常中文里夹英文单词/品牌名不能被误杀
mix = [S("OK，我们今天讲 ETF 的估值方法。", 1.0, 3.0)]
out9 = suppress_hallucination(mix, expected_lang="zh")
check("中英混排正常保留", len(out9) == 1, f"{len(out9)} 条")

print("\n结论:", "ALL_PASS" if not fails else "FAIL -> " + ", ".join(fails))
sys.exit(0 if not fails else 1)
