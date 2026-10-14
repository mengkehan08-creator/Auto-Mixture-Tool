import { copyFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
await copyFile(resolve(root, 'dist', 'app.html'), resolve(root, 'index.html'))
const staticDir = resolve(root, '..', 'src', 'auto_mixture_tool', 'api', 'static')
await mkdir(staticDir, { recursive: true })
await copyFile(resolve(root, 'dist', 'app.html'), resolve(staticDir, 'index.html'))
console.log('已发布前端到 API 静态目录；启动后通过 /ui 访问。')
