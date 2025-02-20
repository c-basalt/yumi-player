import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import { execSync } from 'child_process'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'

const getVersion = () => {
  try {
    const version = execSync('git describe --tags --abbrev=0 --always').toString().trim()
    return version.startsWith('v') ? version : version.slice(0, 7)
  } catch (e) {
    return ''
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(getVersion())
  },
  plugins: [
    vue(),
    vueJsx(),
    {
      name: 'html-transform',
      transformIndexHtml(html) {
        return html.replace(
          /<title>(.*?)<\/title>/,
          `<title>$1 ${getVersion()}</title>`
        )
      }
    }
  ],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  }
})
