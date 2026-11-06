"""Conservative spoken-text rules; preserve sources and persist pronunciation."""
import re

RULES_VERSION = 'speech-rules-1'
_digits = '零一二三四五六七八九'


def number(value):
    if '.' in value:
        left, right = value.split('.', 1)
        return number(left) + '点' + ''.join(_digits[int(n)] for n in right)
    if len(value) > 4 or value.startswith('0'):
        return ''.join(_digits[int(n)] for n in value)
    n = int(value)
    if not n:
        return '零'
    result, zero = '', False
    for unit, label in ((1000, '千'), (100, '百'), (10, '十'), (1, '')):
        d, n = divmod(n, unit)
        if d:
            if zero:
                result += '零'
            result += ('' if d == 1 and unit == 10 and not result else _digits[d]) + label
            zero = False
        elif result and n:
            zero = True
    return result


def clean(text):
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[\^?\d+\]|【[^】]*】|\[cite:[^\]]*\]', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'(?m)^\s*[#>]+\s*', '', text)
    return re.sub(r'[`*_~]', '', text).strip()


def pronounce(text, dictionary=None, language='zh'):
    text = clean(text)
    dictionary = dictionary or {}
    for term in sorted(dictionary, key=len, reverse=True):
        if not term or len(term) > 100 or not dictionary[term].strip() or len(dictionary[term]) > 200:
            raise ValueError('发音词典词条须为1～100字符，读法须为1～200字符')
    # Placeholder substitutions keep explicitly chosen readings intact.
    replacements = []
    def replace(match):
        replacements.append(dictionary[match.group(0)])
        return chr(0xE000 + len(replacements) - 1)
    if dictionary:
        text = re.sub('|'.join(re.escape(k) for k in sorted(dictionary, key=len, reverse=True)), replace, text)
    if language == 'zh':
        text = re.sub(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?',
                      lambda m: ''.join(_digits[int(d)] for d in m[1]) + '年' + number(m[2]) + '月' + number(m[3]) + '日', text)
        text = re.sub(r'(\d+(?:\.\d+)?)\s*%', lambda m: '百分之' + number(m[1]), text)
        # Model identifiers use digit-by-digit readings, distinct from quantities.
        text = re.sub(r'(?<=[A-Za-z-])\d+(?:\.\d+)?', lambda m: ' '.join(_digits[int(d)] if d.isdigit() else '点' for d in m[0]), text)
        text = re.sub(r'\d+(?:\.\d+)?', lambda m: number(m[0]), text)
        for unit, reading in {'GHz':'吉赫兹','MHz':'兆赫兹','GB':'吉字节','MB':'兆字节','kg':'千克','km':'千米'}.items():
            text = text.replace(unit,reading)
        text = re.sub(r'\b[A-Z]{2,8}\b', lambda m: ' '.join(m[0]), text)
    for i, reading in enumerate(replacements):
        text = text.replace(chr(0xE000 + i), reading)
    return text


def review(doc):
    issues = []
    if not doc.paragraphs:
        issues.append({'severity': 'blocker', 'message': '口播稿为空'})
    seen = set()
    for p in doc.paragraphs:
        if not p.speech_text.strip():
            issues.append({'paragraph_id': p.id, 'severity': 'blocker', 'message': '发音文本为空'})
        if not p.source_block_ids and not p.citations:
            issues.append({'paragraph_id': p.id, 'severity': 'warn', 'message': '未关联事实来源，请人工核对'})
        if p.text in seen:
            issues.append({'paragraph_id': p.id, 'severity': 'warn', 'message': '重复段落'})
        seen.add(p.text)
        if re.search(r'[A-Za-z]{2,}|\d', p.speech_text):
            issues.append({'paragraph_id': p.id, 'severity': 'warn', 'message': '专名、英文或数字读法需试听核对'})
        if any(len(sentence) > 100 for sentence in re.split(r'[。！？.!?]', p.text)):
            issues.append({'paragraph_id': p.id, 'severity': 'warn', 'message': '句子较长，建议缩短并检查节奏'})
    return {'kind': 'rules', 'human_approval': False, 'issues': issues,
            'planning_seconds': round(sum(len(p.speech_text) for p in doc.paragraphs) / 4),
            'actual_duration': None, 'fact_check': '需对照来源人工确认'}
