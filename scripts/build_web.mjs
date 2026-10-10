import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.resolve(root, 'dist');
if (path.dirname(output) !== root || path.basename(output) !== 'dist') {
  throw new Error('Build output must be the project dist directory');
}
await fs.rm(output, { recursive: true, force: true });
const files = [
  ['web/index.html', 'index.html'],
  ['web/styles.css', 'styles.css'],
  ['web/app.mjs', 'app.mjs'],
  ['web/economics.mjs', 'economics.mjs'],
  ['web/fonts/Jua.woff2', 'assets/fonts/Jua.woff2'],
  ['web/fonts/GowunDodum.woff2', 'assets/fonts/GowunDodum.woff2'],
  ['web/fonts/Jua-OFL.txt', 'assets/fonts/Jua-OFL.txt'],
  ['web/fonts/GowunDodum-OFL.txt', 'assets/fonts/GowunDodum-OFL.txt'],
  ['data/processed/equipment_catalog.json', 'data/equipment_catalog.json'],
  ['presentation/smartfarm_proposal.pptx', 'presentation/smartfarm_proposal.pptx'],
  ['presentation/fonts/smartfarm_cute_fonts.zip', 'presentation/fonts/smartfarm_cute_fonts.zip'],
  ...['planning_demo_summary', 'planning_reference_scenarios', 'price_forecast_metrics_summary', 'inseason_metrics_summary']
    .map(name => [`reports/${name}.json`, `data/${name}.json`]),
  ...['01-cover', '04-equipment', '06-weather-risk', '07-growth-sensor']
    .map(name => [`assets/illustrated/${name}.png`, `assets/illustrated/${name}.png`]),
];
for (const [source, destination] of files) {
  const target = path.join(output, destination);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.copyFile(path.join(root, source), target);
}
console.log(`Built ${files.length} public files into dist (no server, database or private data).`);
