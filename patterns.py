"""PDF脱敏工具 — 敏感数据正则表达式和检测规则"""

import re
import json
from pathlib import Path
from collections import namedtuple

# ---- 检测结果数据结构 ----

DetectionResult = namedtuple("DetectionResult", [
    "page_num",       # int, 0-indexed
    "pattern_type",   # str, 如 "身份证号" "手机号" "患者姓名"
    "matched_text",   # str, 匹配到的文本
    "rects",          # list[fitz.Rect]
])

FileDetectionSummary = namedtuple("FileDetectionSummary", [
    "filename",       # str
    "total_pages",    # int
    "detections",     # list[DetectionResult]
])

# ---- 配置加载 ----

def _load_config() -> dict:
    """加载 config.json 中的自定义标签。"""
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}

_config = _load_config()

# ---- Tier 1: 高精度模式匹配 ----

ID_CARD = re.compile(r'\b[1-9]\d{16}[\dXx]\b')
PHONE = re.compile(r'\b1[3-9]\d{9}\b')
LANDLINE = re.compile(r'\b0\d{2,3}[-\s]?\d{7,8}\b')
EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
LONG_DIGITS = re.compile(r'\b\d{16,19}\b')

# ---- Tier 2: 标签前缀匹配 ----

def _build_patient_name_pattern() -> re.Pattern:
    labels = _config.get("patient_name_labels", [])
    labels.append(r'姓\s*名')  # 兼容空格变体"姓  名"
    labels = [re.escape(l) if '\\' not in l else l for l in labels if l.strip()]
    return re.compile(r'(?:' + '|'.join(labels) + r')[：:，,\s]*([一-鿿]{2,3})')

def _build_doctor_name_pattern() -> re.Pattern:
    labels = _config.get("doctor_name_labels", [])
    labels = [re.escape(l) for l in labels if l.strip()]
    return re.compile(r'(?:' + '|'.join(labels) + r')[：:，,\s]*([一-鿿]{2,3})')

def _build_address_pattern() -> re.Pattern:
    labels = _config.get("address_labels", [])
    labels = [re.escape(l) for l in labels if l.strip()]
    return re.compile(
        r'(?:' + '|'.join(labels) + r')[：:，,\s]*'
        r'([^\s\-].{1,79}?)(?:$|。|；|\s*(?:电话|邮编|单位电话)\b)',
        re.DOTALL
    )

def _build_medical_record_pattern() -> re.Pattern:
    labels = _config.get("medical_record_labels", [])
    labels = [re.escape(l) for l in labels if l.strip()]
    return re.compile(
        r'(?:' + '|'.join(labels) + r')[：:，,\s]+'
        r'([A-Za-z0-9\-/_]+)',
        re.IGNORECASE
    )

def _build_sensitive_words_pattern() -> re.Pattern | None:
    words = _config.get("sensitive_words", [])
    words = [re.escape(w) for w in words if w.strip()]
    if not words:
        return None
    return re.compile('|'.join(words))

PATIENT_NAME = _build_patient_name_pattern()
DOCTOR_NURSE_NAME = _build_doctor_name_pattern()
ADDRESS = _build_address_pattern()
MEDICAL_RECORD = _build_medical_record_pattern()
SENSITIVE_WORDS = _build_sensitive_words_pattern()

INSTITUTION_NAME = re.compile(
    r'医疗机构([一-鿿]{4,30}(?:医院|卫生院|医疗中心|妇幼保健院|社区卫生服务中心))'
)

# ---- OCR识别到的"名字"黑名单 ----

_NAME_BLACKLIST = {
    '主治', '住院', '主任', '医师', '护士', '性别', '年龄', '出生',
    '入院', '出院', '科室', '诊断', '手术', '检查', '治疗', '药物',
    '门诊', '急诊', '病历', '病理', '质控', '编码', '实习', '进修',
    '日期', '电话', '地址', '联系人', '尸检', '今日', '昨日', '仍有',
    '情况', '报告', '签名', '记录', '首页', '病案', '麻醉', '损伤',
    '中毒', '查房', '病程', '护理', '体温', '脉搏', '呼吸', '血压',
    '血糖', '用药', '医嘱', '转科', '会诊', '过敏', '主诉', '现病史',
    '既往史', '个人史', '家族史', '体格检查', '辅助检查', '初步诊断',
    '入院诊断', '出院诊断', '过敏药物', '死亡', '患者', '家属',
    '新生儿', '出生体重', '月龄', '国籍', '民族', '职业', '婚姻',
    '联系人电话', '入院时间', '出院时间', '入院科别', '出院科别',
    '实际住院', '门急', '西医', '疾病编码', '病理号',
    '入院病情', '有临床', '单病种', '医疗', '付费', '方式',
    '下]', '思j', '册唱', '灿式', '方纺', '保码', '皇上', 'mit',
    '名性', '胆源', '型及', '及类', '轻经', '症六', '子厘', '修册',
    '局攻', '局二', '质拉', '十欧', '天签', '庆迷', '军迷',
    '氏迷', '仍迷', '数迷', '签科', '签的', '名科', '房记', '房后',
    '记录', '首次', '日常', '特殊', '出院小结', '入院记录',
    '术前', '发言', '保证', '讲明', '陈述', '交接', '共同', '确认',
    '处理', '根据', '明确', '记录', '告知', '同意', '说明', '注意',
    '观察', '继续', '给予', '考虑', '建议', '可能', '需要', '已经',
    '目前', '进一步', '必要时', '定期', '随访', '复查', '入院病情',
    '质质近', '质近', '了多', '二钊', '基', '讽基', '风术', '色侯',
    '色吴', '了和', '于厘', '匕峭', '并了',
    '姓名',
}

# ---- 已脱敏标记 ----

MASKED_MARKER = re.compile(r'[★*×X□■]{3,}')

# ---- 主模式列表 ----

_PATTERNS: list[tuple[str, re.Pattern, bool]] = [
    ("身份证号", ID_CARD, True),
    ("手机号", PHONE, True),
    ("固定电话", LANDLINE, True),
    ("邮箱", EMAIL, True),
    ("长数字串", LONG_DIGITS, True),
    ("患者姓名", PATIENT_NAME, False),
    ("医生护士", DOCTOR_NURSE_NAME, False),
    ("地址", ADDRESS, False),
    ("病历号", MEDICAL_RECORD, False),
    ("医疗机构", INSTITUTION_NAME, False),
]
if SENSITIVE_WORDS:
    _PATTERNS.append(("敏感词", SENSITIVE_WORDS, True))

PATTERN_LIST: list[tuple[str, re.Pattern, bool]] = _PATTERNS

# ---- 排除逻辑 ----

HOSPITAL_KEYWORDS = [
    '医院', '卫生院', '卫生所', '医疗中心', '妇幼保健',
    '保健院', '诊所', '门诊部', '社区卫生', '疾控中心',
]

DEPARTMENT_KEYWORDS = [
    '科室', '病区', '诊室', '手术室', '监护室', '急救中心', '康复中心',
]


def is_hospital_or_department(text: str) -> bool:
    for kw in HOSPITAL_KEYWORDS:
        if kw in text:
            return True
    for kw in DEPARTMENT_KEYWORDS:
        if kw in text:
            return True
    return False


def is_invalid_name(name: str) -> bool:
    """检查OCR识别到的名字是否在黑名单中（非人名）。"""
    stripped = name.strip()
    if stripped in _NAME_BLACKLIST:
        return True
    for kw in _NAME_BLACKLIST:
        if len(kw) >= 2 and kw in stripped:
            return True
    if not any('一' <= c <= '鿿' for c in stripped):
        return True
    return False
