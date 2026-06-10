from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DAILY_ETF_DIR = ROOT / "cn_stock" / "daily_etf"
SOURCE_SUFFIX = "_daily_etf.html"
OUTPUT_SUFFIX = "_daily_merge.html"
PREFERRED_CODE_ORDER = [
    "513100",
    "159696",
    "159941",
    "513870",
    "161130",
    "513390",
    "159659",
    "513110",
    "159632",
    "159509",
    "159501",
    "513300",
]


def extract_json_var(text: str, var_name: str):
    pattern = re.compile(rf"const\s+{re.escape(var_name)}\s*=\s*(\{{.*?\}});", re.S)
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Missing payload: {var_name}")
    return json.loads(match.group(1))


def load_source_payloads():
    files = sorted(
        path
        for path in DAILY_ETF_DIR.glob(f"*{SOURCE_SUFFIX}")
        if path.is_file()
    )
    payloads = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        premium_table = extract_json_var(text, "premiumTablePayload")
        normalized = extract_json_var(text, "premiumNormalizedChartPayload")
        payloads.append(
            {
                "path": path,
                "date": path.name[:8],
                "premium_table": premium_table,
                "normalized": normalized,
            }
        )
    return payloads


def load_backup_payload():
    backup_files = sorted(
        path
        for path in DAILY_ETF_DIR.glob(f"*{OUTPUT_SUFFIX}")
        if path.is_file()
    )
    if not backup_files:
        return None
    latest_backup = backup_files[-1]
    text = latest_backup.read_text(encoding="utf-8")
    return extract_json_var(text, "payload")


def get_nasdaq_codes(latest_payload):
    categories = latest_payload["normalized"].get("categories", [])
    for category in categories:
        if category.get("key") == "纳指ETF" or category.get("label") == "纳指ETF":
            codes = [str(code) for code in category.get("codes", [])]
            if codes:
                return codes
    raise ValueError("Missing 纳指ETF category codes")


def row_to_map(columns, row_values):
    mapped = {}
    for column, value in zip(columns, row_values):
        key = column.get("key", "")
        if isinstance(value, list):
            text = value[0] if value else ""
            numeric = value[1] if len(value) > 1 else None
        else:
            text = value
            numeric = None
        mapped[key] = {
            "text": "" if text is None else str(text),
            "numeric": numeric,
        }
    return mapped


def is_bar_column(column_key: str) -> bool:
    return ("涨幅" in column_key) or (column_key in {"溢价", "相对52周最高"})


def build_column_configs(data_columns, rows_by_code):
    column_configs = []
    for key in data_columns:
        positive_values = []
        negative_values = []
        has_numeric = False
        for rows in rows_by_code.values():
            for row in rows:
                numeric = row["cells"].get(key, {}).get("numeric")
                if isinstance(numeric, (int, float)):
                    has_numeric = True
                    if numeric >= 0:
                        positive_values.append(float(numeric))
                    else:
                        negative_values.append(abs(float(numeric)))
        column_configs.append(
            {
                "key": key,
                "label": key,
                "isBar": is_bar_column(key),
                "isNumeric": has_numeric,
                "positiveMax": max(positive_values) if positive_values else 0,
                "negativeMax": max(negative_values) if negative_values else 0,
            }
        )
    return column_configs


def normalize_backup_rows(backup_payload, data_columns, allowed_codes):
    normalized_rows = {}
    if not backup_payload:
        return normalized_rows

    for code, rows in (backup_payload.get("rowsByCode") or {}).items():
        code = str(code)
        if allowed_codes and code not in allowed_codes:
            continue
        normalized_rows.setdefault(code, [])
        for row in rows or []:
            date = str(row.get("date", ""))
            raw_cells = row.get("cells") or {}
            cells = {}
            for key in data_columns:
                cell = raw_cells.get(key, {})
                if isinstance(cell, dict):
                    cells[key] = {
                        "text": "" if cell.get("text") is None else str(cell.get("text")),
                        "numeric": cell.get("numeric"),
                    }
                else:
                    cells[key] = {
                        "text": "" if cell is None else str(cell),
                        "numeric": None,
                    }
            if date:
                normalized_rows[code].append({"date": date, "cells": cells})
    return normalized_rows


def merge_rows_by_code(base_rows_by_code, incoming_rows_by_code):
    merged = {}
    for code in set(base_rows_by_code) | set(incoming_rows_by_code):
        date_map = {}
        for row in base_rows_by_code.get(code, []):
            date_map[row["date"]] = row
        for row in incoming_rows_by_code.get(code, []):
            date_map[row["date"]] = row
        merged[code] = sorted(date_map.values(), key=lambda item: item["date"], reverse=True)
    return merged


