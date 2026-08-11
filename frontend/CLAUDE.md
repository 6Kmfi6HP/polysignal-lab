# frontend/ — Polysignal Dashboard

独立的 React + Vite 前端项目，位于 `frontend/`，与 `src/` 的 Python 后端独立运行。

## 技术栈

React · TypeScript · Vite · TanStack Router · TanStack Query + Axios · Radix UI · TailwindCSS v4 + `class-variance-authority` + `tailwind-merge` · Recharts · Vitest + Testing Library · Prettier + ESLint。版本以 `package.json` 为准。

## 约定

- 使用 TailwindCSS 类名，不用 CSS 模块文件
- 组件的 CSS 变体使用 `cva()` 定义
- 使用 Radix UI 原语构建交互组件
- 使用 axios 进行 API 调用（非 fetch）
- 测试使用 Testing Library 的 `render()` + `screen`
- 使用 `tsconfig.app.json` 作为源文件配置
- 不要修改 `knip.config.ts`

## 命令

脚本定义在 `package.json`，全部在 `frontend/` 目录下运行（`dev` / `build` / `lint` / `test` / `format`）。

## 相关

- 后端 API 服务在 `src/polysignal_lab/app/` 中
- Docker 部署见 `Dockerfile`