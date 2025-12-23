import json
import re
from pathlib import Path

import streamlit as st


# =========================
# Config
# =========================
st.set_page_config(page_title="刷题 Web App", layout="centered")


# =========================
# Load quiz bank (NO questions inside app.py)
# =========================
@st.cache_data
def load_quiz_data():
    base = Path(__file__).parent
    data_dir = base / "data"
    files = sorted(data_dir.glob("quiz_*.json"))

    if not data_dir.exists():
        raise FileNotFoundError("未找到 data/ 文件夹。请在仓库根目录创建 data/ 并上传 quiz_*.json 题库文件。")
    if not files:
        raise FileNotFoundError("data/ 下未找到 quiz_*.json 题库文件。请上传题库 JSON。")

    all_q = []
    for f in files:
        try:
            items = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(items, list):
                continue
            # 记录来源文件名，方便排查
            for it in items:
                if isinstance(it, dict):
                    it.setdefault("_source", f.name)
                    all_q.append(it)
        except Exception:
            # 某个 JSON 格式坏了，不让全站崩；同时给提示
            all_q.append({
                "course": "题库错误",
                "chapter": "请检查 JSON",
                "qtype": "单选题",
                "question": f"题库文件 {f.name} 无法解析（JSON 格式错误）。",
                "options": ["请修复该 JSON 文件后重试。"],
                "answer": "请修复该 JSON 文件后重试。",
                "explanation": "请检查逗号、引号、括号是否完整；确保整个文件是一个 list[dict]。",
                "_source": f.name,
            })

    return all_q


quiz_data = load_quiz_data()


# =========================
# Helpers
# =========================
def resolve_course(q: dict) -> str:
    return str(q.get("course", "未分类")).strip() or "未分类"


def resolve_chapter(q: dict) -> str:
    ch = q.get("chapter", None)
    if ch is not None and str(ch).strip():
        return str(ch).strip()

    # 兜底：从题干解析【第X章】
    text = str(q.get("question", ""))
    m = re.search(r"【\s*第\s*(\d+)\s*章\s*】", text)
    if m:
        return f"第{m.group(1)}章"
    return "未分章"


def resolve_qtype(q: dict) -> str:
    qt = q.get("qtype")
    if qt and str(qt).strip():
        return str(qt).strip()

    # 兜底：有 options 视作选择题，否则简答
    opts = q.get("options") or []
    return "单选题" if opts else "简答题"


def normalize_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", "", s)
    s = s.replace("；", ";").replace("，", ",").replace("。", "")
    s = s.replace("（", "(").replace("）", ")")
    return s


def grade_subjective(user: str, answer: str):
    """主观题：仅做非常宽松的自测判定；无答案则返回 None（不计分）。"""
    if not answer or "暂无" in str(answer):
        return None

    u = normalize_text(user)
    a = normalize_text(str(answer))
    if not u:
        return False
    if u == a:
        return True

    # 关键词覆盖（答案按分隔符拆分，命中 >=80% 认为正确）
    raw = str(answer)
    parts = [p.strip() for p in re.split(r"[;,\s，、]+", raw) if p.strip()]
    parts = [p for p in parts if len(p) >= 2 and "暂无" not in p]
    if parts:
        hit = sum(1 for p in parts if normalize_text(p) in u)
        if hit / len(parts) >= 0.8:
            return True
    return False


# =========================
# Session State (critical)
# =========================
def init_state():
    st.session_state.setdefault("current_index", 0)
    st.session_state.setdefault("score", 0)
    st.session_state.setdefault("submitted", False)
    st.session_state.setdefault("last_is_correct", None)

    # 按筛选维度保存进度（防刷新/切换丢失）
    st.session_state.setdefault("progress_map", {})
    st.session_state.setdefault("active_state_key", None)


def save_state(state_key: str):
    st.session_state.progress_map[state_key] = {
        "current_index": st.session_state.current_index,
        "score": st.session_state.score,
        "submitted": st.session_state.submitted,
        "last_is_correct": st.session_state.last_is_correct,
    }


def load_state(state_key: str):
    data = st.session_state.progress_map.get(state_key)
    if not data:
        st.session_state.current_index = 0
        st.session_state.score = 0
        st.session_state.submitted = False
        st.session_state.last_is_correct = None
    else:
        st.session_state.current_index = data.get("current_index", 0)
        st.session_state.score = data.get("score", 0)
        st.session_state.submitted = data.get("submitted", False)
        st.session_state.last_is_correct = data.get("last_is_correct", None)


init_state()


# =========================
# UI: Sidebar filters
# =========================
st.title("🧠 单页刷题 Web App（JSON题库版）")

st.sidebar.header("📚 筛选")

all_courses = sorted({resolve_course(q) for q in quiz_data})
selected_course = st.sidebar.selectbox("选择课程", ["全部"] + all_courses, key="course_sel")

# chapters depend on course
chapters = sorted({
    resolve_chapter(q)
    for q in quiz_data
    if selected_course == "全部" or resolve_course(q) == selected_course
})
selected_chapter = st.sidebar.selectbox("选择章节", ["全部"] + chapters, key="chapter_sel")

# qtypes depend on course+chapter
qtypes = sorted({
    resolve_qtype(q)
    for q in quiz_data
    if (selected_course == "全部" or resolve_course(q) == selected_course)
    and (selected_chapter == "全部" or resolve_chapter(q) == selected_chapter)
})
selected_qtype = st.sidebar.selectbox("选择题型", ["全部"] + qtypes, key="qtype_sel")

# Filtered list
filtered = [
    q for q in quiz_data
    if (selected_course == "全部" or resolve_course(q) == selected_course)
    and (selected_chapter == "全部" or resolve_chapter(q) == selected_chapter)
    and (selected_qtype == "全部" or resolve_qtype(q) == selected_qtype)
]