def build_history_payloads(source_payloads, backup_payload=None):
    if source_payloads:
        latest_payload = source_payloads[-1]
    elif backup_payload:
        latest_payload = {"date": backup_payload.get("latestDate", ""), "normalized": {"categories": []}, "premium_table": {"columns": []}}
    else:
        raise FileNotFoundError("No daily_etf html files or daily_merge backup found")

    if source_payloads:
        nasdaq_codes = get_nasdaq_codes(latest_payload)
    else:
        nasdaq_codes = [
            str(item.get("code", ""))
            for item in (backup_payload or {}).get("etfList", [])
            if item.get("code")
        ]
        if not nasdaq_codes:
            nasdaq_codes = sorted(str(code) for code in (backup_payload or {}).get("rowsByCode", {}).keys())

    backup_code_set = set(str(code) for code in (backup_payload or {}).get("rowsByCode", {}).keys())
    all_codes = []
    for code in PREFERRED_CODE_ORDER + nasdaq_codes + sorted(backup_code_set):
        if code not in all_codes:
            all_codes.append(code)

    code_to_name = {
        str(item.get("code", "")): item.get("name", str(item.get("code", "")))
        for item in (backup_payload or {}).get("etfList", [])
        if item.get("code")
    }

    latest_columns = latest_payload["premium_table"].get("columns", [])
    if latest_columns:
        data_columns = [
            column.get("key", "")
            for column in latest_columns
            if column.get("key") not in {"序号", "代码", "名称"}
        ]
    else:
        data_columns = [column.get("key", "") for column in (backup_payload or {}).get("columns", [])]

    latest_order = []
    for row in latest_payload["premium_table"].get("rows", []):
        row_map = row_to_map(latest_columns, row.get("values", []))
        code = row_map.get("代码", {}).get("text", "")
        if code in all_codes:
            latest_order.append(code)

    source_rows_by_code = {code: [] for code in all_codes}

    for payload in source_payloads:
        columns = payload["premium_table"].get("columns", [])
        for row in payload["premium_table"].get("rows", []):
            row_map = row_to_map(columns, row.get("values", []))
            code = row_map.get("代码", {}).get("text", "")
            if code not in all_codes:
                continue
            name = row_map.get("名称", {}).get("text", "")
            if name:
                code_to_name[code] = name
            source_rows_by_code.setdefault(code, []).append(
                {
                    "date": payload["date"],
                    "cells": {
                        key: {
                            "text": row_map.get(key, {}).get("text", ""),
                            "numeric": row_map.get(key, {}).get("numeric"),
                        }
                        for key in data_columns
                    },
                }
            )

    for code in source_rows_by_code:
        source_rows_by_code[code].sort(key=lambda item: item["date"], reverse=True)

    backup_rows_by_code = normalize_backup_rows(backup_payload, data_columns, set(all_codes))
    rows_by_code = merge_rows_by_code(backup_rows_by_code, source_rows_by_code)

    ordered_codes = []
    for code in PREFERRED_CODE_ORDER + latest_order + nasdaq_codes + sorted(backup_code_set):
        if code not in ordered_codes and rows_by_code.get(code):
            ordered_codes.append(code)
    for code in sorted(rows_by_code):
        if code not in ordered_codes and rows_by_code.get(code):
            ordered_codes.append(code)

    latest_date = source_payloads[-1]["date"] if source_payloads else str(backup_payload.get("latestDate", ""))
    column_configs = build_column_configs(data_columns, rows_by_code)
    etf_list = [
        {
            "code": code,
            "name": code_to_name.get(code, code),
            "count": len(rows_by_code.get(code, [])),
        }
        for code in ordered_codes
    ]
    return {
        "title": "纳指ETF历史对比",
        "subtitle": "按 ETF 按钮切换，汇总 daily_etf 历史页面中的纳指ETF条目，方便做跨日期对比",
        "latestDate": latest_date,
        "sourceCount": len(source_payloads),
        "backupDate": (backup_payload or {}).get("latestDate", ""),
        "columns": column_configs,
        "etfList": etf_list,
        "rowsByCode": rows_by_code,
    }


