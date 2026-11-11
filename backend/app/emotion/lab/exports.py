import csv
from html import escape
from io import StringIO
import json

from backend.app.emotion.lab.metrics import EMOTIONS, NAMES, SOURCES
from backend.app.emotion.lab.service import get_report
from backend.app.repositories.classroom import audit
from backend.app.repositories.database import connect
from backend.app.services.reports import safe_csv_cell

SOURCE_NAMES = {'MANUAL': '学生主动反馈', 'AI': 'AI 识别记录'}
SECTION_NAMES = {
    'FINDING': '关键发现',
    'CONTEXT': '课堂背景',
    'LIMITATION': '阅读说明',
    'NEXT_STEP': '后续行动',
}


def percentage(value):
    return '无数据' if value is None else f'{value * 100:.1f}%'


def cell(value):
    return escape('' if value is None else str(value), quote=True)


def table(headers, values):
    head = ''.join(f'<th scope="col">{cell(value)}</th>' for value in headers)
    body = ''.join(
        '<tr>' + ''.join(f'<td>{cell(value)}</td>' for value in row) + '</tr>'
        for row in values
    )
    return f'<div class="table-scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def csv_report(report):
    data = report['result']
    buffer = StringIO(newline='')
    writer = csv.writer(buffer)

    def row(*values):
        writer.writerow([safe_csv_cell(value) for value in values])

    row('课堂情绪分析实验室', report['title'])
    row('报告编号', report['id'], '方案编号', report['study_id'])
    row('快照指纹', report['fingerprint'])
    row('引擎版本', data['engine_version'], '数据采集快照', data['captured_at'])
    row('记录截止时间（不含这一刻）', data['recorded_before'])
    row('统计单位', data['methodology']['unit'])
    row('研究问题', report['definition']['question'])
    row('教师结论', report['conclusion'])
    row('复核状态', report['status'])
    row('方案参数', json.dumps(data['settings'], ensure_ascii=False, sort_keys=True))
    row('课堂数', data['summary']['session_count'], '记录数', data['summary']['total_records'])
    row('演示记录', data['summary']['demo_records'])
    row('课堂', '班级', '开始时间', '来源', '记录数', '关注类别记录数', '关注占比', '样本充足')
    for item in data['sessions']:
        session = item['session']
        for source in SOURCES:
            metric = item['sources'][source]
            row(
                session['course_name'], session['class_name'], session['starts_at'], SOURCE_NAMES[source],
                metric['total'], metric['concern_count'], metric['concern_ratio'], metric['sample_sufficient'],
            )
    row('来源', '情绪', '汇总记录数', '汇总占比')
    for source in SOURCES:
        metric = data['sources'][source]['pooled']
        for emotion in EMOTIONS:
            row(SOURCE_NAMES[source], NAMES[emotion], metric['counts'][emotion], metric['shares'][emotion])
    row('来源', '课堂等权关注占比', '汇总关注占比', '纳入课堂', '空白课堂')
    for source in SOURCES:
        metric = data['sources'][source]
        row(
            SOURCE_NAMES[source], metric['equal_weight_concern_ratio'], metric['pooled']['concern_ratio'],
            metric['eligible_sessions'], metric['empty_sessions'],
        )
    row('分组来源', '基准课堂数', '比较课堂数', '等权差异百分点', '比较状态')
    for comparison in data['groups']:
        row(
            SOURCE_NAMES[comparison['source']], comparison['baseline']['eligible_sessions'],
            comparison['comparison']['eligible_sessions'], comparison['equal_weight_change_pp'], comparison['status'],
        )
    row('对齐区间', '课堂', '来源', '观察到该区间', '区间完整', '记录数', '关注占比')
    for item in data['alignment']['rows']:
        for index, value in enumerate(item['cells']):
            for source in SOURCES:
                metric = value['sources'][source]
                row(
                    data['alignment']['columns'][index]['label'], item['label'], SOURCE_NAMES[source],
                    value['observed'], value['complete'], metric['total'], metric['concern_ratio'],
                )
    row('重复出现线索', '来源', '满足阈值的课堂数', '可比较课堂数', '阈值')
    for pattern in data['alignment']['patterns']:
        row(
            pattern['label'], SOURCE_NAMES[pattern['source']], len(pattern['matching_sessions']),
            len(pattern['eligible_sessions']), pattern['threshold'],
        )
    row('质量类别', '级别', '涉及课堂数')
    for issue in data['quality']['categories']:
        row(issue['title'], issue['severity'], len(issue['session_ids']))
    row('课堂', '来源', '完整区间', '有记录区间', '样本充足区间', '时间覆盖率', '最长连续空白')
    for item in data['sessions']:
        for source in SOURCES:
            coverage = item['quality']['coverage'][source]
            row(
                item['session']['class_name'], SOURCE_NAMES[source], coverage['complete_windows'],
                coverage['populated_windows'], coverage['sufficient_windows'], coverage['coverage_ratio'],
                coverage['longest_empty_run']['windows'],
            )
    row('课堂', 'AI 置信度区间', '记录数')
    for item in data['sessions']:
        for band in item['confidence_histogram']:
            row(item['session']['class_name'], band['band'], band['count'])
    row('批注类别', '批注', '版本', '更新时间')
    for annotation in report['annotations']:
        row(SECTION_NAMES[annotation['section']], annotation['content'], annotation['version'], annotation['updated_at'])
    row('方法说明', '内容')
    for title, value in data['methodology'].items():
        row(title, ','.join(value) if isinstance(value, list) else value)
    return ('\ufeff' + buffer.getvalue()).encode('utf-8')


