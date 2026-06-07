import json
import difflib
import re
import random
from pathlib import Path
import streamlit as st

# =========================
# 常量
# =========================
PLACEHOLDER = "请选择一个选项…"

# =========================
# 读取题库（把题库放到 data/*.json）
# 每题建议字段：
# course, chapter, qtype, question, options, answer, explanation
# =========================
@st.cache_data(show_spinner=False)
def load_all_quiz():
    data_dir = Path(__file__).parent / "data"
    if not data_dir.exists():
        raise FileNotFoundError(f"未找到 data 目录：{data_dir}")

    all_items = []
    for p in sorted(data_dir.glob("*.json")):
        with open(p, "r", encoding="utf-8") as f:
            arr = json.load(f)
        if isinstance(arr, dict):
            # 兼容：如果某些导出是 {"data": [...]}
            arr = arr.get("data", [])
        if not isinstance(arr, list):
            continue
        for it in arr:
            if isinstance(it, dict):
                it["_src_file"] = p.name
                all_items.append(it)
    if not all_items:
        raise FileNotFoundError("data 目录下没有可用的题库 JSON（*.json）")
    return all_items


def get_course(it: dict) -> str:
    return (it.get("course") or "").strip() or "未命名课程"


def get_chapter(it: dict) -> str:
    ch = (it.get("chapter") or "").strip()
    return ch or "未分章"


def infer_qtype(it: dict) -> str:
    qt = (it.get("qtype") or "").strip()
    if qt:
        return qt
    opts = it.get("options") or []
    ans = it.get("answer")
    if opts and isinstance(ans, list):
        return "多选题"
    if opts:
        return "单选题"
    return "简答题"


def normalize_text(x) -> str:
    if x is None:
        return ""
    return str(x).strip()


def grade_subjective(user: str, standard: str) -> bool | None:
    """主观题：非常粗略的相似度判分，仅供自查。"""
    user = normalize_text(user)
    standard = normalize_text(standard)
    if not standard:
        return None
    if not user:
        return False
    ratio = difflib.SequenceMatcher(None, user, standard).ratio()
    return ratio >= 0.65


def ensure_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return [normalize_text(i) for i in x if normalize_text(i)]
    # 兼容：字符串 "ABD" 或 "A,B,D"
    s = normalize_text(x)
    # 如果看起来像字母答案，先按字母拆
    if all(c in "ABCDEFGH" for c in s.replace(",", "").replace(" ", "").upper()) and len(s) <= 10:
        letters = [c for c in s.upper() if c in "ABCDEFGH"]
        return letters
    # 否则按分隔符拆
    parts = [p.strip() for p in re.split(r"[，,、;\s]+", s) if p.strip()]
    return parts


# =========================
# Streamlit 单页应用
# =========================
st.set_page_config(page_title="刷题系统（课程/章节筛选）", layout="centered")
st.title("🩺 刷题 Web App（课程/章节筛选 + 单选/多选/简答）")

# ---- 先加载题库
try:
    all_quiz = load_all_quiz()
except Exception as e:
    st.error(f"题库加载失败：{e}")
    st.info("请确认仓库中存在 data 目录，且 data/*.json 已上传并提交到 GitHub。")
    st.stop()

# ---- 按课程分组
COURSE_MAP = {}
for it in all_quiz:
    COURSE_MAP.setdefault(get_course(it), []).append(it)

courses = sorted(COURSE_MAP.keys())

# =========================
# session_state（防刷新丢进度）
# =========================
if "current_index" not in st.session_state:
    st.session_state.current_index = 0
if "score" not in st.session_state:
    st.session_state.score = 0
if "submitted" not in st.session_state:
    st.session_state.submitted = False
if "last_is_correct" not in st.session_state:
    st.session_state.last_is_correct = None

# 为“不同课程+不同章节”保存独立进度
if "progress_map" not in st.session_state:
    st.session_state.progress_map = {}
if "active_state_key" not in st.session_state:
    st.session_state.active_state_key = None

# =========================
# 侧边栏：课程 / 章节 / 题型 筛选
# =========================
st.sidebar.header("📚 课程 / 章节 筛选")

course_name = st.sidebar.selectbox("选择课程", courses)
active_quiz = COURSE_MAP[course_name]

chapters = sorted({get_chapter(it) for it in active_quiz})
chapter_labels = ["全部"] + chapters
chosen_chapter = st.sidebar.selectbox("选择章节", chapter_labels)

