import { copyFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
await copyFile(resolve(root, 'dist', 'app.html'), resolve(root, 'index.html'))
console.log('已生成可双击打开的 index.html')
