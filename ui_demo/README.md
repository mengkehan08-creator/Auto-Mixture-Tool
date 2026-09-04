# Auto-Mixture Vue UI

这是 Auto-Mixture 配比实验配置界面的 Vue 3 演示项目。

## 本地开发

```bash
npm install
npm run dev
```

## 生成演示文件

```bash
npm run build
```

构建完成后会同时生成：

- `dist/app.html`：构建产物
- `index.html`：可直接双击、可发给其他电脑的单文件演示页

## 目录说明

- `src/components/strategy`：三类配比策略配置
- `src/components/steps`：训练、评测和确认提交步骤
- `src/data/defaults.js`：默认配置与选项
- `src/styles/main.css`：全局视觉样式