total = len(filtered)

# state key depends on filters (so each filter set has its own progress)
state_key = f"{selected_course}::{selected_chapter}::{selected_qtype}"

# if switching filter set, save old and load new
if st.session_state.active_state_key != state_key:
    if st.session_state.active_state_key is not None:
        save_state(st.session_state.active_state_key)
    load_state(state_key)
    st.session_state.active_state_key = state_key

st.sidebar.markdown("---")
st.sidebar.write(f"筛选后题量：**{total}**")
st.sidebar.write(f"当前得分：**{st.session_state.score}**")
st.sidebar.write(f"当前进度：**{min(st.session_state.current_index, total)}/{total}**")

if st.sidebar.button("🔄 重置当前筛选进度"):
    st.session_state.progress_map[state_key] = {
        "current_index": 0, "score": 0, "submitted": False, "last_is_correct": None
    }
    load_state(state_key)
    st.session_state.active_state_key = state_key
    st.rerun()

# No questions
if total == 0:
    st.warning("当前筛选条件下没有题目。请在左侧切换课程/章节/题型。")
    st.stop()


# =========================
# Progress bar
# =========================
progress = st.session_state.current_index / total if total else 0.0
st.progress(progress)


# =========================
# Finish page
# =========================
if st.session_state.current_index >= total:
    st.success(f"✅ 已完成本筛选范围全部题目！总分：{st.session_state.score} / {total}")
    st.progress(1.0)

    if st.button("🔄 重新开始（本筛选）", type="primary"):
        st.session_state.current_index = 0
        st.session_state.score = 0
        st.session_state.submitted = False
        st.session_state.last_is_correct = None
        save_state(state_key)
        st.rerun()

    st.stop()


# =========================
# Current question
# =========================
pos = st.session_state.current_index
q = filtered[pos]

course = resolve_course(q)
chapter = resolve_chapter(q)
qtype = resolve_qtype(q)

st.subheader(f"第 {pos + 1} / {total} 题")
st.caption(f"课程：{course}｜章节：{chapter}｜题型：{qtype}")
st.write(q.get("question", "（无题干）"))

options = q.get("options") or []
answer = q.get("answer", None)
explanation = q.get("explanation", "")

disabled = bool(st.session_state.submitted)

# Per-question widget key (critical to avoid session_state conflicts)
widget_key = f"ans::{state_key}::{pos}"

user_answer = None

# =========================
# Render input widgets
# =========================
if qtype == "单选题":
    # ✅ no placeholder, use index=None
    user_answer = st.radio(
        "请选择一个选项：",
        options=options,
        index=None,
        key=widget_key,
        disabled=disabled,
    )

elif qtype == "多选题":
    if widget_key not in st.session_state:
        st.session_state[widget_key] = []
    user_answer = st.multiselect(
        "请选择一个或多个选项：",
        options=options,
        key=widget_key,
        disabled=disabled,
    )

else:
    if widget_key not in st.session_state:
        st.session_state[widget_key] = ""
    if qtype in ("填空题", "名词解释"):
        user_answer = st.text_input("请输入你的答案：", key=widget_key, disabled=disabled)
    else:
        user_answer = st.text_area("请输入你的答案：", key=widget_key, height=120, disabled=disabled)


# =========================
# Submit
# =========================
if not st.session_state.submitted:
    if st.button("✅ 提交答案", type="primary"):
        correct = None

        if qtype == "单选题":
            if user_answer is None:
                st.warning("请先选择一个选项再提交。")
                st.stop()
            if isinstance(answer, str) and answer.strip():
                correct = (user_answer == answer)
            else:
                correct = None

        elif qtype == "多选题":
            if not user_answer:
                st.warning("请至少选择一个选项再提交。")
                st.stop()

            if isinstance(answer, list):
                correct = (set(user_answer) == set(answer))
            else:
                # 兜底：如果答案是字符串，按分隔符拆分
                if isinstance(answer, str) and answer.strip():
                    parts = [p.strip() for p in re.split(r"[;,\s，、]+", answer) if p.strip()]
                    correct = (set(user_answer) == set(parts))
                else:
                    correct = None

        else:
            correct = grade_subjective(str(user_answer), str(answer) if answer is not None else "")

        st.session_state.submitted = True
        st.session_state.last_is_correct = correct

        if correct is True:
            st.session_state.score += 1

        save_state(state_key)
        st.rerun()


# =========================
# After submit: feedback / explanation / next
# =========================
if st.session_state.submitted:
    correct = st.session_state.last_is_correct

    if correct is True:
        st.success("回答正确 ✅")
    elif correct is False:
        # choice questions show the correct answer
        if qtype in ("单选题", "多选题"):
            st.error(f"回答错误 ❌，正确答案是：{answer if answer is not None else '（暂无答案）'}")
        else:
            st.error("未匹配到标准答案（主观题为粗略判定，仅供自查）❌")
    else:
        st.warning("本题暂无可自动判定的标准答案，未计分。")

    with st.expander("📌 查看解析 / 参考答案", expanded=True):
        st.write("**参考答案：**", answer if answer is not None else "（暂无答案）")
        if explanation:
            st.write("**解析：**")
            st.write(explanation)
        else:
            st.info("（暂无解析）")

        # debug info (optional): show source file
        st.caption(f"来源题库：{q.get('_source', 'unknown')}")

    if st.button("➡️ 下一题"):
        st.session_state.current_index += 1
        st.session_state.submitted = False
        st.session_state.last_is_correct = None
        save_state(state_key)
        st.rerun()


st.divider()
st.caption("© 钱靖 • 单页刷题（JSON题库）")
