import { spawnSync } from 'node:child_process';
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const harmony = join(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(harmony, 'test/.generated');
rmSync(out, { recursive: true, force: true });

const sources = [];

function addDir(absDir, relDir) {
  for (const name of readdirSync(absDir)) {
    if (!name.endsWith('.ets')) {
      continue;
    }
    sources.push({
      full: join(absDir, name),
      rel: join(relDir, name.replace(/\.ets$/, '.ts')),
    });
  }
}

addDir(join(harmony, 'entry/src/main/ets/model'), 'model');
for (const name of ['DataSource.ets', 'MockDataSource.ets']) {
  sources.push({
    full: join(harmony, 'entry/src/main/ets/client', name),
    rel: join('client', name.replace(/\.ets$/, '.ts')),
  });
}

function rewrite(text) {
  return text.replace(/from '(\.[^']+)'/g, (_match, spec) => {
    return spec.endsWith('.ts') ? `from '${spec}'` : `from '${spec}.ts'`;
  });
}

for (const item of sources) {
  const dest = join(out, item.rel);
  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, rewrite(readFileSync(item.full, 'utf8')));
}

function walk(dir, found) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (name === 'oh_modules' || name === 'node_modules' || name === '.generated' || name === 'build') {
      continue;
    }
    try {
      const stat = readdirSync(full);
      void stat;
      walk(full, found);
    } catch (_err) {
      if (name.endsWith('.ets') || name.endsWith('.json5') || name.endsWith('.json') || name.endsWith('.ts')) {
        found.push(full);
      }
    }
  }
}

const files = [];
walk(harmony, files);
const forbidden = ['@kit.MapKit', 'MapKit', 'flutter', 'react-native', 'ArkUI-X', 'PlanCommand', 'storePassword', 'keyPassword'];
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  for (const word of forbidden) {
    if (text.includes(word)) {
      console.error(`forbidden ${word} in ${file}`);
      process.exit(1);
    }
  }
}
const moduleText = readFileSync(join(harmony, 'entry/src/main/module.json5'), 'utf8');
const networkText = readFileSync(join(harmony, 'entry/src/main/resources/base/profile/network_config.json'), 'utf8');
const httpText = readFileSync(join(harmony, 'entry/src/main/ets/client/HttpDataSource.ets'), 'utf8');
if (!moduleText.includes('ohos.permission.INTERNET') || !moduleText.includes('ohos.permission.GET_NETWORK_INFO')) {
  console.error('missing network permissions');
  process.exit(1);
}
if (!networkText.includes('"cleartextTrafficPermitted": true')) {
  console.error('cleartext HTTP is not enabled');
  process.exit(1);
}
if (!httpText.includes("@kit.NetworkKit") || !httpText.includes('http.createHttp')) {
  console.error('HttpDataSource does not use NetworkKit');
  process.exit(1);
}
const profile = readFileSync(join(harmony, 'build-profile.json5'), 'utf8');
if (!profile.includes('"signingConfigs": []') || profile.includes('storePassword')) {
  console.error('signing config is not empty');
  process.exit(1);
}

const tsc = spawnSync('npx', ['--yes', '-p', 'typescript@5.6.3', 'tsc', '-p', 'test/tsconfig.json'], {
  cwd: harmony,
  stdio: 'inherit',
});
if (tsc.status !== 0) {
  process.exit(tsc.status ?? 1);
}

const test = spawnSync(process.execPath, ['--experimental-strip-types', 'test/mock_parse.test.ts'], {
  cwd: harmony,
  stdio: 'inherit',
  env: process.env,
});
process.exit(test.status ?? 1);
