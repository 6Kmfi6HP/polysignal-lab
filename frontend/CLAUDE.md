# frontend/ — Polysignal Dashboard

这是一个独立的 React + Vite 前端项目，位于 `frontend/` 目录下。
与 `src/` 中的 Python 后端独立运行。

## 技术栈

- **框架**: React 19 + TypeScript 6
- **构建**: Vite 8
- **路由**: TanStack Router
- **数据获取**: TanStack Query + Axios
- **组件**: Radix UI (Dialog, DropdownMenu, Tabs, Tooltip, etc.)
- **样式**: TailwindCSS v4 + `class-variance-authority` + `tailwind-merge`
- **图表**: Recharts
- **测试**: Vitest + Testing Library + jsdom
- **格式化**: Prettier (with `prettier-plugin-tailwindcss`)
- **Lint**: ESLint 10 + `typescript-eslint`

## 常用命令

所有命令在 `frontend/` 目录下运行：

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器 |
| `npm run build` | TypeScript 检查 + 构建 |
| `npm run lint` | ESLint 代码检查 |
| `npm test` | 运行 Vitest 测试 |
| `npm test:watch` | 测试监听模式 |
| `npm run format` | Prettier 格式化 |
| `npm run format:check` | 检查格式 |

## 项目结构

- `src/` - 应用代码，包括路由、组件
- `public/` - 静态资源
- `vite.config.ts` - Vite 配置
- `package.json` - 依赖管理（非 monorepo，独立运行 `npm install`）

## 约定

- 使用 TailwindCSS 类名，不用 CSS 模块文件
- 组件的 CSS 变体使用 `cva()` 定义
- 使用 Radix UI 原语构建交互组件
- 使用 axios 进行 API 调用（非 fetch）
- 测试使用 Testing Library 的 `render()` + `screen`
- 使用 `tsconfig.app.json` 作为源文件配置
- 不要修改 `knip.config.ts`

## 相关

- 后端 API 服务在 `src/polysignal_lab/app/` 中
- Docker 部署见 `Dockerfile`
