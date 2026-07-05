# ragflow-skills：chunk marker / table 原子性实测

**日期**：2026-07-05
**测试环境**：`~/.hermes/skills/research/ragflow-skills/.venv`，`ragflow_skill_runtime.doc_postprocess`

## 结论摘要

- `doc-to-md` 的 chunk marker 插入算法**不会**在 Markdown 表格或 HTML 表格中间插入 marker
- marker 只出现在表格开始行之前或下一个边界（heading / page / image）之前
- 表格后处理规则（OCR 清理、CJK 修复）只作用于表格外部，不会破坏表格内容
- 质量报告会输出 `chunk_marker_table_atomicity.ok` 用于检测异常
- 但 RAGFlow 自己的 chunker 仍可能按 token 切分超大表格，这与 `doc-to-md` 的 marker 是两层问题

## 实测用例

### 用例 1：长 Markdown 表格

输入：
```markdown
# Specs

| Col1 | Col2 | Col3 |
| --- | --- | --- |
| row0 | val0 | data0 |
...
| row19 | val19 | data19 |

## Next Section

Body
```

使用 `profile="chunk-markers-dense"`：
- 输出 marker 数：2
- marker 位置：表格开始行之前、下一节 heading 之前
- 表格内部无 marker
- 表格行未被拆分到多个段落

### 用例 2：HTML 表格

输入：
```markdown
# Catalog

<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>

## Details

More.
```

输出：
- 输出 marker 数：2
- 第一个 marker 在 `<table>` 之前
- 第二个 marker 在 `## Details` 之前
- `<table>` 与 `</table>` 之间无 marker

## 关键源码位置

- `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_postprocess.py`
  - `_table_protected_spans()`：合并 HTML 和 Markdown 表格范围
  - `_apply_outside_table_blocks()`：只对外部文本应用后处理
  - `_insert_chunk_markers_for_profile()`：按边界类型插入 marker
  - `_chunk_marker_profile_config()`：四种 profile 配置
- `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_quality.py`
  - `_chunk_marker_table_atomicity()`：检测 marker 是否切坏 HTML 表格

## 质量报告字段

```json
{
  "quality_signals": {
    "chunk_marker_table_atomicity": {
      "delimiter": "`<!-- chunk -->`",
      "chunk_marker_count": 2,
      "fragment_count": 3,
      "unbalanced_fragment_count": 0,
      "unbalanced_fragments": [],
      "ok": true
    }
  }
}
```

`ok: false` 时应检查 `unbalanced_fragments` 列表，定位被切坏的表格位置。
