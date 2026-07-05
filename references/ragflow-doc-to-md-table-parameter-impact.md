# ragflow-doc-to-md 参数对表格解析质量的影响

适用场景：用户问「调整哪些参数能改善表格质量」时，快速判断每个参数是否值得尝试。

## 结论先行

在当前 Blackwell + MinerU 3.2.1 FastAPI + `pipeline` 后端环境下，**通过调整 ragflow-doc-to-md 调用参数来显著改善扫描 PDF 表格质量的空间很有限**。表格质量的上限主要由 MinerU 后端模型决定，而非 doc-to-md 包装层参数。

## 参数影响分层

| 层级 | 参数 | 是否改善表格质量 | 说明 |
|------|------|------------------|------|
| 核心决定层 | `--table-quality high` | 理论上 yes，当前环境 no | 会触发 `hybrid-auto-engine`，在 Blackwell sm_120 上初始化失败 |
| 核心决定层 | `--mineru-fastapi-backend` | 受限于环境 | 当前只有 `pipeline` 能稳定完成 |
| 核心决定层 | `--mineru-enable-table` | 必须保持 true | 关闭后表格退化为图片/文本 |
| 中间影响层 | `--mineru-is-ocr` | 对该文档 no | 扫描 PDF 已自动走 OCR，显式开启无差异 |
| 中间影响层 | `--mineru-language` | 必须 `ch` | `auto`/`en` 会降低中文数字/单位识别 |
| 包装影响层 | `--postprocess-profile` | no | 只影响 chunk marker 密度，不改变表格内容 |
| 包装影响层 | `--mineru-asset-mode` | no | 只影响图片形式，不改变表格结构 |

## 实用决策树

1. 表格质量是否由「表格结构缺失/错乱」导致？ → 检查 `--mineru-enable-table` 是否为 true
2. 是否是中文扫描件？ → 确保 `--mineru-language ch`
3. 是否想尝试更高精度？ → 先确认 GPU 是否支持 `hybrid-auto-engine`（Blackwell 不支持）
4. 是否想改善 chunk 边界？ → 调整 `--postprocess-profile`（dense / ragflux-like）
5. 是否想改善入库后检索效果？ → 调整 RAGFlow profile 的 `chunk_token_num` 和 delimiter

## 真正有效的改善方向（超出 doc-to-md 参数）

- 升级 MinerU 到支持 Blackwell high-accuracy backend 的版本
- 在非 Blackwell 环境上跑 `--table-quality high`
- 对关键表格用 VLM 二次识别
- 入库后检查 RAGFlow chunk 是否切坏表格

## 验证方法

对比两套输出时，使用可量化指标：
- HTML `<table>` 数量
- 每表行数/列数
- 合并单元格（rowspan/colspan）保留情况
- 表格字符数
- chunk 分布
- 入库后 RAGFlow chunk 内容

不要仅依赖肉眼观察；用数据支撑「无显著差异」或「有差异」的结论。
