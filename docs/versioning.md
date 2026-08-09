# 版本控制与镜像通道

`pyproject.toml` 是应用程序版本的权威来源。它必须包含一个
稳定的 `X.Y.Z` SemVer 值。分支构建不会修改该值；构建
标识由 GitHub Actions 派生并存储在 OCI 标签中。

## 镜像通道

| 来源 | 源地址标签 | 移动标签 | 构建版本示例 |
| --- | --- | --- | --- |
| `debug/orderbook-recovery` | `sha-<full-commit>` | `debug-orderbook-recovery-<branch-id>` | `1.0.0-debug.184+abcdef123456` |
| `main` | `sha-<full-commit>` | `main` | `1.0.0-main.185+abcdef123456` |
| Git 标签 `v1.0.0` | 现有镜像摘要 | `1.0.0`、`1.0`、`stable` | 不变的候选镜像 |

注册表摘要是不可变的部署标识。`sha-*` 标签
记录源标识，而 `main`、`debug-*`、次版本号和 `stable`
标签是可移动的通道。请勿使用 `latest`。

## 运行时构建标识

CI 将相同的构建标识写入 OCI 标签和后端镜像内的
`/app/build-info.json`。清单包含应用程序版本、构建
版本、通道、源引用、完整和短提交 SHA，以及不可变的 `sha-*`
标签。如果这些字段缺失或不一致，镜像构建将失败。

仪表板通过 `GET /api/version` 发布此非敏感标识，并
在应用程序标题中显示紧凑的构建版本和提交信息。详细信息
面板公开完整的值，用于事件和部署关联。
OpenAPI 的应用程序版本来自同一清单。

没有嵌入清单的源代码检出使用显式的本地标识：
`<application-version>-local`，通道/引用为 `local`，提交/镜像标签为 null。
此回退仅用于开发。运行时镜像包含一个标记，
使得缺失清单成为致命错误，而不是静默报告本地构建。

`frontend/package.json` 仅对前端工具链包进行版本控制。它不是
PolySignal 应用程序版本，也不会显示为部署标识。

推送到 `main` 和 `debug/**` 会在
发布镜像之前运行完整的测试和前端门禁。其他分支和拉取请求运行验证但不
获得镜像发布权限。

## 调试构建

在 `debug/` 下创建一个分支并正常推送。CI 运行会发布
源地址标签和分支通道标签。分支通道包含
一个稳定的八字符分支标识符，因此类似规范化的分支
名称不会冲突。

对于可重复的调试，请部署 `sha-*` 标签或解析后的摘要，而不是
移动的 `debug-*` 标签。调试提升不会创建拉取请求；
集成到 `main` 仍然是显式的用户控制的 Git 操作。

## 稳定版本发布

在创建 `vX.Y.Z` 之前，将 `pyproject.toml` 中的 `project.version` 设置为相同的
`X.Y.Z` 值，并让目标提交通过 `main` CI 镜像构建。推送
标签会启动 `.github/workflows/release.yml`。

发布工作流采取失败关闭策略，除非以下所有条件都为真：

- Git 标签与 `project.version` 完全匹配；
- 被标记的提交包含在 `main` 中；
- `sha-*` 候选存在且标识被标记的提交；
- 候选是通过 `main` 通道构建的；
- 其 GitHub Actions 来源有效且由 `ci.yml` 签名；
- 现有的精确版本标签不指向另一个摘要。

工作流不会重新构建。它将验证后的摘要提升到精确
版本、主/次版本和 `stable` 标签，然后在 GitHub
Release 中记录该摘要。

## Compose 部署

两个后端服务使用相同的完整镜像引用：

```bash
# 移动集成通道
POLYSIGNAL_IMAGE_REF=ghcr.io/6kmfi6hp/polysignal-lab:main docker compose up -d

# 分支调试通道
POLYSIGNAL_IMAGE_REF=ghcr.io/6kmfi6hp/polysignal-lab:debug-orderbook-recovery-<branch-id> docker compose up -d

# 可重现的源构建
POLYSIGNAL_IMAGE_REF=ghcr.io/6kmfi6hp/polysignal-lab:sha-<full-commit> docker compose up -d

# 生产固定
POLYSIGNAL_IMAGE_REF=ghcr.io/6kmfi6hp/polysignal-lab@sha256:<digest> docker compose up -d
```

生产环境应使用摘要形式。仅更改通道标签绝不能
被视为运行中的容器已重新创建或升级的证明。

## Nautilus 依赖版本

NautilusTrader wheel 具有独立的不可变发布标识。
应用程序镜像必须继续在权威清单和 OCI 标签中记录其确切的 Nautilus 源提交、
发布标签和 wheel SHA256。正常的
应用程序调试分支使用当前固定的 wheel；候选 fork
wheel 不得覆盖生产清单或稳定镜像标签。