qtype_labels = ["全部", "单选题", "多选题", "简答题"]
chosen_qtype = st.sidebar.selectbox("题型筛选", qtype_labels)

random_order = st.sidebar.checkbox("随机顺序刷题", value=False)


def passes_filter(it: dict) -> bool:
    if chosen_chapter != "全部" and get_chapter(it) != chosen_chapter:
        return False
    qt = infer_qtype(it)
    if chosen_qtype != "全部" and qt != chosen_qtype:
        return False
    return True


raw_filtered_indices = [idx for idx, it in enumerate(active_quiz) if passes_filter(it)]

# 当前筛选状态 key（决定“独立进度”）
state_key = f"{course_name}::{chosen_chapter}::{chosen_qtype}::random={random_order}"


def make_state_payload(key: str) -> dict:
    data = st.session_state.progress_map.get(key, {})
    payload = {
        "current_index": st.session_state.current_index,
        "score": st.session_state.score,
        "submitted": st.session_state.submitted,
        "last_is_correct": st.session_state.last_is_correct,
    }
    ordered_indices = data.get("ordered_indices")
    if ordered_indices is not None:
        payload["ordered_indices"] = ordered_indices
    return payload


def save_current_state():
    st.session_state.progress_map[state_key] = make_state_payload(state_key)


def load_state_for_key():
    data = st.session_state.progress_map.get(state_key)
    if not data:
        st.session_state.current_index = 0
        st.session_state.score = 0
        st.session_state.submitted = False
        st.session_state.last_is_correct = None
    else:
        st.session_state.current_index = int(data.get("current_index", 0))
        st.session_state.score = int(data.get("score", 0))
        st.session_state.submitted = bool(data.get("submitted", False))
        st.session_state.last_is_correct = data.get("last_is_correct", None)


# 如果切换了筛选条件：保存旧状态 → 载入新状态
if st.session_state.active_state_key != state_key:
    if st.session_state.active_state_key is not None:
        old_key = st.session_state.active_state_key
        st.session_state.progress_map[old_key] = make_state_payload(old_key)
    load_state_for_key()
    st.session_state.active_state_key = state_key

if random_order:
    state_data = st.session_state.progress_map.setdefault(state_key, {})
    ordered_indices = state_data.get("ordered_indices")
    if (
        ordered_indices is None
        or len(ordered_indices) != len(raw_filtered_indices)
        or set(ordered_indices) != set(raw_filtered_indices)
    ):
        ordered_indices = raw_filtered_indices[:]
        random.shuffle(ordered_indices)
        state_data["ordered_indices"] = ordered_indices
    filtered_indices = ordered_indices
else:
    filtered_indices = raw_filtered_indices

total = len(filtered_indices)

# ---- 侧边栏：信息与重置
st.sidebar.markdown("---")
st.sidebar.write(f"当前题量：**{total}**")
st.sidebar.write(f"当前得分：**{st.session_state.score}**")
st.sidebar.write(f"当前进度：**{min(st.session_state.current_index, total)}/{total}**")

if random_order and st.sidebar.button("🎲 重新随机当前题序"):
    ordered_indices = raw_filtered_indices[:]
    random.shuffle(ordered_indices)
    st.session_state.progress_map[state_key] = {
        "current_index": 0,
        "score": 0,
        "submitted": False,
        "last_is_correct": None,
        "ordered_indices": ordered_indices,
    }
    load_state_for_key()
    st.session_state.active_state_key = state_key
    st.rerun()

if st.sidebar.button("🔄 重置当前筛选进度"):
    ordered_indices = st.session_state.progress_map.get(state_key, {}).get("ordered_indices")
    st.session_state.progress_map[state_key] = {
        "current_index": 0,
        "score": 0,
        "submitted": False,
        "last_is_correct": None,
    }
    if ordered_indices is not None:
        st.session_state.progress_map[state_key]["ordered_indices"] = ordered_indices
    load_state_for_key()
    st.session_state.active_state_key = state_key
    st.rerun()

# ---- 没题直接提示
if total == 0:
    st.warning("该筛选条件下暂无题目。请在左侧切换课程/章节/题型。")
    st.stop()

# ---- 进度条
progress = st.session_state.current_index / total
st.progress(progress)

