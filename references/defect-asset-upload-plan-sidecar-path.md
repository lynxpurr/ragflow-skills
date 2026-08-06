# DEFECT: asset-upload-plan 误报 image_missing（sidecar 图片路径解析缺陷）

**编号:** RAGFLOW-SKILL-DEFECT-001
**发现日期:** 2026-07-09
**严重级别:** Medium（功能可用但用户体验误导）
**影响组件:** `ragflow-skill-runtime/kb_build.py` → `_collect_sidecar_image_references()`
**触发场景:** MinerU 解析 PDF 产出 handoff bundle（图片在 `documents/images/` 子目录）后执行 `asset-upload-plan`

## 症状

执行 `build.py asset-upload-plan` 时，plan status 被标记为 `blocked`，生成 36 个 `image_missing` error。但 `planned_visual_upload_files` 中 88/88 全部 `exists=true`，`image-ingestion-execute` 可正常完成上传。

## 根因

`_collect_sidecar_image_references()`（kb_build.py:510）递归扫描 sidecar JSON（如 `artifact_index.json`），提取所有看起来像图片路径的字符串值。`artifact_index.json` 的 JSON 文本中包含不带 `documents/` 前缀的相对路径（如 `images/Palantir---AI/xxx.jpg`），扫描器提取后用 `handoff_root / candidate` 解析（第 532 行），但实际路径是 `handoff_root / documents / images/...`。

Markdown 引用路径正确是因为解析时用 `markdown_path.parent / target_path`（第 721 行），自动补上了 `documents/` 前缀。

## 影响评估

| 维度 | 影响 |
|:--|:--|
| 上传功能 | 无影响 — `image-ingestion-execute` 不检查 plan status |
| 用户体验 | plan status=blocked 误导用户认为不可上传 |
| CI/CD | 检查 `status != blocked` 的流水线会被阻断 |

## 规避方法

不要被 `status=blocked` 吓到。检查 `planned_visual_upload_files` 数组的实际 `exists` 字段——如果全部为 true，直接执行 `image-ingestion-execute`。

## 修复建议

**方案 A（推荐，最小改动）：** 在 `_collect_sidecar_image_references()` 第 532 行增加 fallback：

```python
resolved = handoff_root / candidate
if not resolved.is_file():
    alt = handoff_root / "documents" / candidate
    if alt.is_file():
        resolved = alt
```

**方案 B（数据层）：** 让 `artifact_index.json` 统一使用相对于 handoff_root 的绝对路径。

## 证据

- Plan JSON 中 `planned_visual_upload_files`: 88 条全部 `exists=true`
- Plan JSON 中 `discovered_image_artifacts`: 36 条 `asset_class=missing`，全部 `source=sidecar:artifact_index.json`
- 误报路径: `images/Palantir---AI/image-001_image.jpg`
- 正确路径: `documents/images/Palantir---AI/image-001_image.jpg`
- 实际上传结果: 88/88 DONE, 0 FAILED

## 相关文件

- `ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py:510-535` — bug 所在
- `ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py:413-426` — `_iter_image_path_references()` 递归扫描器
