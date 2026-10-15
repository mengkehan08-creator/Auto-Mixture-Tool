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
- `iam_verify_ssl`：默认 `True`。如明确接受服务器身份无法验证、Secret 和 Token 可能被截获的风险，可在私有 `auth` 或 `AUTH_CONFIG` 字典中设置为 Python 布尔值 `False`（不能写成字符串）。仅关闭 IAM 获取 Token 请求的证书校验，不关闭 ModelArts 校验，也不自动绕过代理；原脚本的 `verify=False` 不会自动映射到此开关。修改后重启后端。建议取得可信 CA 后恢复 `True`。

不要复制附件中的旧 secret；建议先轮换。不要在 Git 仓库里的模板填真实凭据。私有文件是可信 Python 配置，只允许管理员修改，不能接受来自用户的文件路径。

## 启动 UI 后端

如明确接受风险，需同时跳过 IAM 与 ModelArts 证书验证，在仓库外私有文件的 `auth` 或 `AUTH_CONFIG` 字典内添加：

```python
"iam_verify_ssl": False,
"modelarts_verify_ssl": False,
```

`modelarts_verify_ssl` 默认 `True`，设为 `False` 后仅影响工具工作流的 ModelArts 提交及状态查询，不改变独立提交脚本。关闭时 `ca_bundle` 不用于相应服务的校验；不会关闭重定向限制或地址授权检查。此配置不解决代理、网络或权限问题。保存后必须重启后端，恢复安全验证时将两项改回 `True` 并配置可信 CA。

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

## 旧版可以获取、新版获取失败时

先检查新版后端 `/api/v1/workflow-defaults` 返回的 `auth_mode`。`manual` 表示该后端进程启动时没有设置 `AMT_IAM_PROVIDER`；在启动新版的同一个终端设置旧版实际使用的私有文件绝对路径，再重启新版。`iam` 仅表示已选择自动认证，不表示 Token 已获取成功。

旧的“请检查网络、代理及 CA 证书”提示把多类连接异常合并了，不能据此确定是证书问题。更新并重启后，错误会带有下列固定分类；不显示底层异常文本，以免泄露认证信息或代理密码。

| 错误分类 | 排查方向 |
| --- | --- |
| `SSLError` | TLS/SSL 连接失败。比较新旧 Python 环境的 CA 配置，以及私有文件中的 `ca_bundle`、`iam_verify_ssl`；也可能是其他 TLS 握手问题。 |
| `ProxyError` | 代理连接失败。比较新旧后端启动终端中的代理设置，不要输出含密码的代理地址。 |
| `Timeout` | 建立连接或读取响应超时。核对网络、代理和 IAM 服务连通性。 |
| `ConnectionError` | 其他连接失败。核对 DNS、网络和代理；此分类不能单独确定具体原因。 |
| `RequestException` | 其他请求异常，需要继续核对请求环境。 |
| `HTTP 401/403` 等状态码 | 已收到 HTTP 响应，核对私有认证配置、权限及代理/网关返回状态。 |

同一个 Notebook 中，不同虚拟环境或不同启动终端的配置仍可能不同。原始脚本中的 `verify=False` 和代理修改不会自动导入；仅复制 `auth` 字典不代表已经复用了这些连接设置。优先复用旧服务实际使用的可信 CA 配置，不根据通用错误直接关闭证书验证。修改后重启新版后端。

### 从运行中的旧版复用认证启动环境

旧版仍能正常获取 Token 时，可用 `scripts/reuse_modelarts_auth_env.py` 复制该进程的认证启动环境。先更新新版代码，保留旧版运行；PID 应使用当前检查得到的值，以下 `1406516` 仅为示例。

```bash
cd /home/ma-user/work/Auto-Mixture-Tool-MultiNode
git pull --ff-only origin main
python3 scripts/reuse_modelarts_auth_env.py --pid 1406516 --workspace /home/ma-user/work/Auto-Mixture-Tool
```

脚本验证进程属于当前用户、是 AMT 后端且工作目录匹配，只复制 `AMT_IAM_PROVIDER`、大小写代理/NO_PROXY 和 CA 环境变量。配置写入旧版私有认证文件旁的 `amt_multinode_runtime.env`，权限为 `600`；拒绝写入 Git 仓库，不打印配置值。这个文件可能包含代理密码，应与私有认证文件一起保管，不上传 Git、OBS 或聊天。

看到“已保存认证启动环境”后，停止新版服务，在同一个终端加载该文件再启动。以私有认证文件位于 `/home/ma-user/work/private_auth/iam_token_provider.py` 为例：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool-MultiNode
source .venv/bin/activate
source /home/ma-user/work/private_auth/amt_multinode_runtime.env
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
python -m auto_mixture_tool.cli --workspace "$PWD" serve --host 0.0.0.0 --port 8081
```

以后每次启动新版前加载同一份 `.env` 文件即可。旧版未设置的相关变量会在新版终端中取消，避免保留新版独有的 `ALL_PROXY`、旧的 `NO_PROXY` 等设置。旧版连接配置变化后，应重新复制。

此脚本依赖 Linux `/proc`，读取的是进程启动环境；Python 代码运行后在内存里修改的代理设置不在快照范围内。新版继续使用自己的 Python 依赖。若复用后仍失败，应对比云端旧版的认证实现和运行时设置，不能据此继续假定旧版采用直连。脚本本身不执行私有认证文件、不请求 Token。

## 行为与验证边界

- 配置预检查只核对私有配置和目标地址，不请求 IAM、不创建作业。
- 配比作业和后续训练作业每次真正提交前重新获取 Token；失败时不发送创建作业请求。
- 查询状态时使用内存缓存，提前 5 分钟刷新；缺少可解析的有效期时不复用缓存，不假定一定有效 24 小时。
- 自动 Token 不写入实验记录，不回显至页面、不打印；HTTP 失败响应中的相同 Token 会被脱敏。
- 重启时自动鉴权模式可恢复已有作业监控；对无法确认是否已经提交的作业不自动重复提交。
- 仅实现本工具 UI/工作流后端自动鉴权；直接运行原 `modelarts_training_job.py` 仍使用脚本自身的手动 headers。
- 目前通过模拟测试，未用真实密钥验证内部 IAM、证书链和网关 Token 前缀。IAM 获取成功也不保证 ModelArts 权限和资源满足要求。

占位符能降低仓库泄密风险，但不能消除开发环境文件泄露、账户滥用或误上传风险。.gitignore 不能保护已经被 Git 跟踪的文件，因此务必填写仓库外的副本。