# =========================
# 结算页
# =========================
if st.session_state.current_index >= total:
    st.success(f"✅ 已完成当前筛选！得分：{st.session_state.score} / {total}")
    st.progress(1.0)
    if st.button("🔄 重新开始（当前筛选）", type="primary"):
        st.session_state.current_index = 0
        st.session_state.score = 0
        st.session_state.submitted = False
        st.session_state.last_is_correct = None
        save_current_state()
        st.rerun()
    st.stop()

# =========================
# 当前题
# =========================
pos = st.session_state.current_index
global_idx = filtered_indices[pos]
q = active_quiz[global_idx]

chapter = get_chapter(q)
qtype = infer_qtype(q)

st.subheader(f"第 {pos + 1} / {total} 题")
st.caption(f"课程：{course_name}  |  章节：{chapter}  |  题型：{qtype}")
st.write(q.get("question", ""))

disabled = bool(st.session_state.submitted)

# 为每题生成稳定 widget key（避免 “不能修改 session_state” 报错）
widget_key = f"ans::{course_name}::{global_idx}"

user_answer = None

# -------------------------
# 单选题
# -------------------------
if qtype == "单选题":
    opts = [PLACEHOLDER] + (q.get("options") or [])
    if widget_key not in st.session_state:
        st.session_state[widget_key] = PLACEHOLDER

    user_answer = st.radio(
        "请选择一个选项：",
        options=opts,
        index=opts.index(st.session_state[widget_key]) if st.session_state[widget_key] in opts else 0,
        key=widget_key,
        disabled=disabled,
    )

# -------------------------
# 多选题（关键：用 multiselect）
# -------------------------
elif qtype == "多选题":
    opts = q.get("options") or []
    if widget_key not in st.session_state:
        st.session_state[widget_key] = []

    user_answer = st.multiselect(
        "请选择所有正确选项：",
        options=opts,
        default=st.session_state[widget_key] if isinstance(st.session_state[widget_key], list) else [],
        key=widget_key,
        disabled=disabled,
    )

# -------------------------
# 简答/主观题
# -------------------------
else:
    if widget_key not in st.session_state:
        st.session_state[widget_key] = ""

    user_answer = st.text_area("请输入你的答案：", key=widget_key, height=140, disabled=disabled)

# =========================
# 提交答案
# =========================
if not st.session_state.submitted:
    if st.button("✅ 提交答案", type="primary"):
        correct = None

        if qtype == "单选题":
            if user_answer == PLACEHOLDER:
                st.warning("请先选择一个选项再提交。")
                st.stop()

            ans = q.get("answer")
            if not ans:
                correct = None
            else:
                correct = (normalize_text(user_answer) == normalize_text(ans))

        elif qtype == "多选题":
            if not user_answer:
                st.warning("请至少选择 1 个选项再提交。")
                st.stop()

            ans = q.get("answer")
            if not ans:
                correct = None
            else:
                correct_set = set(map(normalize_text, ans)) if isinstance(ans, list) else set(map(normalize_text, ensure_list(ans)))
                user_set = set(map(normalize_text, user_answer))
                correct = (user_set == correct_set)

        else:
            correct = grade_subjective(user_answer, q.get("answer", ""))

        st.session_state.submitted = True
        st.session_state.last_is_correct = correct

        if correct is True:
            st.session_state.score += 1

        save_current_state()
        st.rerun()

# =========================
# 提交后：反馈 + 解析 + 下一题
# =========================
if st.session_state.submitted:
    correct = st.session_state.last_is_correct

    if correct is True:
        st.success("回答正确 ✅")
    elif correct is False:
        if qtype == "单选题":
            st.error(f"回答错误 ❌，正确答案是：{q.get('answer', '（暂无答案）')}")
        elif qtype == "多选题":
            ans = q.get("answer", [])
            if isinstance(ans, list):
                st.error("回答错误 ❌，正确答案是：\n- " + "\n- ".join(ans) if ans else "回答错误 ❌（暂无答案）")
            else:
                st.error(f"回答错误 ❌，正确答案是：{ans}")
        else:
            st.error("未匹配到标准答案（主观题为粗略判定，仅供自查）❌")
    else:
        st.warning("本题暂无可自动判定的标准答案，未计分。")

    with st.expander("📌 查看解析 / 参考答案", expanded=True):
        st.info(q.get("explanation", "（暂无解析）"))

    if st.button("➡️ 下一题"):
        st.session_state.current_index += 1
        st.session_state.submitted = False
        st.session_state.last_is_correct = None
        save_current_state()
        st.rerun()

st.divider()
st.caption("钱靖 • 刷题系统（支持课程/章节筛选）")