def distribution_svg(metric):
    colors = ('#bcaa69', '#8ca879', '#8aa6ba', '#bc8c80', '#aa9bc0', '#b5a787', '#8ea599')
    total = metric['total']
    width = 600
    left = 0
    pieces = []
    for emotion, color in zip(EMOTIONS, colors):
        amount = metric['counts'][emotion]
        segment = amount / total * width if total else 0
        if segment:
            pieces.append(
                f'<rect x="{left:.2f}" y="0" width="{segment:.2f}" height="30" fill="{color}">'
                f'<title>{cell(NAMES[emotion])}: {amount}</title></rect>'
            )
        left += segment
    if not total:
        pieces.append('<rect width="600" height="30" fill="#e8ecdf"/>')
    return (
        '<svg role="img" aria-label="七类情绪记录分布" viewBox="0 0 600 30" xmlns="http://www.w3.org/2000/svg">'
        + ''.join(pieces) + '</svg>'
    )


def source_section(data, source):
    summary = data['sources'][source]
    pooled = summary['pooled']
    rows = [
        [NAMES[emotion], pooled['counts'][emotion], percentage(pooled['shares'][emotion])]
        for emotion in EMOTIONS
    ]
    return (
        f'<section><h2>{cell(SOURCE_NAMES[source])}</h2>'
        f'<p>共 {pooled["total"]} 条记录，纳入等权计算 {summary["eligible_sessions"]} 节课堂。</p>'
        f'<p>课堂等权关注占比：<strong>{percentage(summary["equal_weight_concern_ratio"])}</strong>；'
        f'按记录汇总关注占比：<strong>{percentage(pooled["concern_ratio"])}</strong>。</p>'
        + distribution_svg(pooled)
        + table(['情绪', '记录数', '占比'], rows)
        + '</section>'
    )


def alignment_section(data):
    alignment = data['alignment']
    sections = [f'<section><h2>跨课堂对齐</h2><p>{cell(alignment["description"])}</p>']
    for source in SOURCES:
        headers = ['课堂'] + [item['label'] for item in alignment['columns']]
        values = []
        for row in alignment['rows']:
            cells = []
            for value in row['cells']:
                metric = value['sources'][source]
                if not value['observed']:
                    cells.append('未观察到')
                elif not metric['total']:
                    cells.append('无记录')
                else:
                    suffix = '' if value['complete'] else '（未完整）'
                    cells.append(f"{percentage(metric['concern_ratio'])} / {metric['total']} 条{suffix}")
            values.append([row['label'], *cells])
        sections.append(f'<h3>{cell(SOURCE_NAMES[source])}</h3>')
        sections.append(table(headers, values))
    sections.append('</section>')
    return ''.join(sections)


def session_section(data):
    headers = ['课程', '班级', '开始时间', '主动反馈', 'AI 记录', '演示记录', '质量提示']
    values = []
    for item in data['sessions']:
        values.append([
            item['session']['course_name'],
            item['session']['class_name'],
            item['session']['starts_at'],
            item['sources']['MANUAL']['total'],
            item['sources']['AI']['total'],
            item['demo_count'],
            item['quality']['warning_count'],
        ])
    return '<section><h2>所选课堂</h2>' + table(headers, values) + '</section>'


