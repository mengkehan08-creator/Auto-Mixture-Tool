# OBS 评测包

评测配置 → 评测集评测 → OBS 路径。上方可继续选择内置 STEM 各项，下面可增加或删除评测包。
取消全部 STEM 单项时可以只评测新增包；关闭评测集开关时这些包也不执行。
页面固定使用全量样本，不再显示“每项最大样本数”。

新增地址必须指向解压后的目录，包含：

```text
core.yaml
eval_meta_data.csv
eval_data/
  example.jsonl
```

core.yaml 示例：

```yaml
icl_tasks:
  - label: custom_science
    dataset_uri: example.jsonl
    num_fewshot: [0]
    icl_task_type: multiple_choice
    continuation_delimiter: "\nAnswer: "
```

JSONL 的记录字段和基线 CSV 必须遵循所挂载 NanoChat 版本的评测接口，不接受任意训练文本。
当前新增包支持 multiple_choice、generation；生成题答案提取方式仅接受 gsm8k 或 math。
作业开始时先检查全部包的配置、路径、基线存在性和 JSONL，再加载模型评测。
这属于格式及声明检查，不能代替实际评分器对题目语义和答案正确性的验证。

有新增包时，内置结果位于 builtin/，新增包依次位于 package_0/、package_1/ 等目录，
每个目录分别生成各模型 CSV 和 comparison_report.json/md；实验配置保留目录顺序、名称和 OBS 地址。
工具后端不直接读取 OBS；文件存在性和兼容性在 ModelArts 挂载后检查。
