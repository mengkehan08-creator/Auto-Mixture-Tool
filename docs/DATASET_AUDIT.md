# STEM JSON 数据适配、审查与过滤

本文针对生产数据目录：

```text
/home/ma-user/work/STEM_sample_100B_only_数理化生_json/part-*
```

分片是无扩展名的逐行 JSON。平台将 `part-*` 识别为 JSON；`stem-json-parquet` 会生成过滤后的 Parquet 副本，但不覆盖源文件。

## 1. 字段映射

使用 `configs/schema_stem_sample_json.yaml` 中的 `record_adapter: stem-sample-json-v1`。

| QuadMix 字段 | 原始字段/生成方式 |
|---|---|
| `text` | `text` |
| `category_name` | 从 `domain_category_cls_v1.3[0].category_name` 推导；失败时尝试 `stem_quality_eval.stem_domains` |
| 5 个质量分 | `stem_quality_eval` 中同名字段 |
| `char_count_col` | 优先 `cut_text_len`，其次 `raw_text_len`，最后计算文本长度 |
| `source_record_idx` | 分片物理行号，用于按需回读原文 |

主分类映射为 QuadMix 四域：

- `数理科学和化学-化学-分析化学` → 化学
- `生物学/动物学-昆虫学` → 生物学
- `数理科学和化学-物理-高能物理学` → 物理
- `数理科学和化学-数学-基础数学` → 数学

## 2. 默认过滤规则

规则位于 `configs/schema_stem_sample_json.yaml`，可以直接调整：

```yaml
filter:
  required_status: SUCCESS
  required_verdict: accept
  required_correctness: Y
  required_duplication_suspect: N
  min_primary_domain_score: 0.4
  min_token_num: 64
  max_token_num: 16384
  min_quality:
    stem_relevance: 4
    knowledge_value: 3
    notation_fidelity: 3
    rigor_coherence: 3
    noise_level: 3
```

结构不完整、文本为空、域无法映射或质量分无法转为数值的记录也会被拒绝。过滤只影响进入 QuadMix 的记录集合，不写回源数据。

## 3. 快速抽样审查

```bash
curl -X POST http://127.0.0.1:8080/api/v1/datasets/inspect \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_uri": "/home/ma-user/work/STEM_sample_100B_only_数理化生_json",
    "schema_uri": "/home/ma-user/work/Auto-Mixture-Tool/configs/schema_stem_sample_json.yaml",
    "dataset_id": "stem-json-parquet",
    "sample_size": 1000,
    "full_scan": false
  }'
```

返回的 `filter_preview` 和 `format_check.details.filter_preview_by_file` 给出样本通过数和拒绝原因。

## 4. 全量审查

正式运行前将 `full_scan` 设为 `true`：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/datasets/inspect \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_uri": "/home/ma-user/work/STEM_sample_100B_only_数理化生_json",
    "schema_uri": "/home/ma-user/work/Auto-Mixture-Tool/configs/schema_stem_sample_json.yaml",
    "dataset_id": "stem-json-parquet",
    "full_scan": true
  }'
```

`full_audit` 返回扫描数、接受数、拒绝数、通过率、拒绝原因、四域分布、缺失域、逐分片统计和 `algorithm_compatible`。全量审查不会生成过滤后的数据副本。

## 5. 常见拒绝原因

| 原因 | 含义 |
|---|---|
| `missing_or_empty_text` | 文本缺失或为空 |
| `missing_stem_quality_eval` | 缺少质检对象 |
| `unmapped_domain` | 无法映射到四个目标域 |
| `status_rejected` | `status` 不符合要求 |
| `overall_verdict_rejected` | 质检结论不是 accept |
| `correctness_rejected` | 正确性未通过 |
| `duplication_rejected` | 疑似重复 |
| `*_below_min` | 某项质量分低于阈值 |
| `primary_domain_score_below_min` | 主分类置信度不足 |
| `token_num_below_min/above_max` | 长度越界 |

完整过滤结果还会写入 `pipeline_summary.json -> data_filter`。

## 6. 阈值调整原则

- 先全量审查，再依据拒绝原因分布调阈值，不要只依据 5 条样本。
- 通过率异常低时先检查字段和域映射，不要立即降低质量门槛。
- 某个域没有合格记录时会判为算法不兼容，应修正映射或数据源。
- 修改过滤配置会改变元数据缓存键，QuadMix 会自动重建缓存。