def quality_section(data):
    values = [
        [item['severity'], item['title'], len(item['session_ids'])]
        for item in data['quality']['categories']
    ]
    return (
        '<section><h2>数据质量核对</h2>'
        f'<p>{data["quality"]["sessions_with_warnings"]} 节课堂包含警示，'
        f'共 {data["quality"]["warning_count"]} 项警示及 {data["quality"]["info_count"]} 项说明。</p>'
        + table(['级别', '核对事项', '涉及课堂数'], values)
        + '<p>质量提示不会自动删除原记录，也不是心理或教学质量评分。</p></section>'
    )


def group_section(data):
    values = []
    for item in data['groups']:
        values.append([
            SOURCE_NAMES[item['source']],
            item['baseline']['eligible_sessions'],
            item['comparison']['eligible_sessions'],
            percentage(item['baseline']['equal_weight_concern_ratio']),
            percentage(item['comparison']['equal_weight_concern_ratio']),
            '不可比较' if item['equal_weight_change_pp'] is None else f"{item['equal_weight_change_pp']:+g}",
        ])
    return (
        '<section><h2>基准组与比较组</h2>'
        + table(['来源', '基准课堂数', '比较课堂数', '基准等权占比', '比较等权占比', '变化百分点'], values)
        + '<p>差异为描述性结果，课堂背景与样本构成可能不同。</p></section>'
    )


def html_report(report):
    data = report['result']
    findings = ''.join(
        f'<li><strong>{cell(item["title"])}</strong>：{cell(item["text"])}</li>'
        for item in data['findings']
    )
    annotations = ''.join(
        f'<article><h3>{cell(SECTION_NAMES[item["section"]])}</h3><p class="pre">{cell(item["content"])}</p></article>'
        for item in report['annotations']
    )
    methods = table(['项目', '计算边界'], [
        [key, ', '.join(value) if isinstance(value, list) else value]
        for key, value in data['methodology'].items()
    ])
    style = '''
    :root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#2c3c33;background:#f6f6f1;line-height:1.7}
    body{margin:0;padding:32px}main{max-width:1100px;margin:auto}header,section{background:#fffefa;border:1px solid #dfe4d8;border-radius:14px;padding:26px;margin-bottom:20px}
    h1{font-size:28px}h2{font-size:21px;color:#45634e}h3{font-size:16px}small,.meta{color:#667365;font-size:12px}.pre{white-space:pre-wrap;overflow-wrap:anywhere}
    table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #dfe4d8;padding:9px;text-align:left;vertical-align:top}th{background:#f1f4ec}.table-scroll{overflow:auto;margin-top:15px}
    svg{width:100%;height:30px;margin:12px 0}.notice{border-left:4px solid #9cab7b;padding:12px 18px;background:#f1f4ec}.fingerprint{overflow-wrap:anywhere;font-family:monospace}
    @media print{body{padding:0;background:white}header,section{border-radius:0;break-inside:avoid}a{color:inherit}.table-scroll{overflow:visible}table{font-size:10px}}
    '''
    content = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">'
        f'<title>{cell(report["title"])}</title><style>{style}</style></head><body><main>'
        f'<header><p class="meta">HappyClass · 课堂情绪分析实验室</p><h1>{cell(report["title"])}</h1>'
        f'<p>{cell(report["definition"]["question"])}</p>'
        f'<p class="meta">报告 #{report["id"]} · {cell(data["captured_at"])} · {cell(data["engine_version"])}</p>'
        f'<p class="fingerprint">SHA-256：{cell(report["fingerprint"])}</p></header>'
        f'<section><h2>分析摘要</h2><ul>{findings}</ul><p class="notice">按反馈条数统计，手动反馈和 AI 分开计算。可以结合课堂情况读这份报告。</p></section>'
        + session_section(data)
        + ''.join(source_section(data, source) for source in SOURCES)
        + alignment_section(data)
        + group_section(data)
        + quality_section(data)
        + f'<section><h2>教师结论</h2><p class="pre">{cell(report["conclusion"] or "尚未填写")}</p>{annotations}</section>'
        + f'<section><h2>方法与参数</h2>{methods}<pre class="pre">{cell(json.dumps(data["settings"],ensure_ascii=False,indent=2))}</pre></section>'
        + '</main></body></html>'
    )
    return content.encode('utf-8')


def export_report(identifier, user, format):
    report = get_report(identifier, user)
    if format == 'csv':
        content = csv_report(report)
        media = 'text/csv'
    elif format == 'json':
        content = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')
        media = 'application/json'
    elif format == 'html':
        content = html_report(report)
        media = 'text/html'
    else:
        raise ValueError('Unsupported export format')
    with connect() as db:
        audit(db, user['id'], 'LAB_REPORT_EXPORTED', {'report_id': identifier, 'format': format})
    return content, media
