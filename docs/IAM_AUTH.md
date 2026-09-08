# 自动获取 Authorization

仓库根目录的 `iam_token_provider.py` 只含占位符。此功能使用所提供脚本中的 IAM JWT 接口，不包含密码认证或明文磁盘 Token 缓存。默认不启用，不影响手动 Authorization。

## 开发环境配置

也支持直接把原始 `iam_token_provider_test.py` 的完整内容粘贴到仓库外的 `iam_token_provider.py`。加载器只通过 AST 读取末尾的 `auth = {...}` 字面量字典，不执行 imports、类定义、Token 请求或 print。无须修改原脚本函数；实际鉴权由工具内的安全实现负责。旧字典的 `endpoint/region/project_id` 不参与 JWT 请求，也不会被用来推导或限制 UI 作业地址。仍使用 JWT account/secret，不使用旧脚本的静态 token 或密码认证分支。

旧脚本的 `verify=False`、全局代理修改和打印行为不会生效；如需要内部 CA，向 `auth` 字典补充 `ca_bundle`。文件替换后重启后端，保留 `AMT_IAM_PROVIDER` 设置即可。不要单独执行私有原脚本，因为它自身仍会打印 Token。

先将工具代码更新到包含本功能的版本，再执行：

```bash
mkdir -p /home/ma-user/work/private_auth
chmod 700 /home/ma-user/work/private_auth
cp -n /home/ma-user/work/Auto-Mixture-Tool/iam_token_provider.py /home/ma-user/work/private_auth/iam_token_provider.py
chmod 600 /home/ma-user/work/private_auth/iam_token_provider.py
```

仅编辑仓库外的私有副本，在 `AUTH_CONFIG` 中填写：

- `account / secret / project / enterprise`：你的 IAM JWT 认证信息。
- `modelarts_endpoint`：可选的独立目标地址限制；留空使用可信 `csbgw.roma.huawei.com` 网关、当前 account 路径和 ModelArts 作业路由限制，不锁定旧脚本的区域或项目。若使用其他网关，明确填写与 UI `url` 相同的完整创建作业 API 地址。它不是 IAM 取 Token 地址，也不是原脚本里无关的 `endpoint`。
- `authorization_prefix`：默认空字符串，表示直接使用 access_token。只有网关明确要求时才改成 `Bearer `（末尾有空格）。
- `ca_bundle`：默认空，使用系统信任证书。内部 CA 不被系统信任时填写可信 CA PEM 文件绝对路径，用于 IAM 及 ModelArts HTTPS 校验，不要关闭证书验证。

不要复制附件中的旧 secret；建议先轮换。不要在 Git 仓库里的模板填真实凭据。私有文件是可信 Python 配置，只允许管理员修改，不能接受来自用户的文件路径。

## 启动 UI 后端

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
# 只有已创建该虚拟环境时才激活；否则使用已安装依赖的 Python。
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
export AMT_IAM_PROVIDER=/home/ma-user/work/private_auth/iam_token_provider.py
python -m auto_mixture_tool.cli --workspace "$PWD" serve --host 0.0.0.0 --port 8080
```

页面 Authorization 留空即可。启用后使用管理员配置的身份，页面手动填写的 Token 不参与远程鉴权。只应向可信内部用户开放后端，自动 IAM 不等于为 UI 增加用户登录和权限隔离。

私有文件及 AMT_IAM_PROVIDER 不上传 OBS、不放进 command，也不放进作业环境变量；只有开发环境提交后端需要它们。修改凭据后重启后端。需要恢复手动模式时，停止后端，执行 `unset AMT_IAM_PROVIDER` 后重新启动。

## 行为与验证边界

- 配置预检查只核对私有配置和目标地址，不请求 IAM、不创建作业。
- 配比作业和后续训练作业每次真正提交前重新获取 Token；失败时不发送创建作业请求。
- 查询状态时使用内存缓存，提前 5 分钟刷新；缺少可解析的有效期时不复用缓存，不假定一定有效 24 小时。
- 自动 Token 不写入实验记录，不回显至页面、不打印；HTTP 失败响应中的相同 Token 会被脱敏。
- 重启时自动鉴权模式可恢复已有作业监控；对无法确认是否已经提交的作业不自动重复提交。
- 仅实现本工具 UI/工作流后端自动鉴权；直接运行原 `modelarts_training_job.py` 仍使用脚本自身的手动 headers。
- 目前通过模拟测试，未用真实密钥验证内部 IAM、证书链和网关 Token 前缀。IAM 获取成功也不保证 ModelArts 权限和资源满足要求。

占位符能降低仓库泄密风险，但不能消除开发环境文件泄露、账户滥用或误上传风险。.gitignore 不能保护已经被 Git 跟踪的文件，因此务必填写仓库外的副本。