def build_html(payload):
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>纳指ETF历史对比</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card: #111827;
      --line: #334155;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --primary: #2563eb;
      --primary-soft: rgba(37, 99, 235, 0.18);
      --accent: #f59e0b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }}
    .page {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 18px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.18);
    }}
    .hero {{
      padding: 18px 20px;
      margin-bottom: 14px;
    }}
    .hero h1 {{
      margin: 0;
      font-size: 26px;
    }}
    .hero p {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 14px;
      padding: 14px;
      background: linear-gradient(180deg, rgba(8, 15, 31, 0.82), rgba(15, 23, 42, 0.72));
    }}
    .etf-btn {{
      border: 1px solid rgba(168, 85, 247, 0.28);
      border-radius: 999px;
      background: linear-gradient(180deg, rgba(30, 27, 75, 0.72), rgba(15, 23, 42, 0.88));
      color: #c4b5fd;
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 6px 14px rgba(76, 29, 149, 0.12);
      transition: 0.18s ease;
    }}
    .etf-btn:hover {{
      transform: translateY(-1px);
      border-color: rgba(45, 212, 191, 0.38);
      color: #ccfbf1;
      background: linear-gradient(180deg, rgba(19, 78, 74, 0.48), rgba(15, 23, 42, 0.88));
    }}
    .etf-btn.active {{
      color: #f8fafc;
      background: linear-gradient(135deg, rgba(14, 165, 233, 0.28), rgba(20, 184, 166, 0.24));
      border-color: rgba(45, 212, 191, 0.54);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 10px 22px rgba(20, 184, 166, 0.16);
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      padding: 14px;
      margin-bottom: 14px;
    }}
    .summary-item {{
      padding: 14px;
      border-radius: 14px;
      background: rgba(15, 23, 42, 0.48);
      border: 1px solid rgba(148, 163, 184, 0.12);
    }}
    .summary-label {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
      font-weight: 700;
    }}
    .summary-value {{
      font-size: 22px;
      font-weight: 800;
      line-height: 1.2;
    }}
    .summary-sub {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
    }}
    .summary-value-positive {{
      color: #f87171;
    }}
    .summary-value-negative {{
      color: #22c55e;
    }}
    .summary-value-neutral {{
      color: #e5e7eb;
    }}
    .table-card {{
      padding: 14px;
    }}
    .table-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .table-title {{
      font-size: 18px;
      font-weight: 800;
    }}
    .table-header-btn {{
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      font-weight: 800;
      padding: 0;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .table-header-btn.is-active {{
      color: #dbeafe;
    }}
    .sort-arrow {{
      color: #60a5fa;
      font-size: 11px;
      line-height: 1;
    }}
    .table-badge {{
      padding: 7px 12px;
      border-radius: 999px;
      background: rgba(245, 158, 11, 0.18);
      color: #fde68a;
      border: 1px solid rgba(245, 158, 11, 0.28);
      font-size: 12px;
      font-weight: 700;
    }}
    .table-wrap {{
      overflow: auto;
      border-radius: 14px;
      border: 1px solid rgba(148, 163, 184, 0.12);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1280px;
    }}
    thead th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: #162132;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-align: left;
      padding: 11px 10px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.16);
      white-space: nowrap;
    }}
    tbody td {{
      padding: 11px 10px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.08);
      font-size: 13px;
      white-space: nowrap;
    }}
    tbody tr:nth-child(odd) td {{
      background: rgba(15, 23, 42, 0.24);
    }}
    tbody tr:hover td {{
      background: rgba(37, 99, 235, 0.08);
    }}
    .date-cell {{
      color: #bfdbfe;
      font-weight: 700;
    }}
    .metric-cell {{
      min-width: 110px;
    }}
    .metric-bar {{
      position: relative;
      height: 22px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(51, 65, 85, 0.72);
      border: 1px solid rgba(148, 163, 184, 0.12);
    }}
    .metric-bar-fill {{
      position: absolute;
      inset: 0 auto 0 0;
      width: 0;
      border-radius: 999px;
      opacity: 0.92;
    }}
    .metric-bar-fill.positive {{
      background: linear-gradient(90deg, rgba(239,68,68,0.82), rgba(239,68,68,0.96));
    }}
    .metric-bar-fill.negative {{
      background: linear-gradient(90deg, rgba(34,197,94,0.82), rgba(34,197,94,0.96));
    }}
    .metric-bar-text {{
      position: relative;
      z-index: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100%;
      padding: 0 8px;
      font-weight: 800;
      color: #f8fafc;
    }}
    .empty {{
      padding: 36px 16px;
      text-align: center;
      color: var(--muted);
      font-size: 14px;
    }}
    @media (max-width: 960px) {{
      .summary {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="card hero">
      <h1>纳指ETF历史对比</h1>
      <p id="pageSubtitle"></p>
    </section>
    <section class="summary" id="summary"></section>
    <section class="card toolbar" id="etfButtons"></section>
    <section class="card table-card">
      <div class="table-head">
        <div class="table-title" id="tableTitle"></div>
        <div class="table-badge">历史合并</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr id="tableHead"></tr></thead>
          <tbody id="tableBody"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const payload = {payload_json};
    const state = {{
      activeCode: payload.etfList.length ? payload.etfList[0].code : "",
      sortKey: "日期",
      sortDesc: true
    }};

    function escapeHtml(text) {{
      return String(text ?? "").replace(/[&<>"']/g, function(char) {{
        return {{
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;"
        }}[char] || char;
      }});
    }}

    function getEtfMeta(code) {{
      return payload.etfList.find(function(item) {{
        return item.code === code;
      }}) || null;
    }}

    function renderButtons() {{
      const wrap = document.getElementById("etfButtons");
      wrap.innerHTML = payload.etfList.map(function(item) {{
        const activeClass = item.code === state.activeCode ? "etf-btn active" : "etf-btn";
        return '<button type="button" class="' + activeClass + '" data-code="' + escapeHtml(item.code) + '">' +
          escapeHtml(item.name) +
          '</button>';
      }}).join("");
      wrap.querySelectorAll("[data-code]").forEach(function(button) {{
        button.addEventListener("click", function() {{
          state.activeCode = button.getAttribute("data-code") || "";
          render();
        }});
      }});
    }}

    function renderSummary(rows, meta) {{
      const summary = document.getElementById("summary");
      const latest = rows[0] || null;
      const latestGainText = latest ? (((latest.cells["今日涨幅"] || {{}}).text) || "-") : "-";
      const latestGainValue = latest ? Number((latest.cells["今日涨幅"] || {{}}).numeric) : NaN;
      summary.innerHTML = [
        {{
          label: "当前ETF",
          value: meta ? meta.name : "-",
          sub: meta ? ("历史记录 " + String(meta.count) + " 天") : "-",
          valueClass: ""
        }},
        {{
          label: "最新价",
          value: latest ? ((latest.cells["最新价"] || {{}}).text || "-") : "-",
          sub: latest ? "收盘最新值" : "-",
          valueClass: ""
        }},
        {{
          label: "最新涨幅",
          value: latestGainText,
          sub: Number.isFinite(latestGainValue) ? (latestGainValue >= 0 ? "红涨" : "绿跌") : "-",
          valueClass: Number.isFinite(latestGainValue) ? (latestGainValue > 0 ? "summary-value-positive" : (latestGainValue < 0 ? "summary-value-negative" : "summary-value-neutral")) : ""
        }},
        {{
          label: "历史天数",
          value: String(rows.length),
          sub: "来自 " + payload.sourceCount + " 个 daily_etf 页面",
          valueClass: ""
        }},
        {{
          label: "最新日期",
          value: latest ? latest.date : "-",
          sub: "最新合并页 " + payload.latestDate,
          valueClass: ""
        }}
      ].map(function(item) {{
        return '<div class="card summary-item">' +
          '<div class="summary-label">' + escapeHtml(item.label) + '</div>' +
          '<div class="summary-value ' + escapeHtml(item.valueClass || "") + '">' + escapeHtml(item.value) + '</div>' +
          '<div class="summary-sub">' + escapeHtml(item.sub) + '</div>' +
          '</div>';
      }}).join("");
    }}

    function renderTable(rows, meta) {{
      document.getElementById("tableTitle").textContent = meta ? (meta.name + " 历史指标") : "历史指标";
      document.getElementById("tableHead").innerHTML = ['<th><button type="button" class="table-header-btn ' + (state.sortKey === "日期" ? "is-active" : "") + '" data-sort-key="日期">日期<span class="sort-arrow">' + (state.sortKey === "日期" ? (state.sortDesc ? "▼" : "▲") : "↕") + "</span></button></th>"]
        .concat(payload.columns.map(function(column) {{
          return '<th><button type="button" class="table-header-btn ' + (state.sortKey === column.key ? "is-active" : "") + '" data-sort-key="' + escapeHtml(column.key) + '">' +
            escapeHtml(column.label) +
            '<span class="sort-arrow">' + (state.sortKey === column.key ? (state.sortDesc ? "▼" : "▲") : "↕") + "</span></button></th>";
        }})).join("");

      const sortedRows = rows.slice().sort(function(a, b) {{
        if (state.sortKey === "日期") {{
          return state.sortDesc ? b.date.localeCompare(a.date) : a.date.localeCompare(b.date);
        }}
        const column = payload.columns.find(function(item) {{
          return item.key === state.sortKey;
        }});
        const aCell = a.cells[state.sortKey] || {{}};
        const bCell = b.cells[state.sortKey] || {{}};
        if (column && column.isNumeric) {{
          const aNum = Number(aCell.numeric);
          const bNum = Number(bCell.numeric);
          if (Number.isFinite(aNum) && Number.isFinite(bNum) && aNum !== bNum) {{
            return state.sortDesc ? (bNum - aNum) : (aNum - bNum);
          }}
          if (Number.isFinite(aNum) && !Number.isFinite(bNum)) return -1;
          if (!Number.isFinite(aNum) && Number.isFinite(bNum)) return 1;
        }}
        const aText = String(aCell.text || "");
        const bText = String(bCell.text || "");
        return state.sortDesc ? bText.localeCompare(aText, "zh-Hans-CN") : aText.localeCompare(bText, "zh-Hans-CN");
      }});

      document.getElementById("tableHead").querySelectorAll("[data-sort-key]").forEach(function(button) {{
        button.addEventListener("click", function() {{
          const nextKey = button.getAttribute("data-sort-key") || "日期";
          if (state.sortKey === nextKey) {{
            state.sortDesc = !state.sortDesc;
          }} else {{
            state.sortKey = nextKey;
            state.sortDesc = true;
          }}
          render();
        }});
      }});

      const tbody = document.getElementById("tableBody");
      if (!sortedRows.length) {{
        tbody.innerHTML = '<tr><td class="empty" colspan="' + String(payload.columns.length + 1) + '">暂无历史数据</td></tr>';
        return;
      }}

      tbody.innerHTML = sortedRows.map(function(row) {{
        const cells = payload.columns.map(function(column) {{
          const cell = row.cells[column.key] || {{}};
          if (column.isBar && typeof cell.text !== "undefined") {{
            const numeric = Number(cell.numeric);
            let width = 0;
            let cls = "positive";
            if (Number.isFinite(numeric)) {{
              if (numeric < 0) {{
                cls = "negative";
                width = column.negativeMax > 0 ? (Math.abs(numeric) / column.negativeMax) * 100 : 0;
              }} else {{
                cls = "positive";
                width = column.positiveMax > 0 ? (numeric / column.positiveMax) * 100 : 0;
              }}
            }}
            width = Math.max(0, Math.min(100, width));
            return '<td class="metric-cell"><div class="metric-bar"><div class="metric-bar-fill ' + cls + '" style="width:' + width.toFixed(2) + '%"></div><div class="metric-bar-text">' + escapeHtml(cell.text || "-") + "</div></div></td>";
          }}
          return "<td>" + escapeHtml(cell.text || "-") + "</td>";
        }}).join("");
        return '<tr><td class="date-cell">' + escapeHtml(row.date) + "</td>" + cells + "</tr>";
      }}).join("");
    }}

    function renderSubtitle() {{
      document.getElementById("pageSubtitle").textContent =
        payload.subtitle + "，最新输出日期 " + payload.latestDate;
    }}

    function render() {{
      const rows = payload.rowsByCode[state.activeCode] || [];
      const meta = getEtfMeta(state.activeCode);
      renderSubtitle();
      renderButtons();
      renderSummary(rows, meta);
      renderTable(rows, meta);
    }}

    render();
  </script>
</body>
</html>
"""


def cleanup_old_outputs(latest_output_name: str):
    for path in DAILY_ETF_DIR.glob(f"*{OUTPUT_SUFFIX}"):
        if path.name != latest_output_name:
            path.unlink()


def main():
    source_payloads = load_source_payloads()
    backup_payload = load_backup_payload()
    merge_payload = build_history_payloads(source_payloads, backup_payload)
    latest_date = merge_payload["latestDate"]
    output_name = f"{latest_date}{OUTPUT_SUFFIX}"
    cleanup_old_outputs(output_name)
    output_path = DAILY_ETF_DIR / output_name
    output_path.write_text(build_html(merge_payload), encoding="utf-8")
    print(f"Generated {output_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
