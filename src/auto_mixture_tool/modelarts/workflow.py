"""Submit dependent mixing, training and evaluation ModelArts jobs."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import re
import shlex
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from urllib.parse import quote, urlencode, urlsplit

import requests
from .config_transport import write_config
from .iam_auth import get_provider
from .strategy_upload import validate_script, MAX_TOTAL_BYTES


SUCCESS_STATES = {"completed", "succeeded", "success"}
FAILURE_STATES = {"failed", "canceled", "cancelled", "terminated"}
RESOURCE_INPUTS = {
    'code_obs_uri': 'code_dir', 'quadmix_tokenizer_obs_uri': 'quadmix_tokenizer_dir',
    'proxy_validation_obs_uri': 'proxy_validation_dir', 'eval_bundle_obs_uri': 'eval_bundle_dir',
    'python_wheels_obs_uri': 'python_wheels_dir',
}


def _remote_error(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    code = data.get("error_code") or data.get("error_name")
    message = data.get("error_msg") or data.get("error_message")
    return "；".join(str(item)[:1500] for item in (code, message) if item)


class ModelArtsRejected(RuntimeError):
    """The service explicitly rejected a request."""


def _response_data(response):
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"ModelArts 返回非 JSON 响应（HTTP {response.status_code}），请检查 API 地址或网关") from None
    detail = _remote_error(data)
    if response.status_code >= 400 or detail:
        raise ModelArtsRejected(f"ModelArts 请求失败（HTTP {response.status_code}）：{detail or '服务端未提供错误详情'}")
    return data


def _console_url(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for source in (data, data.get("metadata", {})):
        if isinstance(source, dict):
            for key in ("console_url", "job_url"):
                value = str(source.get(key, ""))
                parsed = urlsplit(value)
                if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.query:
                    return value
    return ""


def training_console_url(job_id: str, region: str, workspace_name: str = "") -> str:
    """Build the same console route as the standalone submission script."""
    if not job_id or not region or "REPLACE_ME" in region:
        return ""
    result = ("https://console.huaweicloud.com/modelarts/?" +
              urlencode({"locale": "zh-cn", "region": region}) +
              "#/training/detail/" + quote(str(job_id), safe=""))
    if workspace_name:
        result += "?" + urlencode({"workspaceName": workspace_name})
    return result


def _clean_obs_uri(value: str) -> str:
    value = value.strip().rstrip("/")
    uri = urlsplit(value)
    if value.startswith("obs://bucket/path") or "REPLACE_ME" in value:
        raise ValueError("OBS 地址仍为示例占位路径，请填写实际的桶和目录")
    if (uri.scheme != "obs" or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", uri.netloc)
            or uri.query or uri.fragment or any(c.isspace() for c in value)
            or any(part in {".", ".."} for part in uri.path.split("/"))):
        raise ValueError("请输入有效的 obs://桶名/目录 地址，不接受 OBS 控制台网页地址、空格或查询参数")
    return value


def _state(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("status", "state", "phase"):
            if isinstance(value.get(key), str):
                return value[key]
            found = _state(value.get(key))
            if found:
                return found
        for key in ("metadata", "spec", "result", "data"):
            found = _state(value.get(key))
            if found:
                return found
    return ""


class ModelArtsClient:
    def __init__(self, template) -> None:
        headers, url = template.headers, template.url
        self.provider = get_provider()
        if self.provider:
            self.provider.validate_endpoint(url)
            headers = {**headers, 'Authorization': 'automatic-iam'}
        if not headers.get("Authorization") or "REPLACE_ME" in url or any("REPLACE_ME" in str(v) for v in headers.values()):
            raise ValueError(
                "请先在 modelarts_training_job.py 中填写 ModelArts API 地址、区域和 Authorization"
            )
        self.url = url.rstrip("/")
        self.headers = dict(headers)

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = self._request_headers(force_refresh=True)
        response = requests.post(
            self.url, headers=headers, json=payload, verify=self._tls_verify(), timeout=60,
            allow_redirects=False,
        )
        return self._response(response, headers)

    def get(self, job_id: str) -> dict[str, Any]:
        headers = self._request_headers()
        response = requests.get(
            f"{self.url}/{job_id}", headers=headers, verify=self._tls_verify(), timeout=60,
            allow_redirects=False,
        )
        return self._response(response, headers)

    def stop(self, job_id: str) -> dict[str, Any]:
        headers = self._request_headers(force_refresh=True)
        response = requests.post(
            f"{self.url}/{quote(job_id, safe='')}/actions", headers=headers,
            json={"action_type": "terminate"}, verify=self._tls_verify(), timeout=60,
            allow_redirects=False,
        )
        if response.status_code == 204:
            return {}
        return self._response(response, headers)

    def _request_headers(self, force_refresh=False):
        headers = dict(self.headers)
        if self.provider:
            headers['Authorization'] = self.provider.authorization(self.url, force_refresh)
        return headers

    def _tls_verify(self):
        # Preserve legacy manual mode; automatic mode verifies unless explicitly disabled.
        if not self.provider or not self.provider.config.get('modelarts_verify_ssl', True):
            return False
        return self.provider.config.get('ca_bundle') or True

    @staticmethod
    def _response(response, headers):
        try:
            if 300 <= response.status_code < 400:
                raise ModelArtsRejected('ModelArts API 返回重定向，请核对配置地址')
            return _response_data(response)
        except ModelArtsRejected as exc:
            token = headers.get('Authorization', '')
            message = str(exc)
            if token:
                message = message.replace(token, '[REDACTED]')
                if token.startswith('Bearer '):
                    message = message.replace(token[7:], '[REDACTED]')
            raise ModelArtsRejected(message) from None


class ModelArtsWorkflowManager:
    def __init__(self, workspace: Path, client: ModelArtsClient | None = None) -> None:
        self.workspace = Path(workspace)
        self.directory = self.workspace / "result" / ".workflows"
        self.client = client
        self.records: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._create_lock = threading.Lock()
        self._template_cache = None
        self._authorizations: dict[str, str] = {}
        self._active: set[str] = set()
        self._deleting: set[str] = set()
        self._stopping = threading.Event()

    def resume(self) -> None:
        """Resume monitoring known jobs; never repeat an ambiguous POST."""
        self._load_disk()
        auth_error = ''
        try:
            automatic_auth = get_provider() is not None
        except ValueError as exc:
            automatic_auth = False
            auth_error = str(exc)
        for record in list(self.records.values()):
            if record.get('delete_requested'):
                if record['status'] != 'DELETED':
                    self._start_delete(record['id'])
                continue
            if record["status"] not in {"SUCCEEDED", "FAILED", "NEEDS_ATTENTION"}:
                if auth_error or (record["config"].get("modelarts") and not automatic_auth):
                    record.update(status="WAITING_AUTH", stage=auth_error or "请在页面重新提供 Authorization 以恢复监控")
                    self._store(record)
                    continue
                self._start(record["id"])

    def close(self) -> None:
        self._stopping.set()

    def renew_authorization(self, workflow_id: str, authorization: str) -> dict[str, Any]:
        self.get(workflow_id)
        record = self.records[workflow_id]
        if not record["config"].get("modelarts"):
            raise ValueError("该实验使用服务端脚本配置")
        if not authorization.strip() or "\n" in authorization or "\r" in authorization:
            raise ValueError("Authorization 不能为空或包含换行")
        self._authorizations[workflow_id] = authorization
        if record["status"] == "WAITING_AUTH":
            record.update(status="QUEUED", message="")
            self._start(workflow_id)
        return self.public(record)

    def _start(self, workflow_id: str) -> None:
        with self._lock:
            if workflow_id in self._active or self.records[workflow_id].get('delete_requested'):
                return
            self._active.add(workflow_id)
        threading.Thread(target=self._run, args=(workflow_id,), daemon=True).start()

    def delete(self, workflow_id: str, confirmed_not_created: bool = False) -> dict[str, Any]:
        self.get(workflow_id)
        record = self.records[workflow_id]
        with self._lock:
            if workflow_id in self._deleting:
                return self.public(record)
            if confirmed_not_created:
                if (workflow_id in self._active or any(job.get('id') for job in record['jobs'])
                        or record['status'] not in {'NEEDS_ATTENTION', 'DELETE_FAILED'}):
                    raise ValueError('仅可对已停止提交、无远程作业 ID 的待核对记录确认未创建；已创建作业仍须终止')
                for job in record['jobs']:
                    if job['status'] in {'SUBMITTING', 'NEEDS_ATTENTION'}:
                        job['status'] = 'NOT_CREATED'
                record['absence_confirmed_at'] = datetime.now().astimezone().isoformat()
            record.update(delete_requested=True, status='DELETING', progress=0,
                          stage='正在删除实验记录，必要时终止关联作业', message='')
        self._store(record)
        self._start_delete(workflow_id)
        return self.public(record)

    def _start_delete(self, workflow_id):
        with self._lock:
            if workflow_id in self._deleting:
                return
            self._deleting.add(workflow_id)
        threading.Thread(target=self._delete_run, args=(workflow_id,), daemon=True).start()

    def _delete_run(self, workflow_id):
        record = self.records[workflow_id]
        try:
            # Let any in-flight creation request finish and persist its job ID.
            while workflow_id in self._active:
                if self._stopping.wait(0.1):
                    return
            for job in record['jobs']:
                if self._stopping.is_set():
                    return
                if not job.get('id'):
                    if job['status'] in {'SUBMITTING', 'NEEDS_ATTENTION'}:
                        raise ValueError('创建请求结果不明确，无法确定远程作业 ID；请在 ModelArts 核对并终止作业，记录暂不删除')
                    continue
                client = self._client(record)
                status = _state(client.get(job['id'])).lower()
                if status not in SUCCESS_STATES | FAILURE_STATES:
                    client.stop(job['id'])
                    # A successful stop response is not confirmation of termination.
                    for _ in range(24):
                        status = _state(client.get(job['id'])).lower()
                        if status in SUCCESS_STATES | FAILURE_STATES:
                            break
                        if self._stopping.wait(5):
                            return
                    else:
                        raise ValueError('已请求终止，但尚未确认远程作业结束；记录保留，请稍后重试删除')
                job['status'] = status.upper()
                self._store(record)
            record.update(status='DELETED', progress=0, stage='已删除', message='')
            self._authorizations.pop(workflow_id, None)
        except Exception as exc:
            message = str(exc)
            for secret in self._authorizations.values():
                if secret:
                    message = message.replace(secret, '[REDACTED]')
            record.update(status='DELETE_FAILED', progress=0,
                          stage='删除未完成，已禁止后续作业自动提交', message=message)
        finally:
            self._store(record)
            with self._lock:
                self._deleting.discard(workflow_id)

    def _template(self):
        if self._template_cache is None:
            source = self.workspace / "modelarts_training_job.py"
            if not source.is_file():
                raise FileNotFoundError('工作区缺少 modelarts_training_job.py')
            spec = importlib.util.spec_from_file_location("_amt_modelarts_template", source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._template_cache = module
        return self._template_cache

    def _configured_template(self, settings=None, authorization=""):
        source = self._template()
        template = SimpleNamespace(url=source.url, headers=dict(source.headers),
                                   job_data=copy.deepcopy(source.job_data))
        if not settings:
            return template
        template.url = settings.get("endpoint", "")
        template.headers.update(region=settings.get("region", ""), Authorization=authorization)
        template.job_data["metadata"]["workspace_id"] = settings.get("workspace_id", "")
        for key in ("image_url", "image_repo_id"):
            template.job_data["algorithm"]["engine"][key] = settings.get(key, "")
        for key in ("flavor_id", "pool_id"):
            template.job_data["spec"]["resource"][key] = settings.get(key, "")
        return template

    def preview(self, config: dict[str, Any]) -> dict[str, Any]:
        value = self._validate(config)
        from . import parallel_workflow
        if value.get('execution_mode') == 'parallel':
            parallel_workflow.check_names(self, parallel_workflow.planned_jobs(value))
        missing = []
        try:
            settings = value.get("modelarts")
            template = self._configured_template(settings, (settings or {}).get("authorization", ""))
            fields = {
                "url": template.url,
                "region": template.headers.get("region"),
                "Authorization": template.headers.get("Authorization"),
                "workspace_id": template.job_data["metadata"].get("workspace_id"),
                **{key: template.job_data["algorithm"]["engine"].get(key)
                   for key in ("image_url", "image_repo_id")},
                **{key: template.job_data["spec"]["resource"].get(key)
                   for key in ("flavor_id", "pool_id")},
            }
        except FileNotFoundError:
            raise ValueError('工作区缺少 modelarts_training_job.py，请检查启动时的 --workspace 路径') from None
        except (OSError, ValueError, AttributeError, KeyError, TypeError, SyntaxError, ImportError):
            raise ValueError('ModelArts 请求模板无法加载：请检查工作区 modelarts_training_job.py 的语法、依赖及必需字段') from None
        provider = get_provider()
        if provider:
            provider.validate_endpoint(template.url)
            fields['Authorization'] = 'automatic-iam'
        missing = [key for key, item in fields.items() if not item or 'REPLACE_ME' in str(item)]
        return {
            "ready": not missing,
            "missing_settings": missing,
            "jobs": parallel_workflow.planned_jobs(value) if value.get('execution_mode') == 'parallel' else [
                {"module": "mixing", "nodes": value["mixing_nodes"]},
                {"module": "training", "nodes": value["training_nodes"]},
                *([{"module": "evaluation", "nodes": value["evaluation_nodes"]}] if value['evaluation']['datasets'] or value['evaluation'].get('obs_packages') else []),
            ][({'training': 1, 'evaluation': 2}.get(value.get('reuse', {}).get('stage'), 0)):],
            "input_data_obs_uri": value["input_data_obs_uri"],
            "output_root_obs_uri": value["output_root_obs_uri"],
            "message": "仅检查配置及服务端模板；不提交任务，也不验证 OBS 文件及权限。",
        }

    def create(self, config: dict[str, Any]) -> dict[str, Any]:
        with self._create_lock:
            return self._create(config)

    def _create(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = self._validate(config)
        authorization = normalized.get("modelarts", {}).pop("authorization", "")
        self._load_disk()
        request_id = normalized.get("request_id")
        if request_id:
            for existing in self.records.values():
                if existing["config"].get("request_id") == request_id:
                    if existing.get('delete_requested'):
                        raise ValueError('原实验已申请删除，请使用新的请求标识创建实验')
                    if existing["config"] != normalized:
                        raise ValueError("重复请求标识对应的配置不同，请重新检查配置后提交")
                    return self.public(existing)
        if self.client is None:
            readiness = self.preview(config)
            if not readiness["ready"]:
                raise ValueError("管理员尚未配置：" + "、".join(readiness["missing_settings"]))
        # Fail the HTTP request immediately when the server-side ModelArts
        # endpoint or Authorization template has not been configured.
        if normalized.get("modelarts"):
            ModelArtsClient(self._configured_template(normalized["modelarts"], authorization))
        else:
            self._client()
        workflow_id = uuid.uuid4().hex[:12]
        if authorization:
            self._authorizations[workflow_id] = authorization
        created = datetime.now().astimezone()
        stamp = created.strftime("%Y%m%d-%H%M%S-%f")[:-3]
        prefix = normalized.get("experiment_name") or "experiment"
        experiment = f"{prefix}-{stamp}-{workflow_id[:6]}"
        run_root = f"{_clean_obs_uri(normalized['output_root_obs_uri'])}/runs/{experiment}"
        record = {
            "pipeline_version": 3,
            "id": workflow_id,
            "created_at": created.isoformat(timespec="milliseconds"),
            "name": experiment,
            "status": "QUEUED",
            "progress": 0,
            "stage": "等待提交配比作业",
            "run_root_obs_uri": run_root,
            "outputs": {
                "mixing": f"{run_root}/mixing/",
                "sampled": f"{run_root}/sampled/",
                "training": f"{run_root}/training/",
            },
            "jobs": [
                self._job_record("mixing", normalized["mixing_nodes"], stamp),
                self._job_record("training", normalized["training_nodes"], stamp),
                *([self._job_record("evaluation", normalized["evaluation_nodes"], stamp)] if normalized['evaluation']['datasets'] or normalized['evaluation'].get('obs_packages') else []),
            ],
            "config": normalized,
            "message": "",
        }
        for section, output, suffix in (("training", "models", "checkpoints"), ("evaluation", "reports", "results")):
            root = normalized[section].get("output_obs_uri")
            record["outputs"][output] = (
                f"{root}/runs/{experiment}/" if root else f"{run_root}/training/{suffix}/"
            )
        if normalized.get('execution_mode') == 'parallel':
            from . import parallel_workflow
            parallel_workflow.initialize(self, record, stamp)
            for job in record['jobs']:
                parallel_workflow.payload(self, record, job)
            self._store(record)
            self._start(workflow_id)
            return self.public(record)
        if normalized.get('reuse'):
            source = self._reuse_source(normalized['reuse'])
            start = 1 if normalized['reuse']['stage'] == 'training' else 2
            record['reused_from'] = source['id']
            for index in range(start):
                record['jobs'][index].update(status='SUCCEEDED', reused=True,
                                              source_workflow_id=source['id'])
            for key in ('mixing', 'sampled', *(['training', 'models'] if start == 2 else [])):
                record['outputs'][key] = source['outputs'][key]
            record['stage'] = '等待提交训练作业' if start == 1 else '等待提交评测作业'
        # Validate every stage request before scheduling the first paid job.
        for stage in ('mixing', 'training', *(['evaluation'] if len(record['jobs']) == 3 else [])):
            if record['jobs'][('mixing', 'training', 'evaluation').index(stage)].get('reused'):
                continue
            self._payload(record, stage)
        self._store(record)
        self._start(workflow_id)
        return self.public(record)

    def list(self) -> list[dict[str, Any]]:
        self._load_disk()
        return sorted((self.public(item) for item in self.records.values() if item.get('status') != 'DELETED'),
                      key=lambda item: self._created_timestamp(item), reverse=True)

    @staticmethod
    def _created_timestamp(record):
        try:
            return datetime.fromisoformat(record.get("created_at", "")).timestamp()
        except (ValueError, TypeError):
            return 0

    def get(self, workflow_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{12}", workflow_id):
            raise ValueError("invalid workflow id")
        self._load_disk()
        if workflow_id not in self.records or self.records[workflow_id]['status'] == 'DELETED':
            raise ValueError("workflow not found")
        return self.public(self.records[workflow_id])

    @staticmethod
    def public(record: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(record)
        value.pop("config", None)
        if not value.get("created_at"):
            # Older records encode local creation time in their generated names.
            match = re.search(r'-(\d{8}-\d{6}-\d{3})(?:-[0-9a-f]{6})?$', value.get("name", ""))
            if match:
                try:
                    value["created_at"] = datetime.strptime(match[1], "%Y%m%d-%H%M%S-%f").astimezone().isoformat()
                except ValueError:
                    pass
        return value

    def copy_configuration(self, workflow_id: str) -> dict[str, Any]:
        self.get(workflow_id)
        value = copy.deepcopy(self.records[workflow_id]["config"])
        value.pop("request_id", None)
        value.pop('reuse', None)
        value.pop('job_reuse', None)
        if value.get('execution_mode') == 'parallel':
            for strategy in value['strategies']:
                strategy['mixing_job_name'] = strategy['training_job_name'] = ''
            value['evaluation']['job_name'] = ''
        if value.get("modelarts"):
            value["modelarts"].pop("authorization", None)
        return value

    def _reuse_source(self, reuse):
        if not isinstance(reuse, dict) or set(reuse) != {'workflow_id', 'stage'} or reuse['stage'] not in {'training', 'evaluation'}:
            raise ValueError('复用配置必须指定 workflow_id 和 training/evaluation 阶段')
        self.get(reuse['workflow_id'])
        source = self.records[reuse['workflow_id']]
        if source.get('pipeline_version') != 3:
            raise ValueError('旧版合并作业不支持阶段复用，请新建实验')
        if source.get('delete_requested') or source['status'] not in {'FAILED', 'SUCCEEDED'}:
            raise ValueError('仅支持复用已结束且未申请删除的实验')
        count = 1 if reuse['stage'] == 'training' else 2
        if len(source['jobs']) < count or any(job['status'] != 'SUCCEEDED' for job in source['jobs'][:count]):
            raise ValueError('前序作业未全部成功，不能复用其输出')
        keys = ['sampled'] + (['models'] if count == 2 else [])
        if any(not source.get('outputs', {}).get(key) for key in keys):
            raise ValueError('原实验缺少可复用的 OBS 输出地址')
        return source

    @staticmethod
    def _job_record(module: str, nodes: int, stamp: str) -> dict[str, Any]:
        return {
            "module": module,
            "name": f"{module}-{nodes}node-{stamp}",
            "nodes": nodes,
            "status": "WAITING",
            "id": None,
        }

    def _validate(self, config: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(config)
        if value.get('execution_mode', 'sequential') not in {'parallel', 'sequential'}:
            raise ValueError('execution_mode 必须为 parallel 或 sequential')
        if value.get('reuse'):
            source = self._reuse_source(value['reuse'])
            original = source['config']
            for key in ('strategies', 'input_data_obs_uri', 'mixing_nodes', 'full_scan'):
                if key in original:
                    value[key] = copy.deepcopy(original[key])
            if value['reuse']['stage'] == 'evaluation':
                value['training'] = copy.deepcopy(original['training'])
                value['training_nodes'] = original['training_nodes']
                value['resources']['nanochat_model_obs_uri'] = original['resources']['nanochat_model_obs_uri']
                if not (value['evaluation'].get('datasets') or value['evaluation'].get('obs_packages')):
                    raise ValueError('从评测开始时必须选择评测任务或评测包')
        for section in ('training', 'evaluation', 'resources'):
            if not isinstance(value.get(section), dict):
                raise ValueError(f'{section} 必须是配置对象')
        priority = value.get('priority', 1)
        if type(priority) is not int or priority not in (1, 2, 3):
            raise ValueError('priority 必须为 1、2 或 3')
        value['priority'] = priority
        for section in ("training", "evaluation"):
            uri = value.get(section, {}).get("output_obs_uri")
            if uri:
                value[section]["output_obs_uri"] = _clean_obs_uri(uri)
        entries = value.get('offline_resources')
        roles = RESOURCE_INPUTS
        if entries is not None:
            if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
                raise ValueError('offline_resources 必须是资源对象列表')
            names, seen_roles = set(), set()
            for entry in entries:
                name, role = entry.get('name', ''), entry.get('role', '')
                if any(not isinstance(item, str) for item in (name, role, entry.get('uri', ''))):
                    raise ValueError('资源 name、role 和 uri 必须为字符串')
                if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name) or name in names
                        or name in {'data_dir', 'comparison_data_dir', 'nanochat_model_dir', 'nanochat_npu_dir'}
                        or re.fullmatch(r'strategy_\d+', name)):
                    raise ValueError('资源 name 必须唯一，以字母开头且仅含字母、数字、下划线，不能使用系统保留名称')
                names.add(name)
                raw_uri = entry.get('uri', '').strip()
                entry['uri'] = _clean_obs_uri(raw_uri) + ('/' if raw_uri.endswith('/') else '')
                if role:
                    if role not in roles or role in seen_roles:
                        raise ValueError('默认资源角色无效或重复')
                    seen_roles.add(role)
                    value['resources'][role] = entry['uri']
            if set(roles) - seen_roles:
                commands = value.get('commands') or {}
                strategies = value.get('strategies', []) if value.get('execution_mode') == 'parallel' else [{}]
                if any((strategy.get(stage + '_command') or commands.get(stage, self._command(stage))) == self._command(stage)
                       for strategy in strategies for stage in ('mixing', 'training')):
                    raise ValueError('已删除默认运行资源，请恢复资源或为所有配比、训练作业配置不依赖这些资源的自定义 command')
        commands = value.get("commands")
        if commands is not None:
            if isinstance(commands, dict) and set(commands) == {"mixing", "training"}:
                commands['evaluation'] = self._command('evaluation')
            if not isinstance(commands, dict) or set(commands) != {"mixing", "training", "evaluation"}:
                raise ValueError("command 必须分别提供配比和训练作业的启动命令")
            for command in commands.values():
                if not isinstance(command, str) or not command.strip() or "\x00" in command or len(command) > 32768:
                    raise ValueError("command 不能为空、包含空字符或超过 32768 字符")
        settings = value.get("modelarts")
        if settings:
            allowed = {"endpoint", "region", "authorization", "workspace_id", "workspace_name", "image_url",
                       "image_repo_id", "flavor_id", "pool_id"}
            if set(settings) - allowed or any(not isinstance(v, str) for v in settings.values()):
                raise ValueError("ModelArts 配置字段无效")
            endpoint = urlsplit(settings.get("endpoint", ""))
            if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username
                    or endpoint.password or endpoint.query or endpoint.fragment):
                raise ValueError("ModelArts API 地址须为无鉴权参数的 HTTPS 创建作业地址")
            if any("\n" in v or "\r" in v for v in settings.values()):
                raise ValueError("ModelArts 配置不能包含换行")
        if value.get("request_id") and not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", value["request_id"]):
            raise ValueError("request_id 格式不正确")
        experiment_name = str(value.get("experiment_name") or "").strip()
        if experiment_name and not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", experiment_name
        ):
            raise ValueError("experiment_name must use 1-48 letters, digits, _ or -")
        value["experiment_name"] = experiment_name
        for key in ("input_data_obs_uri", "output_root_obs_uri"):
            value[key] = _clean_obs_uri(str(value.get(key, "")))
        value.setdefault('evaluation_nodes', 1)
        for key in ("mixing_nodes", "training_nodes", "evaluation_nodes"):
            nodes = value.get(key, 0)
            if type(nodes) is not int or not 1 <= nodes <= 16:
                raise ValueError(f"{key} must be between 1 and 16")
            value[key] = nodes
        strategies = value.get("strategies")
        if not isinstance(strategies, list) or not strategies or any(not isinstance(s, dict) for s in strategies):
            raise ValueError("at least one strategy is required")
        kinds = [item.get("type") for item in strategies]
        if kinds.count("quadmix") > 1 or kinds.count("random") > 1:
            raise ValueError("only one quadmix and one random strategy are supported")
        upload_bytes = 0
        seen_ids = set()
        for index, strategy in enumerate(strategies):
            strategy_id = strategy.get('id', '')
            if (not isinstance(strategy_id, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', strategy_id)
                    or strategy_id in seen_ids):
                raise ValueError('每项策略需要唯一 id，使用 1–64 位字母、数字、下划线或连字符')
            seen_ids.add(strategy_id)
            if not isinstance(strategy.get('script_config', {}), dict):
                raise ValueError('script_config 必须是配置对象')
            label = strategy.get('name', strategy_id)
            if not isinstance(label, str) or any(c in label for c in '\t\r\n'):
                raise ValueError('策略名称不能包含换行或制表符')
            strategy.pop('local_script_path', None)
            if strategy.get('script_upload') is not None:
                if strategy.get('type') not in {'manual', 'random'} or strategy.get('script_obs_uri'):
                    raise ValueError('人工或随机策略只能选择一种脚本来源：OBS 地址或上传文件')
                upload_bytes += validate_script(strategy['script_upload'])
                if upload_bytes > MAX_TOTAL_BYTES:
                    raise ValueError('本次上传脚本总大小不能超过 128 KiB')
            script = str(strategy.get("script_obs_uri") or "").strip()
            if script:
                if strategy.get('type') not in {'manual', 'random'}:
                    raise ValueError('当前仅人工和随机策略支持上传采样脚本')
                strategy["script_obs_uri"] = _clean_obs_uri(script)
                if not script.lower().endswith(".py"):
                    raise ValueError("自定义采样策略必须指向 OBS 中的 .py 文件")
            if strategy.get("type") not in {"quadmix", "manual", "random"}:
                raise ValueError(f"unsupported strategy at index {index}")
            if strategy.get("type") == "manual":
                ratios = strategy.get("ratios")
                if not isinstance(ratios, dict) or not ratios:
                    raise ValueError("every manual strategy requires domain ratios")
                try:
                    ratios = {str(domain).strip(): float(ratio) for domain, ratio in ratios.items()}
                except (TypeError, ValueError) as exc:
                    raise ValueError("manual strategy ratios must be numeric") from exc
                if any(not domain or not math.isfinite(ratio) or ratio <= 0 for domain, ratio in ratios.items()):
                    raise ValueError("manual strategy domains and ratios must be positive")
                strategy["ratios"] = ratios
            if strategy.get("type") == "quadmix":
                for key in ("proxy_experiments", "proxy_steps", "search_count"):
                    number = strategy.get(key, {"proxy_experiments": 16, "proxy_steps": 15, "search_count": 1000}[key])
                    if type(number) is not int or number <= 0:
                        raise ValueError(f"quadmix {key} must be positive")
                    strategy[key] = number
                devices = strategy.get('devices_per_node', 8)
                if type(devices) is not int or not 1 <= devices <= 8:
                    raise ValueError('QuaDMix devices_per_node 必须为 1–8 的整数')
                strategy['devices_per_node'] = devices
                seed = strategy.get('seed', 42)
                if type(seed) is not int or not 0 <= seed < 2**32:
                    raise ValueError('随机种子必须为 0–4294967295 的整数')
                strategy['seed'] = seed
        shared_seed = next((s['seed'] for s in strategies if s['type'] == 'quadmix'), 42)
        for strategy in strategies:
            strategy['seed'] = strategy.get('seed', 42) if value.get('execution_mode') == 'parallel' else shared_seed
            if type(strategy['seed']) is not int or not 0 <= strategy['seed'] < 2**32:
                raise ValueError('随机种子必须为 0–4294967295 的整数')
        training = value.get("training", {})
        if str(training.get("framework", "nanochat")).lower() != "nanochat":
            raise ValueError("the current training adapter supports NanoChat only")
        devices = training.get("devices_per_node", 8)
        if type(devices) is not int or not 1 <= devices <= 8:
            raise ValueError("training devices_per_node must be between 1 and 8")
        training["devices_per_node"] = devices
        tag = training.get('base_model_tag', 'd24')
        if not isinstance(tag, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', tag):
            raise ValueError('base_model_tag 必须是模型目录名称，不能包含路径或空格')
        training['base_model_tag'] = tag
        ratio = float(training.get("target_param_data_ratio", 0.5))
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError("training target_param_data_ratio must be positive")
        training["target_param_data_ratio"] = ratio
        if "token_budget" in training:
            budget = training["token_budget"]
            if type(budget) is not int or not 1 <= budget <= 9007199254740991:
                raise ValueError("训练 Token 预算必须为大于 0 的安全整数")
            if training.get("num_iterations", 0) != 0:
                raise ValueError("训练 Token 预算与固定训练步数不能同时设置")
        for key, default, minimum in (("num_iterations", 0, 0), ("device_batch_size", 1, 1),
                                      ("eval_every", -1, -1), ("core_metric_every", -1, -1)):
            number = training.get(key, default)
            if (isinstance(number, bool) or not isinstance(number, int) or number < minimum
                    or (key.endswith("every") and number == 0)):
                raise ValueError(f"训练参数 {key} 无效：必须为合法整数；间隔仅支持 -1 或正整数")
            training[key] = number
        value["training"] = training
        evaluation = value.setdefault("evaluation", {"datasets": ["stem"]})
        packages = evaluation.get('obs_packages', [])
        if not isinstance(packages, list) or len(packages) > 16:
            raise ValueError('OBS 评测包必须为列表，最多 16 项')
        for package in packages:
            if not isinstance(package, dict) or not isinstance(package.get('name'), str) or not package['name'].strip():
                raise ValueError('请填写 OBS 评测包名称')
            package['obs_uri'] = _clean_obs_uri(str(package.get('obs_uri', '')))
        for key, default, minimum, maximum in (
            ('devices_per_node', 8, 1, 8), ('core_eval_batch_size', 16, 1, 4096),
            ('max_per_task', -1, -1, 2147483647),
        ):
            number = evaluation.get(key, default)
            if type(number) is not int or not minimum <= number <= maximum or number == 0:
                raise ValueError(f'评测参数 {key} 无效')
            evaluation[key] = number
        allowed = {"stem", "core", "all", "arc_easy", "arc_challenge", "mmlu_stem",
                   "gpqa_diamond", "gsm8k_cot", "math_cot_500", "mmlu_zeroshot"}
        datasets = evaluation.get("datasets", ["stem"])
        if not isinstance(datasets, list) or any(item not in allowed for item in datasets):
            raise ValueError("评测任务名称无效，请选择当前 NanoChat 支持的评测项")
        evaluation["datasets"] = list(dict.fromkeys(datasets))
        if set(datasets) & {'stem', 'core', 'all'} and len(set(datasets)) != 1:
            raise ValueError('评测预设 stem/core/all 不能与其他预设或单项任务混选')
        for key in (
            "code_obs_uri", "nanochat_repo_obs_uri", "nanochat_model_obs_uri",
            "quadmix_tokenizer_obs_uri", "proxy_validation_obs_uri",
            "eval_bundle_obs_uri", "python_wheels_obs_uri",
        ):
            if not value["resources"].get(key):
                raise ValueError(f"请填写资源 OBS 地址：{key}；代理验证集须指向包含 stem_v2_tokenized.pt 的目录")
            value["resources"][key] = _clean_obs_uri(value["resources"][key])
        runtime_config = copy.deepcopy(value)
        if value.get('execution_mode') == 'parallel':
            from .parallel_workflow import validate
            validate(self, value)
            runtime_config = copy.deepcopy(value)
        for key in ('modelarts', 'commands', 'offline_resources'):
            runtime_config.pop(key, None)
        write_config({}, runtime_config)
        return value

    def _client(self, record=None) -> ModelArtsClient:
        if record and record["config"].get("modelarts"):
            return ModelArtsClient(self._configured_template(
                record["config"]["modelarts"], self._authorizations.get(record["id"], "")))
        if self.client is None:
            self.client = ModelArtsClient(self._template())
        return self.client

    def _payload(self, record: dict[str, Any], stage: str) -> dict[str, Any]:
        payload = self._configured_template(record["config"].get("modelarts")).job_data
        config = copy.deepcopy(record["config"])
        config.pop("modelarts", None)
        job = record["jobs"][{'mixing': 0, 'training': 1, 'evaluation': 2}[stage]]
        payload["metadata"]["name"] = job["name"]
        payload["metadata"]["description"] = f"Auto-Mixture {stage} stage"
        payload["spec"]["resource"]["node_count"] = job["nodes"]
        payload["spec"].setdefault("schedule_policy", {})["priority"] = config.get('priority', 1)
        env = payload["algorithm"]["environments"]
        env["AMT_RUN_ID"] = record["name"]
        env["AMT_EXPECTED_NODES"] = str(job["nodes"])
        env["AMT_RUN_OBS_URI"] = f"{record['run_root_obs_uri']}/mixing/coordination"
        payload["algorithm"]["command"] = config.get("commands", {}).get(stage, self._command(stage))

        resources = config["resources"]
        payload["algorithm"]["code_dir"] = (
            resources.get("code_obs_uri") or payload["algorithm"]["code_dir"]
        ).rstrip("/") + "/"
        mapping = {
            "data_dir": config["input_data_obs_uri"],
            "nanochat_model_dir": resources["nanochat_model_obs_uri"],
            "code_dir": resources.get("code_obs_uri") or payload["algorithm"]["code_dir"],
            "nanochat_npu_dir": resources["nanochat_repo_obs_uri"],
            "quadmix_tokenizer_dir": resources["quadmix_tokenizer_obs_uri"],
            "proxy_validation_dir": resources["proxy_validation_obs_uri"],
            "eval_bundle_dir": resources["eval_bundle_obs_uri"],
            "python_wheels_dir": resources["python_wheels_obs_uri"],
        }
        needed_inputs = (
            {"data_dir", "nanochat_model_dir", "code_dir", "nanochat_npu_dir",
             "quadmix_tokenizer_dir", "proxy_validation_dir", "python_wheels_dir"}
            if stage == "mixing"
            else {"nanochat_model_dir", "code_dir", "nanochat_npu_dir",
                  "eval_bundle_dir", "python_wheels_dir"}
        )
        payload["algorithm"]["inputs"] = [
            item for item in payload["algorithm"]["inputs"]
            if item["name"] in needed_inputs
        ]
        for item in payload["algorithm"]["inputs"]:
            item["remote"]["obs"]["obs_url"] = mapping[item["name"]].rstrip('/') + '/'
        if config.get('offline_resources') is not None:
            roles = RESOURCE_INPUTS
            entries = config['offline_resources']
            by_role = {entry.get('role'): entry for entry in entries if entry.get('role')}
            reverse = {name: role for role, name in roles.items()}
            inputs = []
            for item in payload['algorithm']['inputs']:
                role = reverse.get(item['name'])
                if role:
                    if role not in by_role:
                        continue
                    item['name'] = by_role[role]['name']
                    item['remote']['obs']['obs_url'] = by_role[role]['uri'].rstrip('/') + '/'
                inputs.append(item)
            for entry in entries:
                if not entry.get('role'):
                    inputs.append({'name': entry['name'], 'local_dir': '/home/ma-user/modelarts/inputs/custom/' + entry['name'],
                                   'access_method': 'env', 'remote': {'obs': {'obs_url': entry['uri']}}})
            payload['algorithm']['inputs'] = inputs
        if stage == "training":
            payload["algorithm"]["inputs"].append({
                "name": "comparison_data_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/comparison_data_dir_8",
                "access_method": "env",
                "remote": {"obs": {"obs_url": record['outputs']['sampled']}},
            })
        if stage == 'evaluation':
            for index, package in enumerate(config['evaluation'].get('obs_packages', [])):
                payload['algorithm']['inputs'].append({
                    'name': f'eval_package_{index}', 'local_dir': f'/home/ma-user/modelarts/inputs/eval_package_{index}',
                    'access_method': 'env', 'remote': {'obs': {'obs_url': package['obs_uri'].rstrip('/') + '/'}},
                })
            payload['algorithm']['inputs'].append({
                'name': 'trained_models', 'local_dir': '/home/ma-user/modelarts/inputs/trained_models',
                'access_method': 'env', 'remote': {'obs': {'obs_url': record['outputs']['models']}},
            })
        for index, strategy in enumerate(config["strategies"], start=9):
            obs_uri = str(strategy.get("script_obs_uri") or "").strip()
            if not obs_uri or stage != "mixing":
                continue
            if not obs_uri.lower().endswith(".py"):
                raise ValueError("custom strategy OBS paths must point to a .py file")
            filename = obs_uri.rsplit("/", 1)[-1]
            local_dir = f"/home/ma-user/modelarts/inputs/strategy_dir_{index}"
            local_path = f"{local_dir}/{filename}"
            strategy["local_script_path"] = local_path
            payload["algorithm"]["inputs"].append({
                "name": f"strategy_{index}", "local_dir": local_dir,
                "access_method": "env", "remote": {"obs": {"obs_url": _clean_obs_uri(obs_uri)}},
            })
        runtime_config = copy.deepcopy(config)
        runtime_config['split_evaluation'] = record.get('pipeline_version') == 3
        runtime_config.pop('commands', None)
        runtime_config.pop('offline_resources', None)
        runtime_config.pop('reuse', None)
        if stage != 'mixing':
            for strategy in runtime_config['strategies']:
                strategy.pop('script_upload', None)
        write_config(env, runtime_config)
        for name, item in env.items():
            if len(str(item).encode('utf-8')) > 4096:
                raise ValueError(f'环境变量 {name} 超过 4096 字节，请减少该变量内容')
        payload["algorithm"]["outputs"][0]["remote"]["obs"]["obs_url"] = (
            record["run_root_obs_uri"] + "/"
        )
        if stage in {"training", "evaluation"}:
            pairs = (("training", "models"), ("evaluation", "reports"))
            if stage == 'evaluation':
                pairs = (("evaluation", "reports"),)
            elif record.get('pipeline_version') == 3:
                pairs = (("training", "models"),)
            for section, output in pairs:
                if config[section].get("output_obs_uri"):
                    payload["algorithm"]["outputs"].append({
                        "name": f"{output}_output", "local_dir": f"/home/ma-user/modelarts/outputs/{output}_output",
                        "access_method": "env", "remote": {"obs": {"obs_url": record["outputs"][output]}},
                    })
        return payload

    @staticmethod
    def _command(stage: str) -> str:
        if stage not in {'mixing', 'training', 'evaluation'}:
            raise ValueError('Unknown ModelArts stage')
        command = '''set -euo pipefail
cd /home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool
PY311="${AMT_PYTHON_EXECUTABLE:-$(command -v python3.11 || command -v python3 || true)}"
test -n "$PY311" || { echo "ERROR: Python 3.11 is required"; exit 2; }
"$PY311" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Python 3.11 required"'
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1 PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1
export NANOCHAT_SKIP_EVAL_DOWNLOAD=1 NANOCHAT_DISABLE_WANDB=1
PY_DEPS=/tmp/auto-mixture-python-packages
mkdir -p "$PY_DEPS" /tmp/auto-mixture-python
: > "$PY_DEPS/dask.py"
export PYTHONPATH="$PWD:$PWD/src:$PY_DEPS:${PYTHONPATH:-}"
if ! "$PY311" -c 'import lightgbm' >/dev/null 2>&1; then
  WHEEL=/home/ma-user/modelarts/inputs/python_wheels_dir_7/lightgbm-4.6.0-py3-none-manylinux2014_aarch64.whl
  if [ -f "$WHEEL" ]; then
    "$PY311" -m pip install --no-index --no-deps --upgrade --target "$PY_DEPS" "$WHEEL"
  else
    echo "Missing offline LightGBM wheel: $WHEEL"
  fi
fi
export AMT_PYTHON_EXECUTABLE="$PY311"
"$PY311" -m pip install --no-index --no-deps --upgrade --target "$PY_DEPS" /home/ma-user/modelarts/inputs/python_wheels_dir_7/rustbpe-0.1.0-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl
"$PY311" -c 'import rustbpe; rustbpe.Tokenizer(); print("rustbpe installed:", rustbpe.__file__)'
ln -sf "$PY311" /tmp/auto-mixture-python/python
ln -sf "$PY311" /tmp/auto-mixture-python/python3
export PATH="/tmp/auto-mixture-python:$PATH"
"$PY311" scripts/modelarts_runtime_check.py
exec "$PY311" -m auto_mixture_tool.modelarts.stage_runner ''' + stage
        return '/bin/bash -c ' + shlex.quote(command) + ' modelarts'

    def _run(self, workflow_id: str) -> None:
        record = self.records[workflow_id]
        if record.get('pipeline_version') == 4:
            from .parallel_workflow import run
            return run(self, record)
        if record.get('delete_requested'):
            with self._lock:
                self._active.discard(workflow_id)
            return
        try:
            if not self._submit_and_wait(record, 0, "mixing", 15, 45):
                return
            if record.get('delete_requested'):
                return
            record["status"] = "MIXING_SUCCEEDED"
            record["progress"] = 50
            record["stage"] = "配比完成，正在自动提交训练作业"
            self._store(record)
            if not self._submit_and_wait(record, 1, "training", 60, 95):
                return
            if record.get('delete_requested'):
                return
            if record.get('pipeline_version') == 3 and len(record['jobs']) > 2:
                record.update(status='TRAINING_SUCCEEDED', stage='训练完成，正在自动提交评测作业')
                self._store(record)
                if not self._submit_and_wait(record, 2, 'evaluation', 96, 99):
                    return
                if record.get('delete_requested'):
                    return
            record.update(status="SUCCEEDED", progress=100, stage="全部作业完成")
        except Exception as exc:
            uncertain = any(job["status"] == "SUBMITTING" and not job["id"] for job in record["jobs"])
            record["status"] = "NEEDS_ATTENTION" if uncertain else "FAILED"
            record["progress"] = 0
            record["stage"] = "提交结果待人工核对，请勿重复提交" if uncertain else "工作流失败"
            message = str(exc)
            for secret in self._authorizations.values():
                message = message.replace(secret, "[REDACTED]")
            record["message"] = message
        finally:
            if record.get('delete_requested'):
                record.update(status='DELETING', progress=0, stage='正在终止关联作业，确认后删除记录')
            self._store(record)
            with self._lock:
                self._active.discard(workflow_id)

    def _submit_and_wait(
        self, record: dict[str, Any], index: int, stage: str,
        submitted_progress: int, running_progress: int,
    ) -> bool:
        job = record["jobs"][index]
        if job["status"] == "SUCCEEDED":
            return True
        if self._stopping.is_set() or record.get('delete_requested'):
            return False
        job_id = job.get("id")
        if not job_id:
            if job["status"] == "SUBMITTING":
                raise RuntimeError("上次创建请求未记录作业 ID，请先在 ModelArts 核对作业是否已创建")
            payload = self._payload(record, stage)
            job["status"] = "SUBMITTING"
            self._store(record)
            try:
                response = self._client(record).submit(payload)
            except (ModelArtsRejected, ValueError):
                job["status"] = "FAILED"
                raise
            if _remote_error(response):
                job["status"] = "FAILED"
                raise RuntimeError("ModelArts 创建作业失败：" + _remote_error(response))
            metadata = response.get("metadata", {})
            job_id = metadata.get("id") or response.get("id")
            if not job_id:
                raise RuntimeError("ModelArts 创建响应未包含作业 ID，请到平台核对，不要自动重试")
            job.update(id=str(job_id), status="SUBMITTED")
            job["url"] = _console_url(response)
        if not job.get("url"):
            settings = record["config"].get("modelarts") or {}
            region = settings.get("region") or self._template().headers.get("region", "")
            job["url"] = training_console_url(str(job_id), region, settings.get("workspace_name", ""))
        record.update(status=f"{stage.upper()}_RUNNING", progress=submitted_progress,
                      stage=f"{job['name']} 已提交")
        self._store(record)
        while True:
            time.sleep(float(record["config"].get("poll_interval_seconds", 15)))
            if self._stopping.is_set() or record.get('delete_requested'):
                return False
            try:
                response = self._client(record).get(str(job_id))
            except requests.RequestException:
                record["message"] = "远程状态查询暂不可用，将继续重试；不重复创建作业。请检查网络及鉴权有效期。"
                self._store(record)
                continue
            record["message"] = ""
            job["url"] = _console_url(response) or job.get("url", "")
            status = _state(response).strip()
            normalized = status.lower()
            job["status"] = status or "RUNNING"
            record["progress"] = running_progress
            record["stage"] = f"{job['name']}: {job['status']}"
            self._store(record)
            if normalized in SUCCESS_STATES:
                job["status"] = "SUCCEEDED"
                return True
            if normalized in FAILURE_STATES:
                raise RuntimeError(f"作业 {job['name']} 运行失败（状态 {status}）：" +
                                   (_remote_error(response) or "平台未返回失败原因，请查看 ModelArts 作业日志"))

    def _store(self, record: dict[str, Any]) -> None:
        with self._lock:
            for item in [record, *record.get('jobs', [])]:
                if item.get('message'):
                    for secret in self._authorizations.values():
                        if secret:
                            item['message'] = item['message'].replace(secret, '[REDACTED]')
            self.records[record["id"]] = record
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{record['id']}.json"
            temporary = self.directory / f".{record['id']}.tmp"
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)

    def _load_disk(self) -> None:
        if not self.directory.exists():
            return
        for path in self.directory.glob("*.json"):
            if path.stem not in self.records:
                self.records[path.stem] = json.loads(path.read_text(encoding="utf-8"))
