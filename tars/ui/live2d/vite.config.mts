import { defineConfig } from 'vite';
import path from 'path';

const sdk = process.env.TARS_CUBISM_SDK as string;
const out = process.env.TARS_AVATAR_APP as string;

export default defineConfig({
  root: './',
  base: './',
  logLevel: 'warn',
  resolve: {
    extensions: ['.ts', '.js'],
    alias: { '@framework': path.join(sdk, 'Framework/src') },
  },
  build: { target: 'es2022', outDir: out, emptyOutDir: true, assetsDir: 'assets' },
});
